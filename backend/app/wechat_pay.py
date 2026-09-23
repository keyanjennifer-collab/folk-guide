"""微信支付 API v3 的最小服务端客户端。

只在后端读取商户私钥与 APIv3 密钥。小程序只接收调起支付所需的短期签名参数。
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import Settings, get_settings


class WechatPayError(RuntimeError):
    """可安全转换为网关错误的微信支付异常。"""


def _private_key(settings: Settings):
    try:
        content = Path(settings.wechat_pay_private_key_path).read_bytes()
        return serialization.load_pem_private_key(content, password=None)
    except Exception as exc:
        raise WechatPayError("微信支付商户私钥无法读取") from exc


def _public_key(settings: Settings):
    try:
        content = Path(settings.wechat_pay_public_key_path).read_bytes()
        return serialization.load_pem_public_key(content)
    except Exception as exc:
        raise WechatPayError("微信支付公钥无法读取") from exc


def _sign(message: str, settings: Settings) -> str:
    signature = _private_key(settings).sign(message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode("ascii")


def _request_path(url: str) -> str:
    parsed = urlsplit(url)
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


def _verify_signature(timestamp: str, nonce: str, signature_text: str, serial: str,
                      body_text: str, settings: Settings) -> None:
    if not timestamp or not nonce or not signature_text:
        raise WechatPayError("微信支付响应缺少签名头")
    if settings.wechat_pay_public_key_id and serial != settings.wechat_pay_public_key_id:
        raise WechatPayError("微信支付响应公钥编号不匹配")
    try:
        _public_key(settings).verify(
            base64.b64decode(signature_text),
            f"{timestamp}\n{nonce}\n{body_text}\n".encode("utf-8"),
            padding.PKCS1v15(), hashes.SHA256(),
        )
    except (InvalidSignature, ValueError) as exc:
        raise WechatPayError("微信支付响应验签失败") from exc


def _request(method: str, path: str, payload: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    """签名请求并验证微信响应签名，避免只依赖 HTTPS 判断响应可信。"""
    runtime = settings or get_settings()
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    url = runtime.wechat_pay_api_base_url.rstrip("/") + path
    message = f"{method.upper()}\n{_request_path(url)}\n{timestamp}\n{nonce}\n{body}\n"
    signature = _sign(message, runtime)
    authorization = (
        'WECHATPAY2-SHA256-RSA2048 '
        f'mchid="{runtime.wechat_pay_mch_id}",nonce_str="{nonce}",'
        f'signature="{signature}",timestamp="{timestamp}",serial_no="{runtime.wechat_pay_cert_serial}"'
    )
    try:
        response = httpx.request(
            method, url, content=body.encode("utf-8"),
            headers={"Authorization": authorization, "Accept": "application/json", "Content-Type": "application/json"},
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise WechatPayError("微信支付网关暂时无法连接") from exc
    _verify_signature(
        response.headers.get("Wechatpay-Timestamp", ""), response.headers.get("Wechatpay-Nonce", ""),
        response.headers.get("Wechatpay-Signature", ""), response.headers.get("Wechatpay-Serial", ""),
        response.text, runtime,
    )
    try:
        data = response.json() if response.content else {}
    except ValueError:
        data = {}
    if response.status_code < 200 or response.status_code >= 300:
        message = data.get("message") if isinstance(data, dict) else None
        raise WechatPayError(str(message or f"微信支付网关返回 {response.status_code}"))
    return data


def jsapi_payment_params(prepay_id: str) -> dict[str, Any]:
    """把服务端 prepay_id 转成 wx.requestPayment 所需参数。"""
    settings = get_settings()
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    package = f"prepay_id={prepay_id}"
    pay_sign = _sign(f"{settings.wechat_app_id}\n{timestamp}\n{nonce}\n{package}\n", settings)
    return {
        "mock": False, "prepay_id": prepay_id, "timeStamp": timestamp, "nonceStr": nonce,
        "package": package, "signType": "RSA", "paySign": pay_sign,
    }


def create_jsapi_payment(order_number: str, description: str, total_fen: int, openid: str,
                         expires_at: datetime | None = None) -> dict[str, Any]:
    settings = get_settings()
    if settings.wechat_pay_mode == "mock":
        return {"mock": True}
    if settings.wechat_pay_mode != "wechat":
        raise WechatPayError("微信支付尚未配置")
    payload: dict[str, Any] = {
        "appid": settings.wechat_app_id,
        "mchid": settings.wechat_pay_mch_id,
        "description": description[:127],
        "out_trade_no": order_number,
        "notify_url": settings.wechat_pay_notify_url,
        "amount": {"total": total_fen, "currency": "CNY"},
        "payer": {"openid": openid},
    }
    if expires_at is not None:
        aware = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at.astimezone(timezone.utc)
        payload["time_expire"] = aware.isoformat(timespec="seconds").replace("+00:00", "Z")
    data = _request("POST", "/v3/pay/transactions/jsapi", payload, settings)
    prepay_id = str(data.get("prepay_id") or "")
    if not prepay_id:
        raise WechatPayError("微信支付未返回预支付凭证")
    return jsapi_payment_params(prepay_id)


def close_payment(order_number: str) -> None:
    settings = get_settings()
    if settings.wechat_pay_mode == "mock":
        return
    if settings.wechat_pay_mode != "wechat":
        raise WechatPayError("微信支付尚未配置")
    _request("POST", f"/v3/pay/transactions/out-trade-no/{order_number}/close",
             {"mchid": settings.wechat_pay_mch_id}, settings)


def create_refund(order_number: str, refund_number: str, total_fen: int, reason: str) -> dict[str, Any]:
    settings = get_settings()
    if settings.wechat_pay_mode == "mock":
        return {"mock": True, "status": "SUCCESS"}
    if settings.wechat_pay_mode != "wechat":
        raise WechatPayError("微信退款尚未配置")
    return _request("POST", "/v3/refund/domestic/refunds", {
        "out_trade_no": order_number,
        "out_refund_no": refund_number,
        "reason": reason[:80],
        "notify_url": settings.wechat_pay_refund_notify_url,
        "amount": {"refund": total_fen, "total": total_fen, "currency": "CNY"},
    }, settings)


def verify_and_decrypt_notification(headers: dict[str, str], body: bytes) -> dict[str, Any]:
    """验签并解密支付/退款通知，返回完整事件及 resource_plaintext。"""
    settings = get_settings()
    timestamp = headers.get("wechatpay-timestamp", "")
    nonce = headers.get("wechatpay-nonce", "")
    signature_text = headers.get("wechatpay-signature", "")
    serial = headers.get("wechatpay-serial", "")
    if not timestamp or not nonce or not signature_text:
        raise WechatPayError("微信支付通知缺少签名头")
    if settings.wechat_pay_public_key_id and serial != settings.wechat_pay_public_key_id:
        raise WechatPayError("微信支付通知公钥编号不匹配")
    try:
        timestamp_value = int(timestamp)
        body_text = body.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise WechatPayError("微信支付通知时间或正文无效") from exc
    # 拒绝五分钟前的通知，再配合数据库 event_id 去重抵御重放。
    if abs(int(time.time()) - timestamp_value) > 300:
        raise WechatPayError("微信支付通知已过期")
    _verify_signature(timestamp, nonce, signature_text, serial, body_text, settings)
    try:
        event = json.loads(body)
        resource = event["resource"]
        key = settings.wechat_pay_api_v3_key.encode("utf-8")
        if len(key) != 32:
            raise ValueError("invalid api v3 key")
        plaintext = AESGCM(key).decrypt(
            str(resource["nonce"]).encode("utf-8"),
            base64.b64decode(resource["ciphertext"]),
            str(resource.get("associated_data") or "").encode("utf-8"),
        )
        event["resource_plaintext"] = json.loads(plaintext)
        return event
    except Exception as exc:
        raise WechatPayError("微信支付通知解密失败") from exc
