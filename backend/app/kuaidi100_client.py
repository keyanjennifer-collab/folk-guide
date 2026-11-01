"""快递100电子面单客户端：负责运单生成、取消、版权底打印。

设计要点：
- 凭证（key/secret/partnerId/partnerKey/netCode）全部走 Settings 读取，不写进代码。
- 共用 wechat_express._split_chinese_address 解析收件人省市区，避免重复实现。
- 与微信物流助手并存：运单生成/取消走快递100，物流轨迹推送由微信侧负责。
- 不复用 wechat_express 的 token 体系（快递100用 MD5 签名 + 时间戳鉴权）。
"""

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from . import wechat_express as wx_api
from .commerce_models import Product
from .config import get_settings

# 快递100 电子面单接口
ORDER_URL = "https://api.kuaidi100.com/label/order"
# 订阅物流轨迹推送（可选，当前由微信物流助手负责轨迹）
SUBSCRIBE_URL = "https://api.kuaidi100.com/label/order"
HTTP_TIMEOUT = 12.0

# 中通在快递100的快递公司编码
ZTO_COM = "zhongtong"

# 常见错误码
ERROR_MESSAGES = {
    "200": "成功",
    "400": "请求参数错误",
    "401": "授权失败：APP Key 或 Secret 错误",
    "403": "无权限访问接口",
    "500": "快递100服务端异常",
}


class Kuaidi100Error(Exception):
    """快递100接口异常。

    uncertain=True 表示请求结果未知（网络超时、5xx），调用方需补查；
    uncertain=False 表示明确失败（业务错误），可直接标记 failed。
    """

    def __init__(self, message: str, code: str = "error", uncertain: bool = False):
        super().__init__(message)
        self.message, self.code, self.uncertain = message, code, uncertain


def configured() -> bool:
    """快递100是否完整配置了下单所需凭证。"""
    s = get_settings()
    return bool(
        s.kuaidi100_enabled
        and s.kuaidi100_key.strip()
        and s.kuaidi100_secret.strip()
        and s.kuaidi100_partner_id.strip()
        and s.kuaidi100_partner_key.strip()
        and s.kuaidi100_net_code.strip()
    )


def _sign(param_json: str, t: int) -> str:
    """快递100签名：MD5(param + t + key + secret)，32位大写。"""
    s = get_settings()
    raw = param_json + str(t) + s.kuaidi100_key.strip() + s.kuaidi100_secret.strip()
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()


def _request(method: str, param: dict) -> dict:
    """同步调用快递100接口。

    method 取值："order" 下单，"cancel" 取消。
    返回快递100响应 JSON；非 200 状态或业务 code != 200 抛 Kuaidi100Error。
    """
    s = get_settings()
    t = int(time.time())
    param_json = json.dumps(param, ensure_ascii=False, separators=(",", ":"))
    sign = _sign(param_json, t)
    payload = {
        "method": method,
        "key": s.kuaidi100_key.strip(),
        "sign": sign,
        "t": str(t),
        "param": param_json,
    }
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.post(ORDER_URL, data=payload)
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise Kuaidi100Error("快递100网络异常，请补查运单状态", "network", True) from exc

    if not isinstance(result, dict):
        raise Kuaidi100Error("快递100响应格式异常", "format", True)
    code = str(result.get("code", ""))
    if code and code != "200":
        message = result.get("message") or ERROR_MESSAGES.get(code, "快递100接口返回错误")
        uncertain = code in {"500", "501", "502"}
        raise Kuaidi100Error(message, code, uncertain)
    return result


def order_payload(db: Session, order, remote_order_id: str, package: dict) -> dict:
    """构造快递100下单请求参数（partnerId/partnerKey 从配置读取）。

    返回的 dict 会传给 _request("order", ...)。
    remote_order_id 用作 kuaidi100 的 orderId 字段，幂等性靠它保证。
    """
    s = get_settings()
    _r = wx_api._split_chinese_address(order.receiver_address.strip())
    receiver = {
        "name": order.receiver_name.strip(),
        "mobile": order.receiver_phone.strip(),
        "printAddr": "",
        "company": "",
    }
    sender = {
        "name": s.wechat_express_sender_name.strip() or "五色知时",
        "mobile": s.wechat_express_sender_phone.strip(),
        "printAddr": "",
        "company": "",
    }
    # 字段长度校验
    for person, label in ((sender, "发件"), (receiver, "收件")):
        if not person["name"] or not person["mobile"]:
            raise Kuaidi100Error(f"{label}人姓名或手机号为空")
        if not re.fullmatch(r"1[0-9]{10}", person["mobile"]):
            raise Kuaidi100Error(f"{label}手机号格式异常")

    # 商品明细
    items = []
    try:
        sku_list = json.loads(order.items_json)
        if not isinstance(sku_list, list) or not sku_list:
            raise ValueError()
        for item in sku_list:
            product = db.get(Product, item["product_id"])
            quantity = int(item["quantity"])
            if quantity < 1:
                raise ValueError()
            items.append({
                "name": str(item["name"])[:128],
                "number": quantity,
            })
    except (ValueError, TypeError, KeyError, AttributeError):
        raise Kuaidi100Error("订单商品明细不完整，无法生成运单") from None

    # 包裹重量尺寸
    try:
        weight = float(package["weight"])
        x, y, z = float(package["space_x"]), float(package["space_y"]), float(package["space_z"])
        if weight <= 0 or x <= 0 or y <= 0 or z <= 0:
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise Kuaidi100Error("包裹重量或尺寸无效") from None

    # 收件完整地址（快递100只有一个 address 字段）
    receiver["printAddr"] = f"{_r['province']}{_r['city']}{_r['area']}{_r['address']}"
    sender["printAddr"] = (
        f"{s.wechat_express_sender_province.strip()}"
        f"{s.wechat_express_sender_city.strip()}"
        f"{s.wechat_express_sender_district.strip()}"
        f"{s.wechat_express_sender_address.strip()}"
    )

    return {
        "partnerId": s.kuaidi100_partner_id.strip(),
        "partnerKey": s.kuaidi100_partner_key.strip(),
        "net": s.kuaidi100_net_code.strip(),
        "kuaidicom": ZTO_COM,
        "sendMan": sender,
        "recMan": receiver,
        "cargo": items,
        "weight": weight,
        "remark": f"订单: {order.number}",
        "orderId": remote_order_id,
        "thirdOrderNo": order.number,
        "dayType": "1",
        "orderType": "1",
    }


def create_waybill(db: Session, order, remote_order_id: str, package: dict) -> str:
    """调用快递100生成运单，返回运单号（kuaidhilNum）。"""
    param = order_payload(db, order, remote_order_id, package)
    result = _request("order", param)
    waybill = str(result.get("kuaidinum") or "").strip()
    if not waybill or not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", waybill):
        raise Kuaidi100Error("快递100返回的运单号异常，请补查", "empty_waybill", True)
    return waybill


def cancel_waybill(kuaidinum: str, order_id: str) -> None:
    """调用快递100取消运单。

    快递100取消接口不依赖 partnerId，只依赖运单号 + orderId。
    成功（code=200）直接返回；失败抛 Kuaidi100Error。
    """
    param = {
        "kuaidinum": kuaidinum,
        "orderId": order_id,
        "reason": "用户协商退款",
    }
    try:
        _request("cancel", param)
    except Kuaidi100Error as exc:
        # 取消是 "best effort"：若运单已揽收则取消必失败，但运单作废操作可由中通网点处理
        # 网络层失败（uncertain）告知调用方补查；业务失败（unshipped）按 cancelled 处理
        if exc.uncertain:
            raise
        # 业务失败：运单可能已被揽收或在途，不能撤销；返回未发货前可作废
        raise


def query_track(kuaidinum: str) -> list[dict]:
    """查询运单物流轨迹（订阅式接口）。

    快递100使用订阅推送方式：调用订阅接口后，物流状态变化会推送到回调URL。
    前端不需要主动查询，直接通过订阅获取更新。
    本方法暂未启用，物流轨迹仍由微信物流助手提供。
    """
    raise Kuaidi100Error("物流轨迹请使用微信物流助手查询", "not_implemented")


def integration_status(db: Session) -> dict:
    """返回快递100配置摘要（用于后台显示）。"""
    s = get_settings()
    return {
        "enabled": s.kuaidi100_enabled,
        "configured": configured(),
        "key_set": bool(s.kuaidi100_key.strip()),
        "partner_id_set": bool(s.kuaidi100_partner_id.strip()),
        "net_code_set": bool(s.kuaidi100_net_code.strip()),
        "carrier_code": ZTO_COM,
        "carrier_name": s.wechat_express_carrier_name.strip() or "中通快递",
    }