"""快递管家账号授权、导入结果及打印单号回传；不改微信物流接口。"""

import hmac
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import kuaidi100_client as kd100
from .admin_auth import AdminIdentity, audit_admin_action, ensure_admin_role, require_admin_write
from .commerce_models import Order, WechatExpressOrder
from .config import get_settings
from .database import get_db
from .wechat_express_service import RETRY_DELAY_LONG, _now, save_waybill

router = APIRouter(tags=["商城运营后台"])


@router.post("/api/admin/kuaidi100/authorize", summary="授权快递管家主账号（网页OAuth）")
def authorize(request: Request, identity: AdminIdentity = Depends(require_admin_write), db: Session = Depends(get_db)):
    ensure_admin_role(identity, "superadmin")
    try:
        url = kd100.authorize_url(db)
    except kd100.Kuaidi100Error as exc:
        raise HTTPException(409, exc.message) from None
    audit_admin_action(db, identity, action="kuaidi100_authorize", target_type="integration", target_id="kuaidiguanjia", request=request)
    db.commit()
    return {"url": url}


@router.get("/api/kuaidi100/callback", include_in_schema=False)
def oauth_callback(code: str = "", state: str = "", db: Session = Depends(get_db)):
    if not code or len(code) > 1024 or not state or len(state) > 128:
        raise HTTPException(400, "缺少快递管家授权信息，请从商城后台重新发起授权")
    try:
        kd100.finish_authorization(db, code, state)
    except kd100.Kuaidi100Error as exc:
        raise HTTPException(400, exc.message) from None
    db.commit()
    return HTMLResponse('<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><title>快递管家授权完成</title><p>快递管家授权完成，请返回商城后台刷新发货管理。</p><a href="/admin/orders">返回商城后台</a></html>',
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _verify_callback(raw: str) -> dict:
    """支持文档中的 data 对象和 JSON 字符串两种形态，始终要求签名。"""
    message = json.loads(raw, object_pairs_hook=_unique_object)
    s = get_settings()
    if not isinstance(message, dict) or not kd100.keys_configured() or message.get("app_key") != s.kuaidi100_key.strip():
        raise ValueError("app key")
    signature = message.get("sign")
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9A-Fa-f]{32}", signature):
        raise ValueError("signature")
    data = message.get("data")
    candidates = {data} if isinstance(data, str) else {
        json.dumps(data, ensure_ascii=ascii, separators=separators)
        for ascii in (False, True) for separators in ((",", ":"), (", ", ": "))
    }
    # 对象形态还保留原始 data 的 JSON 片段，避免签名受字段间空白影响。
    decoder, index = json.JSONDecoder(), 1
    while index < len(raw):
        index = len(raw) - len(raw[index:].lstrip())
        if raw[index:index + 1] in {"", "}"}:
            break
        key, index = decoder.raw_decode(raw, index)
        index = len(raw) - len(raw[index:].lstrip()) + 1  # 跳过冒号
        index = len(raw) - len(raw[index:].lstrip())
        start = index
        _, index = decoder.raw_decode(raw, index)
        if key == "data" and not isinstance(data, str):
            candidates.add(raw[start:index])
        index = len(raw) - len(raw[index:].lstrip())
        if raw[index:index + 1] == ",":
            index += 1
    params = {k: v for k, v in message.items() if k not in {"data", "sign"}}
    if any(not isinstance(v, (str, int)) for v in params.values()) or not all(k in params for k in ("app_key", "timestamp", "type")):
        raise ValueError("fields")
    if not any(hmac.compare_digest(signature.upper(), kd100._sign({**params, "data": text})) for text in candidates):
        raise ValueError("signature")
    if isinstance(data, str):
        data = json.loads(data, object_pairs_hook=_unique_object)
    return {**message, "data": data}


def _apply_callback(db: Session, message: dict) -> None:
    kind, data = message["type"], message["data"]
    if kind not in {"SEND", "FILLEXPNUM"}:
        return  # 微信物流推送继续走原流程；不把未知消息当作发货或撤单成功。
    items = data if kind == "FILLEXPNUM" and isinstance(data, list) else [data]
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("order_number"), str):
            raise ValueError("order")
        remote = item["order_number"]
        row = db.scalar(select(WechatExpressOrder).where(WechatExpressOrder.provider == kd100.PROVIDER,
                        WechatExpressOrder.remote_order_id == remote))
        if row is None:
            continue  # 旧轮次、其他系统订单不能覆盖本系统当前任务。
        order = db.scalar(select(Order).where(Order.id == row.order_id).with_for_update())
        db.refresh(row)
        if row.remote_order_id != remote or row.provider != kd100.PROVIDER:
            continue
        if kind == "FILLEXPNUM":
            result = kd100.waybill_result(item, remote)
            save_waybill(db, order, row, result["waybill_id"])
        elif not row.waybill_id and not row.cancel_requested and row.status not in {"conflict", "stopped"}:
            status = str(item.get("status", ""))
            if status not in {"200", "401"}:
                raise ValueError("status")
            row.status, row.next_action = ("waiting", "verify") if status == "200" else ("failed", "none")
            row.message = "快递管家导入成功，请到管家打印面单，等待单号回传" if status == "200" else "快递管家导入失败，请在管家核对订单资料后重试"
            row.lease_token, row.lease_until = "", None
            row.next_attempt_at = _now() + RETRY_DELAY_LONG


@router.post("/api/kuaidi100/callback", include_in_schema=False)
async def callback(request: Request, db: Session = Depends(get_db)):
    # 外部回调不使用管理员会话，使用管家 App Secret 验签。
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 256 * 1024:
            raise HTTPException(413, "回调报文过大")
    try:
        message = _verify_callback(raw.decode("utf-8").strip())
        _apply_callback(db, message)
        db.commit()
    except (ValueError, TypeError, KeyError, kd100.Kuaidi100Error):
        db.rollback()
        return {"status": "400"}
    return {"status": "200"}
