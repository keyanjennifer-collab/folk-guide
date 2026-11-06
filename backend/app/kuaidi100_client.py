"""快递100「快递管家」开放平台；导入后在管家打印，再接收单号回传或补查。"""

import hashlib
import hmac
import json
import math
import re
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import wechat_express as wx_api
from .commerce_models import Kuaidi100Authorization
from .config import get_settings
from .models import User

BASE_URL = "https://b.kuaidi100.com"
IMPORT_PATH = "/v7/open/api/send"
QUERY_PATH = "/v7/open/api/queryKuaidiNum"
PROVIDER = "kuaidiguanjia"
ZTO_COM = "zhongtong"
HTTP_TIMEOUT = 12.0


class Kuaidi100Error(Exception):
    def __init__(self, message: str, code: str = "error", uncertain: bool = False):
        super().__init__(message)
        self.message, self.code, self.uncertain = message, code, uncertain


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def keys_configured() -> bool:
    s = get_settings()
    return bool(s.kuaidi100_enabled and s.kuaidi100_key.strip() and s.kuaidi100_secret.strip())


def configured(db: Session | None = None) -> bool:
    if not keys_configured():
        return False
    s = get_settings()
    saved = db.get(Kuaidi100Authorization, s.kuaidi100_key.strip()) if db is not None else None
    return bool((saved and saved.access_token) or s.kuaidi100_access_token.strip() or s.kuaidi100_refresh_token.strip())


def _sign(params: dict) -> str:
    """参数名升序拼接参数名和值，首尾加 App Secret，再 MD5 转大写。"""
    secret = get_settings().kuaidi100_secret.strip()
    raw = secret + "".join(str(k) + str(v) for k, v in sorted(params.items()) if k != "sign") + secret
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()


def _post(path: str, payload: dict, *, uncertain: bool = False) -> dict:
    payload = {**payload, "sign": _sign(payload)}
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.post(BASE_URL + path, data=payload)
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise Kuaidi100Error("快递管家响应未能确认，请补查，勿重复导入订单", "network", uncertain) from exc
    if not isinstance(result, dict):
        raise Kuaidi100Error("快递管家返回格式异常，请补查", "format", uncertain)
    if path.startswith("/open/oauth/") and result.get("access_token"):
        return result
    status = str(result.get("status", ""))
    if status != "200":
        message = str(result.get("message") or "快递管家未明确返回处理成功")[:200]
        s = get_settings()
        for value in (s.kuaidi100_key, s.kuaidi100_secret, s.kuaidi100_access_token,
                      s.kuaidi100_refresh_token, payload.get("access_token"), payload.get("refresh_token")):
            if value:
                message = message.replace(str(value), "[已隐藏]")
        raise Kuaidi100Error(message, status or "format", uncertain and (not status or status.startswith("5")))
    return result


def _save_token(row: Kuaidi100Authorization, result: dict) -> None:
    try:
        token, refresh = result["access_token"], result["refresh_token"]
        seconds = int(result["expires_in"])
        if not isinstance(token, str) or not token or len(token) > 1024 or not isinstance(refresh, str) or not refresh or len(refresh) > 1024 or not 0 < seconds <= 366 * 86400:
            raise ValueError()
    except (KeyError, ValueError, TypeError):
        raise Kuaidi100Error("快递管家授权结果不完整，请重新授权", "authorization") from None
    row.access_token, row.refresh_token = token, refresh
    row.expires_at = datetime.utcnow() + timedelta(seconds=seconds)


def _access_token(db: Session) -> str:
    s = get_settings()
    if not keys_configured():
        raise Kuaidi100Error("请配置快递管家的 App Key 和 App Secret", "configuration")
    row = db.scalar(select(Kuaidi100Authorization).where(Kuaidi100Authorization.app_key == s.kuaidi100_key.strip()).with_for_update())
    if row and row.access_token:
        if row.expires_at and row.expires_at <= datetime.utcnow() + timedelta(minutes=5):
            return _refresh_access_token(db)
        return row.access_token
    if s.kuaidi100_access_token.strip():
        return s.kuaidi100_access_token.strip()
    if s.kuaidi100_refresh_token.strip():
        return _refresh_access_token(db)
    raise Kuaidi100Error("请先在发货管理中授权快递管家账号", "authorization")


def _refresh_access_token(db: Session) -> str:
    s = get_settings()
    row = db.scalar(select(Kuaidi100Authorization).where(Kuaidi100Authorization.app_key == s.kuaidi100_key.strip()).with_for_update())
    refresh = row.refresh_token if row and row.refresh_token else s.kuaidi100_refresh_token.strip()
    if not refresh:
        raise Kuaidi100Error("快递管家授权已失效，请在后台重新授权", "authorization")
    result = _post("/open/oauth/refreshToken", {
        "client_id": s.kuaidi100_key.strip(), "client_secret": s.kuaidi100_secret.strip(),
        "refresh_token": refresh, "grant_type": "refresh_token", "timestamp": str(int(time.time() * 1000)),
    })
    if row is None:
        row = Kuaidi100Authorization(app_key=s.kuaidi100_key.strip())
        db.add(row)
    _save_token(row, result)
    db.commit()
    return row.access_token


def _request(db: Session, path: str, data: dict, *, uncertain: bool = False) -> dict:
    payload = {
        "app_key": get_settings().kuaidi100_key.strip(), "access_token": _access_token(db),
        "timestamp": str(int(time.time())), "data": _json(data),
    }
    try:
        return _post(path, payload, uncertain=uncertain)
    except Kuaidi100Error as exc:
        # 仅明确的令牌失效响应允许刷新后重试；超时或业务失败绝不重发导单。
        if exc.code == "401" and re.search(r"(?i)(token|令牌).*(过期|失效|expired|invalid)", exc.message):
            payload["access_token"] = _refresh_access_token(db)
            return _post(path, payload, uncertain=uncertain)
        raise


def authorize_by_mobile(db: Session, mobile: str) -> None:
    """用手机号直接获取 access_token（client_credentials 模式），无需网页授权。

    快递管家文档：https://www.kuaidi100.com/ecommerce/api/index.html?name=11
    调用成功后 access_token 有效期 1 年，可用 refresh_token 刷新。
    注意：此方式会创建子账号，订单在子账号下，电子面单需在子账号单独绑定。
    """
    s = get_settings()
    mobile = mobile.strip()
    if not re.fullmatch(r"1[0-9]{10}", mobile):
        raise Kuaidi100Error("手机号格式不正确", "mobile")
    if not keys_configured():
        raise Kuaidi100Error("请配置快递管家的 App Key 和 App Secret", "configuration")
    params = {
        "client_id": s.kuaidi100_key.strip(),
        "client_secret": s.kuaidi100_secret.strip(),
        "timestamp": str(int(time.time() * 1000)),
        "grant_type": "client_credentials",
        "mobile": mobile,
    }
    result = _post("/open/oauth/token", params)
    row = db.scalar(select(Kuaidi100Authorization).where(Kuaidi100Authorization.app_key == s.kuaidi100_key.strip()))
    if row is None:
        row = Kuaidi100Authorization(app_key=s.kuaidi100_key.strip())
        db.add(row)
    _save_token(row, result)


def authorize_url(db: Session) -> str:
    """构造网页 OAuth 授权 URL，用主账号登录授权，订单在主账号下。"""
    s = get_settings()
    callback = s.kuaidi100_callback_url.strip()
    parsed = urlsplit(callback)
    if not keys_configured() or parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment or parsed.username:
        raise Kuaidi100Error("请配置管家 App Key、App Secret 和公网 HTTPS 回调地址 KUAIDI100_CALLBACK_URL")
    row = db.get(Kuaidi100Authorization, s.kuaidi100_key.strip())
    if row is None:
        row = Kuaidi100Authorization(app_key=s.kuaidi100_key.strip())
        db.add(row)
    state = secrets.token_urlsafe(32)
    row.oauth_state_hash = hashlib.sha256(state.encode()).hexdigest()
    row.oauth_state_expires_at = datetime.utcnow() + timedelta(minutes=10)
    params = {"client_id": row.app_key, "response_type": "code", "redirect_uri": callback,
              "state": state, "timestamp": str(int(time.time() * 1000))}
    return BASE_URL + "/open/oauth/authorize?" + urlencode({**params, "sign": _sign(params)})


def finish_authorization(db: Session, code: str, state: str) -> None:
    s = get_settings()
    row = db.scalar(select(Kuaidi100Authorization).where(Kuaidi100Authorization.app_key == s.kuaidi100_key.strip()).with_for_update())
    if not keys_configured() or not row or not row.oauth_state_hash or not row.oauth_state_expires_at or row.oauth_state_expires_at <= datetime.utcnow() or not hmac.compare_digest(row.oauth_state_hash, hashlib.sha256(state.encode()).hexdigest()):
        raise Kuaidi100Error("授权已过期或状态不匹配，请从商城后台重新发起授权", "state")
    result = _post("/open/oauth/accessToken", {
        "client_id": row.app_key, "client_secret": s.kuaidi100_secret.strip(),
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": s.kuaidi100_callback_url.strip(), "timestamp": str(int(time.time() * 1000)),
    })
    _save_token(row, result)
    row.oauth_state_hash, row.oauth_state_expires_at = "", None


def order_payload(db: Session, order, remote_order_id: str, package: dict) -> dict:
    s = get_settings()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,30}", remote_order_id):
        raise Kuaidi100Error("快递管家订单编号须为30位以内字母、数字、下划线或连字符")
    try:
        items = json.loads(order.items_json)
        if not isinstance(items, list) or not items:
            raise ValueError()
        goods = [{"name": str(item["name"])[:30], "count": int(item["quantity"])} for item in items]
        if any(not g["name"] or not 0 < g["count"] <= 999 for g in goods):
            raise ValueError()
        values = {key: float(package[key]) for key in ("weight", "space_x", "space_y", "space_z")}
        if any(not math.isfinite(v) or v <= 0 for v in values.values()):
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError):
        raise Kuaidi100Error("商品明细或包裹重量尺寸不完整，请在后台核对") from None
    payload = {
        "order_number": remote_order_id, "cargo_name": "、".join(g["name"] for g in goods)[:100],
        "cargo_count": sum(g["count"] for g in goods), "package_count": 1,
        "weight": values["weight"], "volume": str(round(values["space_x"] * values["space_y"] * values["space_z"], 3)),
        "goods_list": goods, "express_company": ZTO_COM, "api_pay_mode": s.kuaidi100_api_pay_mode,
        "receiver": {"name": order.receiver_name.strip(), "mobile": order.receiver_phone.strip(), "addr": order.receiver_address.strip()},
        "sender": {"name": s.wechat_express_sender_name.strip(), "mobile": s.wechat_express_sender_phone.strip(),
                   "addr": "".join(getattr(s, "wechat_express_sender_" + k).strip() for k in ("province", "city", "district", "address"))},
    }
    for person in (payload["sender"], payload["receiver"]):
        if any(not person[k] or len(person[k]) > limit for k, limit in (("name", 30), ("mobile", 30), ("addr", 100))):
            raise Kuaidi100Error("收寄件姓名、电话或地址缺失，或超出快递管家字段长度限制")
    # 沿用现有微信绑定和订单字段，交给管家打单；微信客户端和物流查询不变。
    if s.wechat_express_enabled:
        user = db.get(User, order.user_id)
        if not user or not user.openid:
            raise Kuaidi100Error("买家微信账号缺失，请核对原订单")
        wx = wx_api.order_payload(db, order, remote_order_id, user.openid, package)
        payload.update(order_source="WX", openid=wx["openid"], express_custom_code=wx["biz_id"],
                       express_company=wx["delivery_id"], order_page_url=wx["shop"]["wxa_path"], service_type=wx["service"]["service_name"])
        for item, detail in zip(goods, wx["shop"]["detail_list"]):
            item["img_url"] = detail["goods_img_url"]
    return payload


def import_order(db: Session, payload: dict) -> None:
    _request(db, IMPORT_PATH, payload, uncertain=True)


def lookup_waybill(db: Session, remote_order_id: str) -> dict:
    result = _request(db, QUERY_PATH, {"order_number": remote_order_id})
    return waybill_result(result, remote_order_id)


def waybill_result(result: dict, remote: str) -> dict:
    number = result.get("kuaidi_num")
    carrier = result.get("company_code") or result.get("kuaidi_com")
    if result.get("order_number") != remote or carrier not in {ZTO_COM, "ZTO"} or not isinstance(number, str) or not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", number):
        raise Kuaidi100Error("快递管家尚未返回匹配的单包裹中通运单，请在管家核对后补查", "waybill", True)
    return {"waybill_id": number, "order_status": 0}


def integration_status(db: Session) -> dict:
    s = get_settings()
    return {"enabled": s.kuaidi100_enabled, "configured": configured(db), "key_set": bool(s.kuaidi100_key.strip()),
            "secret_set": bool(s.kuaidi100_secret.strip()), "carrier_code": ZTO_COM,
            "carrier_name": s.wechat_express_carrier_name.strip() or "中通快递", "supports_cancel": False}
