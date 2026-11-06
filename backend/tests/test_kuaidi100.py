"""快递管家真实协议的模拟联调；所有请求拦截，不使用真实账号下单。"""

import json
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import func, select

from app import kuaidi100_client as kd
from app import wechat_express_service as service
from app.admin_models import AdminAuditLog
from app.commerce_models import Kuaidi100Authorization, WechatExpressOrder
from app.config import Settings, get_settings
from test_sale_operations import ADMIN, checkout, paid, shop
from test_wechat_express import PACKAGE, action, create, record


@pytest.fixture
def guanjia(shop, monkeypatch):
    for name, value in {
        "kuaidi100_enabled": True, "kuaidi100_key": "guanjia-app-key", "kuaidi100_secret": "guanjia-app-secret",
        "kuaidi100_access_token": "guanjia-access-token", "kuaidi100_refresh_token": "",
        "kuaidi100_callback_url": "https://api.example.test/api/kuaidi100/callback",
        "wechat_express_enabled": False, "wechat_express_sender_name": "测试寄件人",
        "wechat_express_sender_phone": "13900139000", "wechat_express_sender_province": "浙江省",
        "wechat_express_sender_city": "杭州市", "wechat_express_sender_district": "西湖区",
        "wechat_express_sender_address": "寄件路1号",
    }.items():
        monkeypatch.setattr(get_settings(), name, value)


def provider(monkeypatch, custom=None):
    calls = []

    def handle(transport, request):
        assert request.url.host == "b.kuaidi100.com"
        fields = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        assert fields["sign"] == kd._sign(fields)
        calls.append((request.url.path, fields))
        result = custom(request, fields) if custom else None
        return httpx.Response(200, json=result if result is not None else {"status": "200", "message": "success"}, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    return calls


def callback(client, remote, kind="FILLEXPNUM", data=None, *, string_data=False, **changes):
    if data is None:
        data = [{"order_number": remote, "company_code": "zhongtong", "kuadicom_name": "中通快递", "kuaidi_num": "73123456789012"}]
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    body = {"app_key": get_settings().kuaidi100_key, "timestamp": int(time.time()), "type": kind, "data": text}
    body["sign"] = kd._sign(body)
    if not string_data:
        body["data"] = data
    body.update(changes)
    return client.post("/api/kuaidi100/callback", json=body)


def test_signature_matches_official_signature_example(monkeypatch):
    monkeypatch.setattr(get_settings(), "kuaidi100_secret", "testSecret")
    assert kd._sign({"app_id": "LeWFeuaGwx1v", "response_type": "code",
        "redirect_uri": "http://b.kuaidi100.com/open/test/sent.do", "state": "test123",
        "timestamp": "1533089506853"}) == "F85E088FDC92BEDDA875146CCF03D226"


def test_existing_and_guanjia_config_names_are_accepted(monkeypatch):
    for name in ("KUAIDI100_ENABLED", "KUAIDI100_KEY", "KUAIDI100_SECRET", "KUAIDI100_ACCESS_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    for key, secret in (("KUAIDI100_KEY", "KUAIDI100_SECRET"), ("KUAIDI100_APP_KEY", "KUAIDI100_APP_SECRET"),
                        ("KUAIDIGUANJIA_APP_KEY", "KUAIDIGUANJIA_APP_SECRET")):
        settings = Settings(_env_file=None, **{key: "app-key", secret: "app-secret"})
        assert settings.kuaidi100_key == "app-key" and settings.kuaidi100_secret == "app-secret"


def test_import_waits_for_printed_waybill_and_uses_only_guanjia_protocol(shop, guanjia, monkeypatch):
    calls = provider(monkeypatch)
    order = create(shop)
    service.run_batch(shop[1])
    row = record(shop[1], order)
    assert row.provider == kd.PROVIDER and row.status == "waiting" and not row.waybill_id
    assert shop[0].get(f"/api/orders/{order['id']}", headers=shop[2]).json()["tracking_number"] is None
    assert len(calls) == 1 and calls[0][0] == kd.IMPORT_PATH
    fields = calls[0][1]
    assert len(fields["timestamp"]) == 10 and "method" not in fields and "param" not in fields
    data = json.loads(fields["data"])
    assert data["order_number"] == order["number"]
    assert data["cargo_count"] == 2 and data["package_count"] == 1
    assert data["weight"] == 1.2 and data["volume"] == "3000.0"
    assert data["receiver"]["addr"] == order["receiver_address"]
    assert not any(k in data for k in ("partnerId", "partnerKey", "tempId"))
    printed = shop[0].get(f"/api/admin/orders/{order['id']}/waybill", headers=ADMIN, follow_redirects=False)
    assert printed.status_code == 303 and printed.headers["location"] == "https://b.kuaidi100.com/page/doPrint/PRINTWAIT"
    assert action(shop, order, "cancel").status_code == 410
    assert len(calls) == 1


@pytest.mark.parametrize("string_data", [False, True])
def test_signed_callbacks_are_idempotent_and_do_not_auto_ship(shop, guanjia, monkeypatch, string_data):
    provider(monkeypatch)
    order = create(shop)
    service.run_batch(shop[1])
    client, sessions, owner, _ = shop
    assert callback(client, order["number"], kind="SEND", data={"order_number": order["number"], "status": "200"}, string_data=string_data).json() == {"status": "200"}
    assert callback(client, order["number"], string_data=string_data).json() == {"status": "200"}
    assert record(sessions, order).status == "ordered"
    with sessions() as db:
        audits = db.scalar(select(func.count()).select_from(AdminAuditLog).where(AdminAuditLog.action == "kuaidi100_waybill_received"))
    assert callback(client, order["number"], string_data=string_data).json() == {"status": "200"}
    buyer = client.get(f"/api/orders/{order['id']}", headers=owner).json()
    assert buyer["status"] == "paid" and not buyer["shipped_at"] and buyer["tracking_number"] == "73123456789012"
    shipped = client.post(f"/api/admin/orders/{order['id']}/ship", headers=ADMIN,
                          json={"carrier": "中通快递", "tracking_number": buyer["tracking_number"]})
    assert shipped.status_code == 200 and shipped.json()["status"] == "shipped"
    callback(client, order["number"])
    assert record(sessions, order).status == "ordered"
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(AdminAuditLog).where(AdminAuditLog.action == "kuaidi100_waybill_received")) == audits == 1


@pytest.mark.parametrize("changes", [{"sign": ""}, {"sign": "A" * 32}, {"app_key": "other-app"}, {"timestamp": 0}])
def test_invalid_callback_never_changes_orders(shop, guanjia, changes):
    order = create(shop)
    assert callback(shop[0], order["number"], **changes).json() == {"status": "400"}
    assert record(shop[1], order).status == "queued"
    assert not record(shop[1], order).waybill_id


def test_timeout_and_restart_only_query_without_resubmitting(shop, guanjia, monkeypatch):
    order = create(shop)
    def timeout(request, fields):
        if request.url.path == kd.IMPORT_PATH:
            raise httpx.ReadTimeout("private-token")
        return {"status": "200", "order_number": order["number"], "kuaidi_com": "zhongtong", "kuaidi_num": "73123456789012"}
    calls = provider(monkeypatch, timeout)
    service.run_batch(shop[1])
    assert record(shop[1], order).status == "unknown"
    assert "private-token" not in record(shop[1], order).message
    assert shop[0].post(f"/api/admin/orders/{order['id']}/shipping-sync/retry", headers=ADMIN, json=PACKAGE).status_code == 409
    assert action(shop, order, "verify").status_code == 200
    service.run_batch(shop[1])
    assert record(shop[1], order).status == "ordered"
    assert [path for path, _ in calls] == [kd.IMPORT_PATH, kd.QUERY_PATH]


def test_crashed_import_never_reimports_or_accepts_missing_number(shop, guanjia, monkeypatch):
    order = create(shop)
    with shop[1]() as db:
        job = service._claim(db)
    calls = provider(monkeypatch)
    with shop[1]() as db:
        row = db.get(WechatExpressOrder, order["id"])
        row.lease_until = row.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    service.run_batch(shop[1])
    assert record(shop[1], order).status == "unknown" and not record(shop[1], order).waybill_id
    service._execute(shop[1], job)
    assert [path for path, _ in calls] == [kd.QUERY_PATH]


def test_refund_stops_local_job_without_cancel_and_late_number_is_retained(shop, guanjia, monkeypatch):
    order = create(shop)
    calls = provider(monkeypatch)
    service.run_batch(shop[1])
    result = shop[0].post(f"/api/orders/{order['id']}/refund", headers=shop[2], json={"reason": "不要了"})
    assert result.status_code == 200 and result.json()["status"] == "refunded"
    assert record(shop[1], order).status == "stopped"
    assert callback(shop[0], order["number"]).json() == {"status": "200"}
    row = record(shop[1], order)
    assert row.waybill_id == "73123456789012" and row.status == "stopped" and row.next_action == "none"
    buyer = shop[0].get(f"/api/orders/{order['id']}", headers=shop[2]).json()
    assert buyer["status"] == "refunded" and not buyer["tracking_number"]
    service.run_batch(shop[1])
    assert len(calls) == 1 and calls[0][0] == kd.IMPORT_PATH


def test_callback_before_import_response_is_not_overwritten(shop, guanjia, monkeypatch):
    order = create(shop)
    def early(request, fields):
        if request.url.path == kd.IMPORT_PATH:
            assert callback(shop[0], order["number"]).json() == {"status": "200"}
    provider(monkeypatch, early)
    service.run_batch(shop[1])
    assert record(shop[1], order).status == "ordered"


def test_refund_during_import_does_not_resume_or_cancel(shop, guanjia, monkeypatch):
    order = create(shop)
    def refund(request, fields):
        if request.url.path == kd.IMPORT_PATH:
            result = shop[0].post(f"/api/orders/{order['id']}/refund", headers=shop[2], json={"reason": "不要了"})
            assert result.status_code == 200
    calls = provider(monkeypatch, refund)
    service.run_batch(shop[1])
    assert record(shop[1], order).status == "stopped" and record(shop[1], order).next_action == "none"
    assert len(calls) == 1


def test_old_attempt_callbacks_and_mismatched_waybills_cannot_overwrite(shop, guanjia, monkeypatch):
    order = create(shop)
    provider(monkeypatch)
    service.run_batch(shop[1])
    callback(shop[0], order["number"], kind="SEND", data={"order_number": order["number"], "status": "401"})
    assert record(shop[1], order).status == "failed"
    assert shop[0].post(f"/api/admin/orders/{order['id']}/shipping-sync/retry", headers=ADMIN, json=PACKAGE).status_code == 200
    service.run_batch(shop[1])
    callback(shop[0], order["number"])
    assert not record(shop[1], order).waybill_id
    remote = record(shop[1], order).remote_order_id
    assert remote.endswith("_R2")
    callback(shop[0], remote)
    callback(shop[0], remote, data=[{"order_number": remote, "company_code": "zhongtong", "kuaidi_num": "73111111111111"}])
    row = record(shop[1], order)
    assert row.status == "conflict" and row.waybill_id == "73123456789012"
    callback(shop[0], remote)
    assert record(shop[1], order).status == "conflict"


def test_authorization_state_is_single_use_and_tokens_are_not_exposed(shop, guanjia, monkeypatch):
    monkeypatch.setattr(get_settings(), "kuaidi100_access_token", "")
    assert shop[0].post("/api/admin/kuaidi100/authorize", json={"mobile": "13800138000"}).status_code == 401
    assert shop[0].post("/api/admin/kuaidi100/authorize", json={"mobile": "13800138000"}, headers=shop[2]).status_code == 401
    assert shop[0].post("/api/admin/kuaidi100/authorize", json={"mobile": ""}, headers=ADMIN).status_code == 409
    calls = provider(monkeypatch, lambda req, _: {"access_token": "saved-token", "refresh_token": "saved-refresh", "expires_in": 31536000})
    started = shop[0].post("/api/admin/kuaidi100/authorize", json={"mobile": "13800138000"}, headers=ADMIN)
    assert started.status_code == 200 and "saved-token" not in started.text and "saved-refresh" not in started.text
    status = shop[0].get("/api/admin/wechat-express", headers=ADMIN)
    assert status.json()["configured"] is True and "saved-token" not in status.text and "saved-refresh" not in status.text
    assert len(calls) == 1 and calls[0][0] == "/open/oauth/token"


def test_expiring_database_authorization_refreshes_before_import(shop, guanjia, monkeypatch):
    with shop[1]() as db:
        db.add(Kuaidi100Authorization(app_key=get_settings().kuaidi100_key, access_token="old-token", refresh_token="old-refresh",
                                     expires_at=datetime.utcnow() - timedelta(seconds=1)))
        db.commit()
    def fresh(req, fields):
        if req.url.path.endswith("refreshToken"):
            assert fields["refresh_token"] == "old-refresh"
            return {"access_token": "new-token", "refresh_token": "new-refresh", "expires_in": 31536000}
        assert fields["access_token"] == "new-token"
    calls = provider(monkeypatch, fresh)
    order = create(shop)
    service.run_batch(shop[1])
    assert record(shop[1], order).status == "waiting"
    assert [p for p, _ in calls] == ["/open/oauth/refreshToken", kd.IMPORT_PATH]


def test_enabled_but_unauthorized_never_falls_back_to_wechat(shop, guanjia, monkeypatch):
    monkeypatch.setattr(get_settings(), "kuaidi100_access_token", "")
    monkeypatch.setattr(get_settings(), "wechat_express_enabled", True)
    order = checkout(shop)
    paid(shop, order)
    assert shop[0].post(f"/api/admin/orders/{order['id']}/shipping-sync/create", headers=ADMIN, json=PACKAGE).status_code == 409


def test_old_wechat_order_stays_on_wechat_after_enabling_guanjia(shop, guanjia, monkeypatch):
    from test_wechat_express import provider as wechat_provider
    monkeypatch.setattr(get_settings(), "wechat_app_id", "test-app")
    monkeypatch.setattr(get_settings(), "wechat_app_secret", "test-secret")
    monkeypatch.setattr(get_settings(), "wechat_express_enabled", True)
    monkeypatch.setattr(get_settings(), "wechat_express_asset_origin", "https://api.example.test")
    order = create(shop)
    with shop[1]() as db:
        db.get(WechatExpressOrder, order["id"]).provider = "wechat"
        db.commit()
    monkeypatch.setattr(get_settings(), "kuaidi100_access_token", "")
    calls = wechat_provider(monkeypatch)
    service.run_batch(shop[1])
    assert record(shop[1], order).status == "ordered"
    from app.wechat_express import ORDER_ADD_PATH
    assert any(path == ORDER_ADD_PATH for _, path, _ in calls)
    assert shop[0].get(f"/api/admin/orders/{order['id']}/waybill", headers=ADMIN).status_code == 200
    assert shop[0].post("/api/admin/wechat-express/printer", headers=ADMIN,
                        json={"openid": "test-printer-openid", "update_type": "bind"}).status_code == 200


def test_guanjia_import_keeps_existing_wechat_binding_and_order_fields(shop, guanjia, monkeypatch):
    from test_wechat_express import provider as wechat_provider
    from app import wechat_express as wx
    for key, value in {"wechat_app_id": "test-app", "wechat_app_secret": "test-secret",
                       "wechat_express_enabled": True, "wechat_express_asset_origin": "https://api.example.test"}.items():
        monkeypatch.setattr(get_settings(), key, value)
    wechat_calls = wechat_provider(monkeypatch)
    wechat_handler = httpx.HTTPTransport.handle_request
    guanjia_calls = provider(monkeypatch)
    guanjia_handler = httpx.HTTPTransport.handle_request

    def handle(transport, request):
        handler = guanjia_handler if request.url.host == "b.kuaidi100.com" else wechat_handler
        return handler(transport, request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    order = create(shop)
    service.run_batch(shop[1])
    assert record(shop[1], order).status == "waiting"
    data = json.loads(guanjia_calls[0][1]["data"])
    assert data["order_source"] == "WX" and data["openid"]
    assert data["express_custom_code"] == "fake-biz-id" and data["express_company"] == "ZTO"
    assert data["order_page_url"] and data["service_type"] == "标准快递"
    assert data["goods_list"][0]["img_url"] == "https://api.example.test/product-assets/green.jpg"
    assert not any(path == wx.ORDER_ADD_PATH for _, path, _ in wechat_calls)


def test_environment_refresh_token_can_complete_authorization(shop, guanjia, monkeypatch):
    monkeypatch.setattr(get_settings(), "kuaidi100_access_token", "")
    monkeypatch.setattr(get_settings(), "kuaidi100_refresh_token", "environment-refresh")

    def refreshed(req, fields):
        if req.url.path.endswith("refreshToken"):
            assert fields["refresh_token"] == "environment-refresh"
            return {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 31536000}
        assert fields["access_token"] == "new-access"

    calls = provider(monkeypatch, refreshed)
    order = create(shop)
    service.run_batch(shop[1])
    assert record(shop[1], order).status == "waiting"
    assert [p for p, _ in calls] == ["/open/oauth/refreshToken", kd.IMPORT_PATH]


@pytest.mark.parametrize("carrier,number", [("yuantong", "YT123456789"), ("zhongtong", "731111111,732222222")])
def test_wrong_carrier_or_multiple_waybills_never_become_a_valid_shipment(shop, guanjia, monkeypatch, carrier, number):
    provider(monkeypatch)
    order = create(shop)
    service.run_batch(shop[1])
    assert callback(shop[0], order["number"], data=[{"order_number": order["number"],
                    "company_code": carrier, "kuaidi_num": number}]).json() == {"status": "400"}
    assert record(shop[1], order).status == "waiting" and not record(shop[1], order).waybill_id
    assert not shop[0].get(f"/api/orders/{order['id']}", headers=shop[2]).json()["tracking_number"]
