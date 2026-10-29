"""七天体验、历史套装永久权益、退款撤销及服务端功能边界。"""

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.entitlements import LIFETIME_PLAN, TRIAL_PLAN, feature_access_for_user
from app.main import app
from app.models import AIServiceGrant, User
from app.commerce_models import Order
from app.daily_update_service import _active_paid_plans, _entitlement_plan
from app.time_service import utc_now_naive

ADMIN = {"X-Admin-Key": "dev-admin-key", "X-Admin-Name": "pytest"}
PERSON = {"label": "体验命盘", "birth_date": "1990-01-02", "birth_time": "08:00", "gender": "male"}


@pytest.fixture
def client():
    with TestClient(app) as result:
        yield result


def login(client, age_days=10):
    code = f"entitlement-{uuid4().hex}"
    token = client.post("/api/auth/wechat", json={"code": code}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    user_id = client.get("/api/users/me", headers=headers).json()["id"]
    with SessionLocal() as db:
        db.get(User, user_id).created_at = utc_now_naive() - timedelta(days=age_days)
        db.commit()
    return headers, user_id, code


def stored_order(user_id, *, status="paid", product="gift", paid=True, refunded=False, cancelled=False, items=None):
    now = utc_now_naive()
    with SessionLocal() as db:
        order = Order(user_id=user_id, number=f"WS-{uuid4().hex}", status=status, total_fen=26800,
                      items_json=json.dumps(items if items is not None else [
                          {"product_id": product, "quantity": 1, "unit_price_fen": 26800}]),
                      paid_at=now - timedelta(days=100) if paid else None,
                      refunded_at=now if refunded else None, cancelled_at=now if cancelled else None)
        db.add(order)
        db.commit()
        return order.id


def test_trial_is_exactly_seven_days_and_relogin_does_not_reset_it(client):
    headers, user_id, code = login(client, age_days=6)
    quota = client.get("/api/ai/quota", headers=headers).json()
    assert quota["active"] and quota["plan"] == TRIAL_PLAN
    assert quota["normal_limit"] == 20 and quota["comparison_limit"] == 2
    with SessionLocal() as db:
        user = db.get(User, user_id)
        start = user.created_at
        assert feature_access_for_user(db, user, start + timedelta(days=7, microseconds=-1)).active
        assert not feature_access_for_user(db, user, start + timedelta(days=7)).active
        assert not feature_access_for_user(db, user, start - timedelta(microseconds=1)).active
    client.post("/api/auth/wechat", json={"code": code})
    with SessionLocal() as db:
        assert db.get(User, user_id).created_at == start


@pytest.mark.parametrize("status,paid,refunded,cancelled,product,expected", [
    ("paid", True, False, False, "gift", True),
    ("shipped", True, False, False, "gift", True),
    ("completed", True, False, False, "gift", True),
    ("after_sale", True, False, False, "gift", True),
    ("pending", False, False, False, "gift", False),
    ("cancelled", True, False, True, "gift", False),
    ("refunded", True, True, False, "gift", False),
    ("paid", False, False, False, "gift", False),
    ("paid", True, True, False, "gift", False),
    ("paid", True, False, True, "gift", False),
    ("paid", True, False, False, "green", False),
])
def test_only_real_paid_gift_orders_unlock_lifetime(client, status, paid, refunded, cancelled, product, expected):
    headers, user_id, _ = login(client, age_days=500)
    stored_order(user_id, status=status, paid=paid, refunded=refunded, cancelled=cancelled, product=product)
    quota = client.get("/api/ai/quota", headers=headers).json()
    assert quota["active"] is expected
    if expected:
        assert quota["plan"] == LIFETIME_PLAN and quota["expires_at"] is None
        assert quota["normal_limit"] == 50
        with SessionLocal() as db:
            assert _active_paid_plans(db, [user_id], utc_now_naive())[user_id] == LIFETIME_PLAN


def test_historical_gift_refund_keeps_other_purchase_and_trial(client):
    headers, user_id, _ = login(client)
    first, second = stored_order(user_id), stored_order(user_id)
    with SessionLocal() as db:
        db.get(Order, first).status = "refunded"
        db.get(Order, first).refunded_at = utc_now_naive()
        db.commit()
    assert client.get("/api/ai/quota", headers=headers).json()["plan"] == LIFETIME_PLAN
    with SessionLocal() as db:
        db.get(Order, second).status = "refunded"
        db.get(Order, second).refunded_at = utc_now_naive()
        db.commit()
    assert not client.get("/api/ai/quota", headers=headers).json()["active"]
    with SessionLocal() as db:
        user = db.get(User, user_id)
        user.created_at = utc_now_naive() - timedelta(days=6)
        db.commit()
        assert _entitlement_plan(user, {}, utc_now_naive()) == TRIAL_PLAN
    assert client.get("/api/ai/quota", headers=headers).json()["plan"] == TRIAL_PLAN


@pytest.mark.parametrize("method,path,payload", [
    ("get", "/api/daily", None),
    ("get", "/api/ziwei/charts", None),
    ("get", "/api/ziwei/compatibilities", None),
    ("post", "/api/ziwei/charts", PERSON),
    ("post", "/api/ziwei/compatibilities", {"relation_type": "business", "person_a": PERSON, "person_b": PERSON}),
    ("post", "/api/ziwei/interpret", {"chart_id": 1}),
    ("post", "/api/ziwei/compatibility/analyze", {"compatibility_id": 1}),
    ("post", "/api/ai/chat", {"question": "解释五行文化"}),
    ("post", "/api/chat", {"question": "解释五行文化"}),
])
def test_expired_trial_blocks_every_feature_at_api_boundary(client, method, path, payload):
    headers, _, _ = login(client)
    kwargs = {"headers": headers}
    if payload is not None:
        kwargs["json"] = payload
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "feature_access_required"
    assert client.get("/api/public-guides/today").status_code == 200


def test_real_checkout_payment_and_successful_refund_toggle_access(client):
    headers, _, _ = login(client)
    assert client.put("/api/admin/inventory/gift", headers=ADMIN, json={"available": 3, "active": True}).status_code == 200
    address = client.post("/api/addresses", headers=headers, json={
        "recipient_name": "权益测试", "phone": "13800138000", "province": "浙江省", "city": "杭州市",
        "district": "西湖区", "detail": "测试路1号", "is_default": True,
    })
    assert address.status_code == 201, address.text
    order = client.post("/api/orders", headers=headers, json={
        "items": [{"product_id": "gift", "quantity": 1}], "address_id": address.json()["id"],
        "idempotency_key": uuid4().hex,
    })
    assert order.status_code == 201, order.text
    assert not client.get("/api/ai/quota", headers=headers).json()["active"]
    order_id = order.json()["id"]
    assert client.post(f"/api/orders/{order_id}/mock-pay", headers=headers).status_code == 200
    assert client.get("/api/ai/quota", headers=headers).json()["plan"] == LIFETIME_PLAN
    profile = client.put("/api/profiles/current", headers=headers, json={
        "calendar_type": "solar", "birth_date": "1990-01-02", "time_known": False,
    })
    assert profile.status_code == 200, profile.text
    assert client.get("/api/daily", headers=headers).json()["entitlement_plan"] == LIFETIME_PLAN
    refund = client.post(f"/api/orders/{order_id}/refund", headers=headers, json={"reason": "测试赠送权益撤销"})
    assert refund.status_code == 200 and refund.json()["status"] == "refunded", refund.text
    assert not client.get("/api/ai/quota", headers=headers).json()["active"]
    assert client.get("/api/daily", headers=headers).status_code == 403


def test_expiry_blocks_saved_interpretation_cache_before_returning_it(client, monkeypatch):
    headers, user_id, _ = login(client, age_days=6)
    monkeypatch.setattr("app.ziwei_interpret_routes._model_answer", lambda *args: ("测试解读", "pytest"))
    chart = client.post("/api/ziwei/charts", headers=headers, json=PERSON)
    assert chart.status_code == 200, chart.text
    request = {"chart_id": chart.json()["id"]}
    assert client.post("/api/ziwei/interpret", headers=headers, json=request).status_code == 200
    assert client.post("/api/ziwei/interpret", headers=headers, json=request).json()["cached"] is True
    with SessionLocal() as db:
        db.get(User, user_id).created_at = utc_now_naive() - timedelta(days=8)
        db.commit()
    assert client.post("/api/ziwei/interpret", headers=headers, json=request).status_code == 403
    assert client.get("/api/ziwei/charts", headers=headers).status_code == 403


def test_existing_term_grant_is_preserved_and_gift_is_not_shared_between_accounts(client):
    headers, user_id, _ = login(client)
    other, other_id, _ = login(client)
    stored_order(other_id)
    assert not client.get("/api/ai/quota", headers=headers).json()["active"]
    assert client.get("/api/ai/quota", headers=other).json()["plan"] == LIFETIME_PLAN
    with SessionLocal() as db:
        now = utc_now_naive()
        db.add(AIServiceGrant(user_id=user_id, grant_type="paid_30_days", start_at=now - timedelta(days=1), end_at=now + timedelta(days=20)))
        db.commit()
    assert client.get("/api/ai/quota", headers=headers).json()["plan"] == "paid_30_days"
