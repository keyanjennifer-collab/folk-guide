"""使用独立数据库核对开售、支付通知、库存和后台资金口径；不调用真实微信。"""

import base64
import csv
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.admin_auth import create_admin_user
from app.admin_models import AdminAuditLog
from app.commerce_models import Order, PaymentEvent, Product
from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.operations_routes import _beijing_today_range
from app.wechat_pay import WechatPayError


ADMIN = {"X-Admin-Key": "dev-admin-key", "X-Admin-Name": "sale-test"}


@pytest.fixture
def shop(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'shop.db').as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def isolated_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    try:
        with TestClient(app) as client:
            token = client.post("/api/auth/wechat", json={"code": "sale-operations"}).json()["access_token"]
            owner = {"Authorization": f"Bearer {token}"}
            address = client.post("/api/addresses", headers=owner, json={
                "recipient_name": "测试用户", "phone": "13800138000", "province": "浙江省",
                "city": "杭州市", "district": "西湖区", "detail": "测试路1号",
            })
            assert address.status_code == 201
            assert client.put("/api/admin/inventory/green", headers=ADMIN,
                              json={"available": 10, "active": True}).status_code == 200
            with sessions() as db:
                db.get(Product, "green").cost_fen = 2000
                db.commit()
            yield client, sessions, owner, address.json()["id"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def checkout(shop, quantity=2):
    client, _, owner, address_id = shop
    result = client.post("/api/orders", headers=owner, json={
        "items": [{"product_id": "green", "quantity": quantity}],
        "address_id": address_id, "idempotency_key": uuid4().hex,
    })
    assert result.status_code == 201, result.text
    return result.json()


def stock(client):
    return next(x for x in client.get("/api/admin/inventory", headers=ADMIN).json() if x["product_id"] == "green")


def money(client):
    result = client.get("/api/admin/finance", headers=ADMIN)
    assert result.status_code == 200, result.text
    return result.json()


def paid(shop, order):
    client, _, owner, _ = shop
    result = client.post(f"/api/orders/{order['id']}/mock-pay", headers=owner)
    assert result.status_code == 200 and result.json()["status"] == "paid"


@pytest.fixture
def signed_notify(tmp_path, monkeypatch):
    """生成临时平台密钥，走真实 RSA 验签和 AES-GCM 解密代码。"""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_path = tmp_path / "test-platform.pem"
    public_path.write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    settings = get_settings()
    monkeypatch.setattr(settings, "wechat_pay_public_key_path", str(public_path))
    monkeypatch.setattr(settings, "wechat_pay_public_key_id", "TEST-PLATFORM")
    monkeypatch.setattr(settings, "wechat_pay_api_v3_key", "t" * 32)

    def send(client, event_type, resource, event_id=None, tamper=False):
        resource_nonce = "testnonce123"
        ciphertext = AESGCM(b"t" * 32).encrypt(resource_nonce.encode(), json.dumps(resource).encode(), b"test")
        body = json.dumps({"id": event_id or uuid4().hex, "event_type": event_type, "resource": {
            "nonce": resource_nonce, "associated_data": "test", "ciphertext": base64.b64encode(ciphertext).decode(),
        }})
        timestamp, nonce = str(int(time.time())), "test-signature-nonce"
        signature = key.sign(f"{timestamp}\n{nonce}\n{body}\n".encode(), padding.PKCS1v15(), hashes.SHA256())
        return client.post("/api/payments/wechat/notify", content=(body + " " if tamper else body), headers={
            "Content-Type": "application/json", "Wechatpay-Timestamp": timestamp, "Wechatpay-Nonce": nonce,
            "Wechatpay-Serial": "TEST-PLATFORM", "Wechatpay-Signature": base64.b64encode(signature).decode(),
        })

    return send


def payment_resource(order, total=None):
    return {"out_trade_no": order["number"], "transaction_id": "WX-" + order["number"],
            "trade_state": "SUCCESS", "amount": {"total": total if total is not None else order["total_fen"]}}


def test_sale_catalog_and_contact_configuration(shop, monkeypatch):
    client, _, _, _ = shop
    catalog = client.get("/api/catalog").json()
    assert catalog["sale_enabled"] and catalog["sale_mode"] == "ready"
    assert catalog["shipping_eta"] == "付款后48小时内发货"
    settings = get_settings()
    contact = client.get("/api/after-sales/contact").json()
    assert contact["available"] is False and contact["corp_id"] == contact["url"] == ""
    monkeypatch.setattr(settings, "wecom_corp_id", "ww-test-corp")
    monkeypatch.setattr(settings, "wecom_customer_service_url", "https://work.weixin.qq.com/kfid/test-account")
    contact = client.get("/api/after-sales/contact").json()
    assert contact["available"] and contact["corp_id"] == "ww-test-corp"
    assert set(contact) == {"available", "corp_id", "url", "fallback_contact"}
    monkeypatch.setattr(settings, "wecom_customer_service_url", "https://work.weixin.qq.com.evil.test/kfid/a")
    assert client.get("/api/after-sales/contact").json()["available"] is False


def test_payment_refund_and_finance_are_consistent(shop):
    client, sessions, owner, _ = shop
    order = checkout(shop)
    assert order["total_fen"] == 14600
    assert order["items"][0]["sale_mode"] == "ready"
    assert "unit_cost_fen" not in order["items"][0]
    assert (stock(client)["available"], stock(client)["reserved"], stock(client)["sold"]) == (8, 2, 0)
    assert money(client)["gross_sales_fen"] == 0
    paid(shop, order)
    paid(shop, order)  # 重复支付请求不能重复记销量。
    assert (stock(client)["available"], stock(client)["reserved"], stock(client)["sold"]) == (8, 0, 2)
    with sessions() as db:
        db.get(Product, "green").cost_fen = 9999
        db.commit()
    finance = money(client)
    assert finance["gross_sales_fen"] == finance["net_sales_fen"] == 14600
    assert finance["total_cost_fen"] == 4000 and finance["gross_profit_fen"] == 10600
    assert finance["products"][0]["cost_fen"] == 4000
    assert client.delete("/api/account", headers=owner).status_code == 409
    assert money(client)["net_sales_fen"] == 14600
    result = client.post(f"/api/orders/{order['id']}/refund", headers=owner, json={"reason": "测试退款"})
    assert result.status_code == 200 and result.json()["status"] == "refunded"
    finance = money(client)
    assert finance["gross_sales_fen"] == finance["refund_fen"] == 14600
    assert finance["net_sales_fen"] == finance["gross_profit_fen"] == finance["total_cost_fen"] == 0
    assert stock(client)["available"] == 10 and stock(client)["sold"] == 0
    dashboard = client.get("/api/admin/dashboard", headers=ADMIN).json()
    assert dashboard["total_sales_fen"] == dashboard["today_sales_fen"] == 0


def test_signed_callbacks_are_verified_and_idempotent(shop, signed_notify, monkeypatch):
    client, sessions, owner, _ = shop
    order = checkout(shop)
    resource = payment_resource(order)
    assert signed_notify(client, "TRANSACTION.SUCCESS", resource, tamper=True).status_code == 400
    assert signed_notify(client, "TRANSACTION.SUCCESS", payment_resource(order, 1)).status_code == 400
    assert stock(client)["reserved"] == 2 and stock(client)["sold"] == 0
    for event_id in ["paid-once", "paid-once", "paid-second-event"]:
        assert signed_notify(client, "TRANSACTION.SUCCESS", resource, event_id).status_code == 200
    assert stock(client)["sold"] == 2 and money(client)["net_sales_fen"] == 14600
    monkeypatch.setattr("app.order_routes.create_refund", lambda *args: {"status": "PROCESSING"})
    refund = client.post(f"/api/orders/{order['id']}/refund", headers=owner, json={"reason": "测试异步退款"})
    assert refund.json()["status"] == "after_sale"
    assert money(client)["refund_fen"] == 0  # 发起退款不等于退款成功。
    with sessions() as db:
        refund_number = db.get(Order, order["id"]).refund_number
    resource = {"out_trade_no": order["number"], "out_refund_no": refund_number,
                "refund_status": "SUCCESS", "amount": {"total": 14600, "refund": 1}}
    assert signed_notify(client, "REFUND.SUCCESS", resource).status_code == 400
    resource["amount"]["refund"] = 14600
    for event_id in ["refunded-once", "refunded-once", "refunded-second-event"]:
        assert signed_notify(client, "REFUND.SUCCESS", resource, event_id).status_code == 200
    assert stock(client)["available"] == 10 and stock(client)["sold"] == 0
    assert money(client)["net_sales_fen"] == 0
    with sessions() as db:
        assert len(db.scalars(select(PaymentEvent)).all()) == 4


@pytest.mark.parametrize("complete", [False, True])
def test_shipped_refund_requires_return_inspection(shop, complete):
    client, sessions, owner, _ = shop
    order = checkout(shop)
    paid(shop, order)
    assert client.post(f"/api/admin/orders/{order['id']}/ship", headers=ADMIN,
                       json={"carrier": "顺丰速运", "tracking_number": "SF123456"}).status_code == 200
    update = client.put(f"/api/admin/orders/{order['id']}/logistics", headers=ADMIN,
                        json={"carrier": "顺丰速运", "tracking_number": "SF654321"})
    assert update.status_code == 200 and update.json()["tracking_number"] == "SF654321"
    if complete:
        assert client.post(f"/api/orders/{order['id']}/complete", headers=owner).status_code == 200
    refund = client.post(f"/api/admin/orders/{order['id']}/refund", headers=ADMIN, json={"reason": "客服同意退款"})
    assert refund.status_code == 200 and refund.json()["status"] == "refunded"
    assert stock(client)["available"] == 8 and stock(client)["sold"] == 0
    assert money(client)["net_sales_fen"] == 0 and money(client)["gross_profit_fen"] == -4000
    assert client.post(f"/api/admin/orders/{order['id']}/restock", headers=owner).status_code == 401
    result = client.post(f"/api/admin/orders/{order['id']}/restock", headers=ADMIN)
    assert result.status_code == 200
    assert stock(client)["available"] == 10 and stock(client)["sold"] == 0
    assert money(client)["gross_profit_fen"] == 0
    assert client.post(f"/api/admin/orders/{order['id']}/restock", headers=ADMIN).status_code == 409
    assert stock(client)["available"] == 10
    with sessions() as db:
        actions = set(db.scalars(select(AdminAuditLog.action)).all())
        assert {"order_refund", "order_return_restock", "order_logistics_update"}.issubset(actions)


def test_today_cash_uses_payment_and_refund_dates(shop):
    client, sessions, owner, _ = shop
    order = checkout(shop)
    paid(shop, order)
    start, _ = _beijing_today_range()
    with sessions() as db:
        saved = db.get(Order, order["id"])
        saved.created_at = start - timedelta(days=1)
        db.commit()
    dashboard = client.get("/api/admin/dashboard", headers=ADMIN).json()
    assert dashboard["today_order_count"] == 0 and dashboard["today_sales_fen"] == 14600
    with sessions() as db:
        db.get(Order, order["id"]).paid_at = start - timedelta(hours=1)
        db.commit()
    client.post(f"/api/orders/{order['id']}/refund", headers=owner, json={"reason": "隔日退款"})
    dashboard = client.get("/api/admin/dashboard", headers=ADMIN).json()
    assert dashboard["today_sales_fen"] == -14600 and dashboard["total_sales_fen"] == 0


def test_expiration_releases_inventory_and_late_payment_does_not_restock_twice(shop, signed_notify, monkeypatch):
    client, sessions, _, _ = shop
    order = checkout(shop)
    with sessions() as db:
        db.get(Order, order["id"]).expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    assert stock(client)["available"] == 10 and stock(client)["reserved"] == 0
    monkeypatch.setattr("app.order_routes.create_refund", lambda *args: {"status": "PROCESSING"})
    assert signed_notify(client, "TRANSACTION.SUCCESS", payment_resource(order)).status_code == 200
    assert stock(client)["available"] == 10 and money(client)["total_cost_fen"] == 0
    with sessions() as db:
        refund_number = db.get(Order, order["id"]).refund_number
    result = signed_notify(client, "REFUND.SUCCESS", {
        "out_trade_no": order["number"], "out_refund_no": refund_number, "refund_status": "SUCCESS",
        "amount": {"total": 14600, "refund": 14600},
    })
    assert result.status_code == 200
    assert stock(client)["available"] == 10 and stock(client)["sold"] == 0
    assert money(client)["net_sales_fen"] == 0


def test_failed_refund_keeps_stock_and_sales(shop, monkeypatch):
    client, _, _, _ = shop
    order = checkout(shop)
    paid(shop, order)

    def failed_gateway(*args):
        raise WechatPayError("测试网关超时")

    monkeypatch.setattr("app.operations_routes.create_refund", failed_gateway)
    result = client.post(f"/api/admin/orders/{order['id']}/refund", headers=ADMIN, json={"reason": "测试退款"})
    assert result.status_code == 502
    assert stock(client)["available"] == 8 and stock(client)["sold"] == 2
    assert money(client)["net_sales_fen"] == 14600


def test_operator_cannot_refund_or_restock(shop):
    client, sessions, _, _ = shop
    order = checkout(shop)
    paid(shop, order)
    with sessions() as db:
        create_admin_user(db, username="sale-operator", password="Safe-Password-2026", display_name="测试运营", role="operator")
    login = client.post("/api/admin/auth/login", json={"username": "sale-operator", "password": "Safe-Password-2026"})
    headers = {"X-CSRF-Token": login.json()["csrf_token"]}
    assert client.post(f"/api/admin/orders/{order['id']}/refund", headers=headers, json={"reason": "无权限退款"}).status_code == 403
    assert client.post(f"/api/admin/orders/{order['id']}/restock", headers=headers).status_code == 403


def test_cost_estimate_warning_for_legacy_orders(shop):
    client, sessions, _, _ = shop
    order = checkout(shop)
    paid(shop, order)
    with sessions() as db:
        saved = db.get(Order, order["id"])
        items = json.loads(saved.items_json)
        items[0].pop("unit_cost_fen")
        saved.items_json = json.dumps(items)
        db.get(Product, "green").cost_fen = 0
        db.commit()
    warning = money(client)["cost_warning"]
    assert "成本为0" in warning and "历史订单" in warning


def test_last_item_cannot_be_reserved_twice(shop):
    client, _, owner, address_id = shop
    client.put("/api/admin/inventory/green", headers=ADMIN, json={"available": 1, "active": True})

    def buy(_):
        return client.post("/api/orders", headers=owner, json={
            "items": [{"product_id": "green", "quantity": 1}],
            "address_id": address_id, "idempotency_key": uuid4().hex,
        }).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(buy, range(2))) == [201, 409]
    assert (stock(client)["available"], stock(client)["reserved"], stock(client)["sold"]) == (0, 1, 0)


def test_failed_multi_product_checkout_rolls_back_all_reservations(shop):
    client, sessions, owner, address_id = shop
    client.put("/api/admin/inventory/gold", headers=ADMIN, json={"available": 2, "active": True})
    response = client.post("/api/orders", headers=owner, json={
        "items": [{"product_id": "gold", "quantity": 1}, {"product_id": "green", "quantity": 11}],
        "address_id": address_id, "idempotency_key": uuid4().hex,
    })
    assert response.status_code == 409
    rows = {x["product_id"]: x for x in client.get("/api/admin/inventory", headers=ADMIN).json()}
    assert rows["gold"]["available"] == 2 and rows["gold"]["reserved"] == 0
    assert rows["green"]["available"] == 10 and rows["green"]["reserved"] == 0
    with sessions() as db:
        assert db.scalar(select(Order.id)) is None


def test_delayed_payment_notification_keeps_wechat_success_date(shop, signed_notify):
    client, sessions, _, _ = shop
    order = checkout(shop)
    resource = payment_resource(order)
    resource["success_time"] = "2026-10-11T23:59:59+08:00"
    assert signed_notify(client, "TRANSACTION.SUCCESS", resource).status_code == 200
    with sessions() as db:
        assert db.get(Order, order["id"]).paid_at == datetime(2026, 10, 11, 15, 59, 59)


def test_admin_date_filter_and_csv_use_beijing_time(shop):
    client, sessions, _, _ = shop
    first, second = checkout(shop, 1), checkout(shop, 1)
    with sessions() as db:
        db.get(Order, first["id"]).created_at = datetime(2026, 10, 11, 16, 0, 0)
        db.get(Order, second["id"]).created_at = datetime(2026, 10, 12, 16, 0, 0)
        db.commit()
    query = {"date_from": "2026-10-12", "date_to": "2026-10-12"}
    result = client.get("/api/admin/orders", params=query, headers=ADMIN)
    assert [x["id"] for x in result.json()] == [first["id"]]
    exported = client.get("/api/admin/orders/export.csv", params=query, headers=ADMIN)
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert len(rows) == 1 and rows[0]["下单时间"] == "2026-10-12 00:00"
    assert rows[0]["成本"] == rows[0]["毛利"] == "0.00"  # 未支付订单不产生利润。
