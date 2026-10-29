"""微信物流助手的管理入口、运单任务和隔离的官方面单预览。"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import wechat_express as api
from .admin_auth import AdminIdentity, audit_admin_action, ensure_admin_role, require_admin_identity, require_admin_write
from .commerce_models import Order, WechatExpressOrder
from .config import get_settings
from .database import get_db
from .wechat_express_service import _openid_of, request_cancel

router = APIRouter(tags=["商城运营后台"])


def _enabled() -> None:
    if not get_settings().wechat_express_enabled or not api.configured():
        raise HTTPException(409, "请先在服务器配置并启用微信物流助手")


@router.get("/api/admin/wechat-express", summary="查看微信物流助手绑定状态")
def integration_status(response: Response, identity: AdminIdentity = Depends(require_admin_identity), db: Session = Depends(get_db)):
    s = get_settings()
    bindings, error = [], ""
    if s.wechat_express_enabled and api.configured():
        try:
            bindings = api.delivery_bindings(db)
        except api.WechatExpressError as exc:
            error = exc.message
    response.headers["Cache-Control"] = "private, no-store"
    return {"enabled": s.wechat_express_enabled, "configured": api.configured(),
        "delivery_id": s.wechat_express_delivery_id, "carrier_name": s.wechat_express_carrier_name,
        "bindings": bindings, "binding_error": error,
        "printer_guide": "在连接热敏打印机的电脑打开官方面单，按Ctrl+P打印；打印并打包后再确认发货。"}


class PackageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    weight: float = Field(ge=0.001, le=1000, description="实际包裹总重量，千克")
    space_x: float = Field(gt=0, le=1000, description="长，厘米")
    space_y: float = Field(gt=0, le=1000, description="宽，厘米")
    space_z: float = Field(gt=0, le=1000, description="高，厘米")


class PrinterInput(BaseModel):
    openid: str = Field(min_length=6, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    update_type: str = Field(pattern="^(bind|unbind)$")


@router.post("/api/admin/wechat-express/printer", summary="配置微信打单PC软件打印员（可选）")
def update_printer(data: PrinterInput, request: Request, identity: AdminIdentity = Depends(require_admin_write), db: Session = Depends(get_db)):
    ensure_admin_role(identity, "superadmin")
    _enabled()
    try:
        api.update_printer(db, data.openid, data.update_type)
    except api.WechatExpressError as exc:
        raise HTTPException(502, exc.message) from None
    audit_admin_action(db, identity, action="wechat_printer_" + data.update_type, target_type="integration", target_id="wechat-express", request=request)
    db.commit()
    return {"message": "打印员配置已更新"}


@router.post("/api/admin/orders/{order_id}/shipping-sync/{action}", summary="生成、补查或撤销微信运单")
def sync_action(order_id: int, action: str, request: Request, data: PackageInput | None = None,
                identity: AdminIdentity = Depends(require_admin_write), db: Session = Depends(get_db)):
    _enabled()
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order:
        raise HTTPException(404, "订单不存在")
    row = db.get(WechatExpressOrder, order_id)
    now = datetime.utcnow()
    if order.status != "paid" or order.refund_number:
        raise HTTPException(409, "只有已付款待发货且没有退款中的订单可以操作运单")
    if action in {"create", "retry"}:
        if data is None:
            raise HTTPException(422, "请填写本次包裹实际重量及长宽高")
        if order.tracking_number or (row and (row.status not in {"failed", "cancelled"} or (row.lease_until and row.lease_until > now))):
            raise HTTPException(409, "运单已存在或正在处理，请先补查或撤销，勿重复下单")
        if row is None:
            row = WechatExpressOrder(order_id=order.id)
            db.add(row)
        else:
            row.attempt_round += 1
        row.status, row.next_action, row.message = "queued", "create", "已安排生成微信运单，尚未确认发货"
        row.remote_order_id, row.waybill_id, row.cancel_requested = "", "", False
        row.package_json = json.dumps(data.model_dump(), separators=(",", ":"))
        row.lease_token, row.lease_until, row.next_attempt_at = "", None, now
    elif action == "verify":
        if row is None or row.status != "unknown":
            raise HTTPException(409, "只有结果未确认的运单可以补查")
        if row.lease_until and row.lease_until > now:
            raise HTTPException(409, "正在处理，请稍后刷新")
        row.next_action, row.next_attempt_at = "verify", now
    elif action == "cancel":
        if row is None:
            raise HTTPException(404, "运单任务不存在")
        request_cancel(db, order, row)
    else:
        raise HTTPException(404, "操作不存在")
    audit_admin_action(db, identity, action="wechat_waybill_" + action, target_type="order", target_id=order.id, request=request)
    db.commit()
    return {"message": "已安排处理，请稍后刷新状态"}


@router.get("/api/admin/orders/{order_id}/waybill", include_in_schema=False)
def waybill_preview(order_id: int, request: Request, identity: AdminIdentity = Depends(require_admin_identity), db: Session = Depends(get_db)):
    _enabled()
    order = db.get(Order, order_id)
    row = db.get(WechatExpressOrder, order_id)
    if not order or not row:
        raise HTTPException(404, "运单不存在")
    if row.status != "ordered" or row.cancel_requested or order.refund_number or order.status not in {"paid", "shipped", "completed"} or row.waybill_id != order.tracking_number or row.carrier_name != order.carrier:
        raise HTTPException(409, "当前运单不可打印，请先完成补查或撤单处理")
    try:
        source = api.print_html(db, row.delivery_id, row.remote_order_id, row.waybill_id, _openid_of(db, order))
    except api.WechatExpressError as exc:
        raise HTTPException(502, exc.message) from None
    audit_admin_action(db, identity, action="wechat_waybill_view", target_type="order", target_id=order.id, request=request)
    db.commit()
    notice = '<style>@media print{#waybill-guide{display:none}}</style><p id="waybill-guide">请按 Ctrl+P，选择热敏打印机和对应纸张，缩放100%，关闭页眉页脚。打印并打包后返回后台确认发货。</p>'
    return HTMLResponse(source + notice, headers={"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox allow-modals; default-src 'none'; img-src data: https:; style-src 'unsafe-inline' https:; font-src data: https:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"})
