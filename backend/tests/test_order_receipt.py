"""用独立商城订单核对十天自动收货，不访问微信或快递接口。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.admin_models import AdminAuditLog
from app.commerce_models import Order, ProductInventory
from app.config import get_settings
from app.order_receipt_service import complete_due_orders
from test_sale_operations import ADMIN, checkout, paid, shop

CURRENT_TIME = datetime(2026, 11, 7, 8, 30)


@pytest.fixture
def shipped(shop):
    order = checkout(shop)
    paid(shop, order)
    assert shop[0].post(f"/api/admin/orders/{order['id']}/ship", headers=ADMIN,
                       json={"carrier": "中通快递", "tracking_number": "73123456786642"}).status_code == 200
    return order


def stored_order(shop, order):
    with shop[1]() as db:
        result = db.get(Order, order["id"])
        db.expunge(result)
        return result


@pytest.mark.parametrize("elapsed,expected", [
    (timedelta(days=10) - timedelta(seconds=1), 0),
    (timedelta(days=10), 1),
    (timedelta(days=10, seconds=1), 1),
    (timedelta(days=30), 1),
])
def test_receipt_starts_from_shipping_and_requires_ten_full_days(shop, shipped, elapsed, expected):
    with shop[1]() as db:
        order = db.get(Order, shipped["id"])
        order.created_at = CURRENT_TIME - timedelta(days=60)
        order.paid_at = CURRENT_TIME - timedelta(days=50)
        order.shipped_at = CURRENT_TIME - elapsed
        db.commit()
    assert complete_due_orders(shop[1], current_time=CURRENT_TIME) == expected
    order = stored_order(shop, shipped)
    assert order.status == ("completed" if expected else "shipped")
    assert order.completed_at == (CURRENT_TIME if expected else None)


@pytest.mark.parametrize("status", ["pending", "paid", "after_sale", "refunded", "cancelled", "completed"])
def test_other_order_states_are_never_automatically_changed(shop, shipped, status):
    previous_completion = CURRENT_TIME - timedelta(days=1) if status == "completed" else None
    with shop[1]() as db:
        order = db.get(Order, shipped["id"])
        order.status, order.shipped_at = status, CURRENT_TIME - timedelta(days=20)
        order.completed_at = previous_completion
        db.commit()
    assert complete_due_orders(shop[1], current_time=CURRENT_TIME) == 0
    order = stored_order(shop, shipped)
    assert order.status == status and order.completed_at == previous_completion


@pytest.mark.parametrize("field,value", [
    ("shipped_at", None), ("refund_number", "refund-processing"),
    ("refunded_at", CURRENT_TIME - timedelta(days=1)),
])
def test_missing_shipping_time_and_refunds_are_skipped(shop, shipped, field, value):
    with shop[1]() as db:
        order = db.get(Order, shipped["id"])
        order.shipped_at = CURRENT_TIME - timedelta(days=20)
        setattr(order, field, value)
        db.commit()
    assert complete_due_orders(shop[1], current_time=CURRENT_TIME) == 0
    assert stored_order(shop, shipped).status == "shipped"


def test_multiple_workers_complete_once_without_changing_inventory(shop, shipped):
    with shop[1]() as db:
        db.get(Order, shipped["id"]).shipped_at = CURRENT_TIME - timedelta(days=20)
        before = [(x.product_id, x.available, x.reserved, x.sold) for x in db.scalars(select(ProductInventory))]
        db.commit()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: complete_due_orders(shop[1], current_time=CURRENT_TIME), range(2)))
    assert sorted(results) == [0, 1]
    assert complete_due_orders(shop[1], current_time=CURRENT_TIME) == 0
    with shop[1]() as db:
        assert db.scalar(select(func.count()).select_from(AdminAuditLog).where(
            AdminAuditLog.action == "order_auto_complete")) == 1
        assert [(x.product_id, x.available, x.reserved, x.sold) for x in db.scalars(select(ProductInventory))] == before
    events = shop[0].get(f"/api/orders/{shipped['id']}/logistics", headers=shop[2]).json()["order_events"]
    assert any(event["title"] == "系统已自动确认收货" for event in events)


def test_manual_receipt_still_works_before_ten_days_without_wechat_configuration(shop, shipped, monkeypatch):
    monkeypatch.setattr(get_settings(), "wechat_pay_mode", "wechat")
    with shop[1]() as db:
        db.get(Order, shipped["id"]).shipped_at = CURRENT_TIME - timedelta(days=1)
        db.commit()
    result = shop[0].post(f"/api/orders/{shipped['id']}/complete", headers=shop[2])
    assert result.status_code == 200 and result.json()["status"] == "completed"
    assert complete_due_orders(shop[1], current_time=CURRENT_TIME) == 0
