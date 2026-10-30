"""用临时商户/平台密钥验证查单的真实签名，不访问微信网络。"""

import base64
import json
import re
import time

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.config import Settings
from app import wechat_pay


@pytest.fixture
def payment_keys(tmp_path, monkeypatch):
    merchant = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    platform = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path, public_path = tmp_path / "merchant.pem", tmp_path / "platform.pem"
    private_path.write_bytes(merchant.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public_path.write_bytes(platform.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    settings = Settings(_env_file=None, wechat_pay_mode="wechat", wechat_pay_mch_id="test-merchant",
                        wechat_pay_cert_serial="test-merchant-serial", wechat_pay_public_key_id="test-platform",
                        wechat_pay_private_key_path=str(private_path), wechat_pay_public_key_path=str(public_path))
    monkeypatch.setattr(wechat_pay, "get_settings", lambda: settings)
    return merchant, platform, settings


def response_signed_by(platform, tamper=None):
    body = json.dumps({"trade_state": "SUCCESS", "out_trade_no": "WS1"})
    timestamp, nonce = str(int(time.time())), "response-nonce"
    signature = platform.sign(f"{timestamp}\n{nonce}\n{body}\n".encode(), padding.PKCS1v15(), hashes.SHA256())
    if tamper == "body":
        body += " "
    if tamper == "signature":
        signature = bytes(len(signature))
    return httpx.Response(200, content=body.encode(), headers={
        "Wechatpay-Timestamp": timestamp, "Wechatpay-Nonce": nonce,
        "Wechatpay-Signature": base64.b64encode(signature).decode(),
        "Wechatpay-Serial": "other-key" if tamper == "serial" else "test-platform",
    })


def test_query_signs_exact_get_path_query_and_empty_body(payment_keys, monkeypatch):
    merchant, platform, _ = payment_keys
    calls = []

    def request(method, url, **options):
        calls.append(url)
        assert method == "GET" and options["content"] == b"" and options["timeout"] == 3.0
        assert url.endswith("/out-trade-no/WS%20%2F%3F?mchid=test-merchant")
        values = dict(re.findall(r'(\w+)="([^"]*)"', options["headers"]["Authorization"]))
        message = f"GET\n/v3/pay/transactions/out-trade-no/WS%20%2F%3F?mchid=test-merchant\n{values['timestamp']}\n{values['nonce_str']}\n\n"
        merchant.public_key().verify(base64.b64decode(values["signature"]), message.encode(),
                                     padding.PKCS1v15(), hashes.SHA256())
        return response_signed_by(platform)

    monkeypatch.setattr(wechat_pay.httpx, "request", request)
    assert wechat_pay.query_payment("WS /?")["trade_state"] == "SUCCESS"
    assert len(calls) == 1


@pytest.mark.parametrize("tamper", ["body", "signature", "serial"])
def test_query_never_accepts_unverified_wechat_results(payment_keys, monkeypatch, tamper):
    _, platform, _ = payment_keys
    monkeypatch.setattr(wechat_pay.httpx, "request", lambda *args, **kw: response_signed_by(platform, tamper))
    with pytest.raises(wechat_pay.WechatPayError, match="验签|公钥编号"):
        wechat_pay.query_payment("WS1")


def test_query_timeout_is_a_safe_gateway_error(payment_keys, monkeypatch):
    def timeout(*args, **kw):
        raise httpx.ReadTimeout("test timeout")

    monkeypatch.setattr(wechat_pay.httpx, "request", timeout)
    with pytest.raises(wechat_pay.WechatPayError, match="暂时无法连接"):
        wechat_pay.query_payment("WS1")
