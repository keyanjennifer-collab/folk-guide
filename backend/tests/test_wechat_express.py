"""微信物流闭环及故障恢复；所有HTTP均模拟，不调用真实微信。"""

import base64
import json
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app import wechat_express as api
from app import wechat_express_service as service
from app.admin_auth import create_admin_user
from app.admin_models import AdminAuditLog
from app.commerce_models import Order, WechatAccessToken, WechatExpressOrder
from app.config import Settings, get_settings, validate_runtime_settings
from test_logistics import snapshot
from test_sale_operations import ADMIN, checkout, paid, shop


PACKAGE = {"weight": 1.2, "space_x": 20, "space_y": 15, "space_z": 10}


@pytest.fixture
def enabled(shop, monkeypatch):
    settings = get_settings()
    for name, value in {"wechat_app_id": "review-test-app", "wechat_app_secret": "review-test-secret",
        "wechat_express_enabled": True, "wechat_express_delivery_id": "ZTO", "wechat_express_carrier_name": "中通快递",
        "wechat_express_sender_name": "测试寄件人", "wechat_express_sender_phone": "13900139000",
        "wechat_express_sender_province": "浙江省", "wechat_express_sender_city": "杭州市",
        "wechat_express_sender_district": "西湖区", "wechat_express_sender_address": "测试寄件地址1号",
        "wechat_express_asset_origin": "https://api.example.test"}.items():
        monkeypatch.setattr(settings, name, value)


def provider(monkeypatch, custom=None):
    calls = []

    def handle(transport, request):
        data = json.loads(request.content) if request.content else {}
        calls.append((request.method, request.url.path, data))
        if custom:
            result = custom(request, data)
            if result is not None:
                return httpx.Response(200, json=result, request=request)
        path = request.url.path
        if path.endswith("stable_token"):
            result = {"access_token": "fake-wechat-access", "expires_in": 7200}
        elif path == api.ACCOUNT_GETALL_PATH:
            assert request.method == "GET" and not request.content
            result = {"list": [{"delivery_id": "ZTO", "biz_id": "fake-biz-id", "status_code": 0,
                "quota_num": 10, "service_type": [{"service_type": 0, "service_name": "标准快递"}]}]}
        elif path == api.ORDER_ADD_PATH:
            result = {"order_id": data["order_id"], "waybill_id": "73123456789012"}
        elif path == api.ORDER_GET_PATH:
            result = {**data, "order_status": 0,
                "print_html": base64.b64encode(b'<html><body>official waybill<script>opener.test()</script></body></html>').decode()}
        elif path == api.ORDER_BATCHGET_PATH:
            result = {"order_list": [{**data["order_list"][0], "errcode": 0, "order_status": 0, "waybill_id": "73123456789012"}]}
        elif path == api.PATH_GET_PATH:
            result = {"path_item_list": [{"action_time": 1793246400, "action_type": 100001, "action_msg": "中通已揽件"}]}
        else:
            assert path in {api.ORDER_CANCEL_PATH, api.PRINTER_UPDATE_PATH}
            result = {"errcode": 0}
        return httpx.Response(200, json=result, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    return calls


def create(shop):
    order = checkout(shop)
    paid(shop, order)
    response = shop[0].post(f"/api/admin/orders/{order['id']}/shipping-sync/create", headers=ADMIN, json=PACKAGE)
    assert response.status_code == 200, response.text
    return order


def record(sessions, order):
    with sessions() as db:
        row = db.get(WechatExpressOrder, order["id"])
        db.expunge(row)
        return row


def action(shop, order, name):
    return shop[0].post(f"/api/admin/orders/{order['id']}/shipping-sync/{name}", headers=ADMIN)


def test_paid_does_not_create_until_admin_requests(shop, enabled, monkeypatch):
    calls = provider(monkeypatch)
    order = checkout(shop)
    assert action(shop, order, "create").status_code == 409
    paid(shop, order)
    service.run_batch(shop[1])
    assert calls == []
    assert shop[0].post(f"/api/admin/orders/{order['id']}/shipping-sync/create", headers=ADMIN).status_code == 422
    assert shop[0].post(f"/api/admin/orders/{order['id']}/shipping-sync/create", headers=ADMIN, json={**PACKAGE, "weight": 0}).status_code == 422


def test_generate_print_then_confirm_ship_and_buyer_query(shop, enabled, monkeypatch):
    client, sessions, owner, _ = shop
    calls = provider(monkeypatch)
    order = create(shop)
    before = snapshot(sessions)
    service.run_batch(sessions)
    row = record(sessions, order)
    assert row.remote_order_id == order["number"] and row.attempts == 1 and row.status == "ordered"
    assert snapshot(sessions)[1] == before[1]
    buyer = client.get(f"/api/orders/{order['id']}", headers=owner).json()
    assert buyer["status"] == "paid" and buyer["shipped_at"] is None and buyer["tracking_number"] == row.waybill_id
    data = next(c[2] for c in calls if c[1] == api.ORDER_ADD_PATH)
    assert data["order_id"] == row.remote_order_id and data["service"]["service_type"] == 0
    assert data["cargo"]["weight"] == 1.2 and data["cargo"]["count"] == 1
    assert data["receiver"]["address"] == order["receiver_address"]
    assert data["shop"]["detail_list"][0]["goods_img_url"] == "https://api.example.test/product-assets/green.jpg"
    assert client.get(f"/api/admin/orders/{order['id']}/waybill").status_code == 401
    printed = client.get(f"/api/admin/orders/{order['id']}/waybill", headers=ADMIN)
    assert printed.status_code == 200 and "official waybill" in printed.text
    assert "sandbox allow-modals" in printed.headers["content-security-policy"] and "script-src" not in printed.headers["content-security-policy"]
    assert printed.headers["cache-control"] == "private, no-store"
    assert client.post(f"/api/admin/orders/{order['id']}/ship", headers=ADMIN, json={"carrier": "中通快递", "tracking_number": "different123"}).status_code == 409
    shipment = client.post(f"/api/admin/orders/{order['id']}/ship", headers=ADMIN, json={"carrier": "中通快递", "tracking_number": row.waybill_id})
    assert shipment.status_code == 200 and shipment.json()["status"] == "shipped"
    tracking = client.get(f"/api/orders/{order['id']}/logistics", headers=owner)
    assert tracking.status_code == 200 and tracking.json()["tracking_events"][0]["title"] == "已揽件"
    before_calls = len(calls)
    client.get(f"/api/orders/{order['id']}/logistics", headers=owner)
    assert len(calls) == before_calls


@pytest.mark.parametrize("state", ["ordered", "failed", "cancelled", "conflict"])
def test_terminal_jobs_never_claimed_or_recreated(shop, enabled, monkeypatch, state):
    order = create(shop)
    with shop[1]() as db:
        row = db.get(WechatExpressOrder, order["id"])
        row.status, row.next_action = state, "none"
        row.next_attempt_at = datetime.utcnow() - timedelta(days=1)
        db.commit()
    calls = provider(monkeypatch)
    service.run_batch(shop[1])
    assert calls == [] and record(shop[1], order).status == state


def test_timeout_uses_saved_remote_number_and_only_verifies(shop, enabled, monkeypatch):
    order = create(shop)
    def timeout(request, data):
        if request.url.path == api.ORDER_ADD_PATH:
            with shop[1]() as db:
                row = db.get(WechatExpressOrder, order["id"])
                assert row.remote_order_id == data["order_id"] and row.attempts == 1
            raise httpx.ReadTimeout("private-secret")
    calls = provider(monkeypatch, timeout)
    service.run_batch(shop[1])
    assert record(shop[1], order).status == "unknown"
    assert "private-secret" not in record(shop[1], order).message
    assert shop[0].post(f"/api/admin/orders/{order['id']}/shipping-sync/retry", headers=ADMIN, json=PACKAGE).status_code == 409
    assert action(shop, order, "verify").status_code == 200
    service.run_batch(shop[1])
    assert record(shop[1], order).status == "ordered"
    assert sum(path == api.ORDER_ADD_PATH for _, path, _ in calls) == 1
    assert next(data for _, path, data in calls if path == api.ORDER_BATCHGET_PATH)["order_list"][0]["order_id"] == order["number"]


def test_crashed_create_is_verified_without_new_waybill(shop, enabled, monkeypatch):
    order = create(shop)
    with shop[1]() as db:
        first = service._claim(db)
    calls = provider(monkeypatch)
    service.run_batch(shop[1])
    assert calls == []
    with shop[1]() as db:
        row = db.get(WechatExpressOrder, order["id"])
        row.lease_until = row.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    service.run_batch(shop[1])
    assert record(shop[1], order).status == "ordered"
    assert all(path != api.ORDER_ADD_PATH for _, path, _ in calls)
    service._execute(shop[1], first)
    assert all(path != api.ORDER_ADD_PATH for _, path, _ in calls)


def test_cancel_before_execution_and_regenerate_with_new_id(shop, enabled, monkeypatch):
    order = create(shop)
    calls = provider(monkeypatch)
    assert action(shop, order, "cancel").status_code == 200
    service.run_batch(shop[1])
    assert calls == [] and record(shop[1], order).status == "cancelled"
    assert shop[0].post(f"/api/admin/orders/{order['id']}/shipping-sync/create", headers=ADMIN, json=PACKAGE).status_code == 200
    service.run_batch(shop[1])
    assert record(shop[1], order).remote_order_id == order["number"] + "_R2"


def test_refund_after_waybill_waits_for_confirmed_cancellation(shop, enabled, monkeypatch):
    client, sessions, owner, _ = shop
    order = create(shop)
    calls = provider(monkeypatch)
    service.run_batch(sessions)
    refund_url = f"/api/orders/{order['id']}/refund"
    assert client.post(refund_url, headers=owner, json={"reason": "不要了"}).status_code == 409
    assert client.get(f"/api/admin/orders/{order['id']}/waybill", headers=ADMIN).status_code == 409
    service.run_batch(sessions)
    assert record(sessions, order).status == "cancelled"
    assert any(path == api.ORDER_CANCEL_PATH for _, path, _ in calls)
    assert client.post(refund_url, headers=owner, json={"reason": "不要了"}).status_code == 200
    before = len(calls)
    service.run_batch(sessions)
    assert len(calls) == before


def test_refund_during_request_cancels_late_created_waybill(shop, enabled, monkeypatch):
    client, sessions, owner, _ = shop
    order = create(shop)
    def refund(request, data):
        if request.url.path == api.ORDER_ADD_PATH:
            result = client.post(f"/api/orders/{order['id']}/refund", headers=owner, json={"reason": "不要了"})
            assert result.status_code == 409
    calls = provider(monkeypatch, refund)
    service.run_batch(sessions)
    assert record(sessions, order).status == "cancelled"
    assert sum(path == api.ORDER_ADD_PATH for _, path, _ in calls) == 1
    assert sum(path == api.ORDER_CANCEL_PATH for _, path, _ in calls) == 1
    assert client.get(f"/api/orders/{order['id']}", headers=owner).json()["status"] == "paid"


def test_unconfirmed_cancel_cannot_unlock_refund(shop, enabled, monkeypatch):
    client, sessions, owner, _ = shop
    order = create(shop)
    provider(monkeypatch)
    service.run_batch(sessions)
    provider(monkeypatch, lambda req, _: {} if req.url.path == api.ORDER_CANCEL_PATH else None)
    assert client.post(f"/api/orders/{order['id']}/refund", headers=owner, json={"reason": "不要了"}).status_code == 409
    service.run_batch(sessions)
    assert record(sessions, order).status == "unknown"
    assert client.post(f"/api/orders/{order['id']}/refund", headers=owner, json={"reason": "不要了"}).status_code == 409


def test_print_type_and_manual_change_cannot_print_old_label(shop, enabled, monkeypatch):
    client, sessions, _, _ = shop
    order = create(shop)
    calls = provider(monkeypatch)
    service.run_batch(sessions)
    monkeypatch.setattr(get_settings(), "wechat_express_print_type", 1)
    assert client.get(f"/api/admin/orders/{order['id']}/waybill", headers=ADMIN).status_code == 200
    assert next(data for _, path, data in calls if path == api.ORDER_GET_PATH)["print_type"] == 1
    with sessions() as db:
        db.get(Order, order["id"]).tracking_number = "replaced123456"
        db.commit()
    assert client.get(f"/api/admin/orders/{order['id']}/waybill", headers=ADMIN).status_code == 409


def test_failed_query_or_cancelled_waybill_cannot_trigger_reorder(shop, enabled, monkeypatch):
    order = create(shop)
    def uncertain(request, data):
        if request.url.path == api.ORDER_ADD_PATH:
            return {"errcode": -1}
        if request.url.path == api.ORDER_BATCHGET_PATH:
            return {"order_list": [{"errcode": 9300506, "order_id": order["number"], "delivery_id": "ZTO"}]}
    calls = provider(monkeypatch, uncertain)
    service.run_batch(shop[1])
    assert record(shop[1], order).status == "unknown"
    action(shop, order, "cancel")
    service.run_batch(shop[1])
    assert record(shop[1], order).status == "unknown"
    assert sum(path == api.ORDER_ADD_PATH for _, path, _ in calls) == 1
    provider(monkeypatch, lambda request, data: {"order_list": [{"errcode": 0, "order_id": order["number"],
        "delivery_id": "ZTO", "waybill_id": "73123456789012", "order_status": 1}]} if request.url.path == api.ORDER_BATCHGET_PATH else None)
    action(shop, order, "verify")
    service.run_batch(shop[1])
    assert record(shop[1], order).status == "cancelled"
    with shop[1]() as db:
        assert db.get(Order, order["id"]).tracking_number is None


def test_token_expired_really_refreshes_and_binding_uses_get(shop, enabled, monkeypatch):
    with shop[1]() as db:
        db.add(WechatAccessToken(id=1, access_token="stale", expires_at=datetime.utcnow() + timedelta(hours=1)))
        db.commit()
    def stale(request, data):
        if request.url.params.get("access_token") == "stale":
            return {"errcode": 40001}
    calls = provider(monkeypatch, stale)
    with shop[1]() as db:
        assert api.delivery_bindings(db)[0]["biz_id"] == "fake-biz-id"
    assert [path for _, path, _ in calls] == [api.ACCOUNT_GETALL_PATH, "/cgi-bin/stable_token", api.ACCOUNT_GETALL_PATH]


def test_permissions_session_csrf_and_no_configuration_leak(shop, enabled, monkeypatch):
    client, sessions, owner, _ = shop
    calls = provider(monkeypatch)
    order = checkout(shop)
    paid(shop, order)
    url = f"/api/admin/orders/{order['id']}/shipping-sync/create"
    assert client.post(url, headers=owner, json=PACKAGE).status_code == 401
    with sessions() as db:
        create_admin_user(db, username="express-test", password="Safe-Password-2026", display_name="发货员", role="operator")
    login = client.post("/api/admin/auth/login", json={"username": "express-test", "password": "Safe-Password-2026"})
    assert client.post(url, json=PACKAGE).status_code == 403
    assert client.post(url, headers={"X-CSRF-Token": login.json()["csrf_token"]}, json=PACKAGE).status_code == 200
    status = client.get("/api/admin/wechat-express")
    assert status.status_code == 200 and "review-test-secret" not in status.text and "fake-wechat-access" not in status.text
    assert client.post("/api/admin/wechat-express/printer", headers={"X-CSRF-Token": login.json()["csrf_token"]},
        json={"openid": "operator-openid", "update_type": "bind"}).status_code == 403


def test_rejected_parameters_do_not_generate_waybill_or_retry_automatically(shop, enabled, monkeypatch):
    order = create(shop)
    monkeypatch.setattr(get_settings(), "wechat_express_asset_origin", "")
    calls = provider(monkeypatch)
    service.run_batch(shop[1])
    assert record(shop[1], order).status == "failed"
    service.run_batch(shop[1])
    assert all(path != api.ORDER_ADD_PATH for _, path, _ in calls)


def test_production_configuration_checks_image_origin_and_service_type():
    values = dict(_env_file=None, environment="production", auto_create_schema=False, testing=False,
        database_url="postgresql+psycopg://u:p@db/test", jwt_secret="x" * 32, admin_api_key="x" * 24,
        wechat_app_id="test", wechat_app_secret="test", cors_origins="https://example.test", commerce_enabled=False,
        wechat_express_enabled=True, wechat_express_sender_name="测试", wechat_express_sender_phone="13900000000",
        wechat_express_sender_province="浙江省", wechat_express_sender_city="杭州市", wechat_express_sender_address="测试地址",
        wechat_express_asset_origin="https://api.example.test")
    validate_runtime_settings(Settings(**values))
    with pytest.raises(RuntimeError, match="ASSET_ORIGIN"):
        validate_runtime_settings(Settings(**{**values, "wechat_express_asset_origin": "http://api.example.test/path"}))
    with pytest.raises(RuntimeError, match="同时填写"):
        validate_runtime_settings(Settings(**{**values, "wechat_express_service_type": "0"}))
