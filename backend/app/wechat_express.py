"""微信物流助手客户端；只使用小程序服务端接口，密钥仅在服务器。"""

import base64
import binascii
import json
import math
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .commerce_models import Product, WechatAccessToken
from .config import get_settings

API_BASE = "https://api.weixin.qq.com"
TOKEN_URL = API_BASE + "/cgi-bin/stable_token"
ACCOUNT_GETALL_PATH = "/cgi-bin/express/business/account/getall"
ORDER_ADD_PATH = "/cgi-bin/express/business/order/add"
ORDER_GET_PATH = "/cgi-bin/express/business/order/get"
ORDER_CANCEL_PATH = "/cgi-bin/express/business/order/cancel"
PATH_GET_PATH = "/cgi-bin/express/business/path/get"
ORDER_BATCHGET_PATH = "/cgi-bin/express/business/order/batchget"
PRINTER_UPDATE_PATH = "/cgi-bin/express/business/printer/update"
HTTP_TIMEOUT = 8.0
ACTION_TITLES = {100001: "已揽件", 100002: "揽件失败", 100003: "已分配快递员",
                 200001: "运输中", 300002: "派送中", 300003: "已签收", 300004: "签收失败",
                 400001: "运单已取消", 400002: "运单滞留"}


class WechatExpressError(Exception):
    def __init__(self, message: str, code: str = "error", uncertain: bool = False):
        super().__init__(message)
        self.message, self.code, self.uncertain = message, code, uncertain


def configured() -> bool:
    s = get_settings()
    return bool(s.wechat_app_id.strip() and s.wechat_app_secret.strip())


def access_token(db: Session, force_refresh: bool = False) -> str:
    row = db.scalar(select(WechatAccessToken).where(WechatAccessToken.id == 1).with_for_update())
    now = datetime.utcnow()
    if row and not force_refresh and row.expires_at and row.expires_at > now + timedelta(minutes=5):
        token = row.access_token
        db.commit()
        return token
    s = get_settings()
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.post(TOKEN_URL, json={"grant_type": "client_credential",
                "appid": s.wechat_app_id.strip(), "secret": s.wechat_app_secret.strip(), "force_refresh": False})
            response.raise_for_status()
            result = response.json()
        token = result.get("access_token") if isinstance(result, dict) else None
        ttl = int(result.get("expires_in", 0)) if isinstance(result, dict) else 0
        if not isinstance(token, str) or not token or not 300 < ttl <= 7200:
            raise ValueError()
    except (httpx.HTTPError, ValueError, TypeError):
        raise WechatExpressError("微信凭证获取失败，请核对AppID、AppSecret与服务器IP白名单", "token") from None
    if row is None:
        row = WechatAccessToken(id=1)
        db.add(row)
    row.access_token, row.expires_at = token, now + timedelta(seconds=ttl)
    db.commit()
    return token


def request_api(db: Session, path: str, payload: dict | None = None, *, method: str = "POST") -> dict:
    token = access_token(db)
    for attempt in range(2):
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT) as client:
                response = client.request(method, API_BASE + path, params={"access_token": token},
                    **({"json": payload or {}} if method != "GET" else {}))
                response.raise_for_status()
                result = response.json()
            if not isinstance(result, dict):
                raise ValueError()
            code = int(result.get("errcode", 0))
        except (httpx.HTTPError, ValueError, TypeError):
            raise WechatExpressError("微信请求结果未能确认，请先补查，勿重复下单", "network", True) from None
        if code in {40001, 40014, 42001} and attempt == 0:
            token = access_token(db, force_refresh=True)
            continue
        if code:
            messages = {40003: "买家openid无效，请核对小程序账号", 47001: "微信下单参数不完整或格式错误",
                9300501: "快递公司拒绝请求，请核对中通账号、地址和服务类型", 9300503: "快递公司编码不存在",
                9300510: "快递服务类型无效", 9300525: "快递客户编码未绑定", 9300526: "收寄件字段超出长度限制",
                9300531: "快递客户编码或密码无效", 9300534: "小程序与买家openid不匹配",
                9300535: "商品图片、名称或数量无效", 9300506: "运单不存在"}
            raise WechatExpressError(messages.get(code, "微信物流接口暂不可用，请核对配置后补查"), str(code), code in {-1, 9300502})
        return result
    raise WechatExpressError("微信凭证失效，请核对小程序配置", "token")


def delivery_bindings(db: Session) -> list[dict]:
    result = request_api(db, ACCOUNT_GETALL_PATH, method="GET")
    rows = result.get("list")
    if not isinstance(rows, list):
        raise WechatExpressError("微信绑定账号响应格式异常", uncertain=True)
    return [{"delivery_id": str(r.get("delivery_id") or ""), "biz_id": str(r.get("biz_id") or ""),
        "status_code": r.get("status_code"), "quota_num": r.get("quota_num"),
        "service_types": r.get("service_type") if isinstance(r.get("service_type"), list) else []}
        for r in rows if isinstance(r, dict)]


def resolve_binding(db: Session) -> dict:
    s = get_settings()
    matches = [r for r in delivery_bindings(db) if r["delivery_id"].upper() == s.wechat_express_delivery_id.strip().upper()
        and r["status_code"] in (0, "0") and r["biz_id"]
        and (not s.wechat_express_biz_id.strip() or r["biz_id"] == s.wechat_express_biz_id.strip())]
    if len(matches) != 1:
        raise WechatExpressError("请确认中通账号审核通过；多个绑定账号时请在服务器指定biz_id", "binding")
    return matches[0]


def _short(value: str, limit: int) -> str:
    return value.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


def order_payload(db: Session, order, remote_order_id: str, openid: str, package: dict) -> dict:
    s = get_settings()
    binding = resolve_binding(db)
    services = binding["service_types"]
    if s.wechat_express_service_type.strip() and s.wechat_express_service_name.strip():
        kind, name = s.wechat_express_service_type.strip(), s.wechat_express_service_name.strip()
    elif services:
        kind, name = services[0].get("service_type"), services[0].get("service_name")
    else:
        raise WechatExpressError("未获取到中通服务类型，请在服务器填写服务类型ID和名称", "binding")
    try:
        kind = int(kind)
        if kind < 0 or not name:
            raise ValueError()
    except (ValueError, TypeError):
        raise WechatExpressError("中通服务类型ID必须为有效整数", "binding") from None
    sender = {"name": s.wechat_express_sender_name.strip(), "mobile": s.wechat_express_sender_phone.strip(),
        "province": s.wechat_express_sender_province.strip(), "city": s.wechat_express_sender_city.strip(),
        "area": s.wechat_express_sender_district.strip(), "address": s.wechat_express_sender_address.strip()}
    receiver = {"name": order.receiver_name.strip(), "mobile": order.receiver_phone.strip(), "address": order.receiver_address.strip()}
    for person in (sender, receiver):
        for key, limit in (("name", 64), ("mobile", 32), ("province", 64), ("city", 64), ("area", 64), ("address", 512)):
            if key in person and (len(person[key].encode()) > limit or (key in {"name", "mobile", "address"} and not person[key])):
                raise WechatExpressError("收寄件信息缺失或超出微信字段长度限制")
    if not re.fullmatch(r"1[0-9]{10}", receiver["mobile"]):
        raise WechatExpressError("收件手机号格式异常，请核对原订单")
    details, shop_details = [], []
    try:
        items = json.loads(order.items_json)
        if not isinstance(items, list) or not items:
            raise ValueError()
        for item in items:
            product = db.get(Product, item["product_id"])
            image = item.get("image") or (product.image if product else "")
            if not image.startswith("https://"):
                origin = s.wechat_express_asset_origin.rstrip("/")
                if not origin.startswith("https://") or not image or "/" in image or "\\" in image:
                    raise ValueError()
                image = origin + "/product-assets/" + quote(image, safe="")
            if not urlsplit(image).netloc:
                raise ValueError()
            count = int(item["quantity"])
            if count < 1 or not item["name"]:
                raise ValueError()
            name = _short(str(item["name"]), 128)
            details.append({"name": name, "count": count})
            shop_details.append({"goods_name": name, "goods_img_url": image, "goods_desc": "数量：" + str(count)})
        if any(not math.isfinite(float(package[k])) or float(package[k]) <= 0 for k in ("weight", "space_x", "space_y", "space_z")):
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError):
        raise WechatExpressError("商品图片、商品明细或实际包裹重量尺寸不完整，请在后台核对") from None
    return {"add_source": 0, "order_id": remote_order_id, "openid": openid,
        "delivery_id": binding["delivery_id"], "biz_id": binding["biz_id"], "sender": sender, "receiver": receiver,
        "cargo": {"count": 1, **package, "detail_list": details},
        "shop": {"wxa_path": f"/pages/orders/logistics?id={order.id}", "detail_list": shop_details},
        "insured": {"use_insured": 0}, "service": {"service_type": kind, "service_name": name}}


def create_waybill(db: Session, payload: dict) -> str:
    result = request_api(db, ORDER_ADD_PATH, payload)
    waybill = result.get("waybill_id")
    if not isinstance(waybill, str) or not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", waybill) or result.get("order_id") != payload["order_id"]:
        raise WechatExpressError("微信下单结果未能确认，请先补查", "empty_waybill", True)
    return waybill


def lookup_waybill(db: Session, delivery_id: str, remote: str) -> dict:
    result = request_api(db, ORDER_BATCHGET_PATH, {"order_list": [{"delivery_id": delivery_id, "order_id": remote}]})
    rows = result.get("order_list")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise WechatExpressError("补查结果不完整，请稍后继续补查；不会自动重下", uncertain=True)
    row = rows[0]
    if row.get("order_id") != remote or row.get("delivery_id") != delivery_id or row.get("errcode") not in (0, "0"):
        raise WechatExpressError("尚未确认原运单结果，请核对微信物流助手订单；不会自动重下", uncertain=True)
    if not isinstance(row.get("waybill_id"), str) or not row["waybill_id"] or row.get("order_status") not in (0, 1):
        raise WechatExpressError("微信运单状态不完整，请继续补查", uncertain=True)
    return row


def cancel_waybill(db: Session, delivery_id: str, remote: str, waybill: str, openid: str) -> None:
    result = request_api(db, ORDER_CANCEL_PATH, {"openid": openid, "delivery_id": delivery_id, "order_id": remote, "waybill_id": waybill})
    if result.get("errcode") not in (0, "0"):
        raise WechatExpressError("撤单结果未能确认，请先补查运单状态", uncertain=True)


def print_html(db: Session, delivery_id: str, remote: str, waybill: str, openid: str) -> str:
    result = request_api(db, ORDER_GET_PATH, {"openid": openid, "delivery_id": delivery_id, "order_id": remote,
        "waybill_id": waybill, "print_type": get_settings().wechat_express_print_type})
    if result.get("order_id") != remote or result.get("delivery_id") != delivery_id or result.get("waybill_id") != waybill or result.get("order_status") != 0:
        raise WechatExpressError("运单已取消或不匹配，不能打印")
    try:
        encoded = result["print_html"]
        if not isinstance(encoded, str) or len(encoded) > 1400000:
            raise ValueError()
        source = base64.b64decode(encoded, validate=True).decode("utf-8")
        if not source.strip():
            raise ValueError()
        return source
    except (KeyError, ValueError, TypeError, binascii.Error):
        raise WechatExpressError("微信暂未返回可打印面单，请稍后重试") from None


def query_track(db: Session, delivery_id: str, remote: str, waybill: str, openid: str) -> list[dict]:
    result = request_api(db, PATH_GET_PATH, {"openid": openid, "delivery_id": delivery_id, "order_id": remote, "waybill_id": waybill})
    rows = result.get("path_item_list")
    if not isinstance(rows, list):
        raise WechatExpressError("微信物流轨迹响应格式异常", uncertain=True)
    events = []
    for row in rows:
        try:
            events.append({"time": datetime.fromtimestamp(int(row["action_time"]), tz=timezone.utc),
                "title": ACTION_TITLES.get(row.get("action_type"), "物流动态"), "description": str(row["action_msg"])[:4000]})
        except (TypeError, ValueError, KeyError, OverflowError, OSError):
            raise WechatExpressError("微信物流轨迹内容异常", uncertain=True) from None
    return sorted(events, key=lambda r: r["time"], reverse=True)


def update_printer(db: Session, openid: str, update_type: str) -> None:
    result = request_api(db, PRINTER_UPDATE_PATH, {"openid": openid, "update_type": update_type})
    if result.get("errcode") not in (0, "0"):
        raise WechatExpressError("打印员设置结果未能确认，请稍后查询", uncertain=True)
