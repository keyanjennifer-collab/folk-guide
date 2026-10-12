"""物流查看只读、本人隔离，并与真实发货/改运单操作保持一致。"""

import httpx
import pytest
from sqlalchemy import select

from app.commerce_models import Order, ProductInventory
from test_sale_operations import ADMIN, checkout, paid, shop  # 复用隔离测试库与建单夹具。


def snapshot(sessions):
    with sessions() as db:
        orders = [(o.id, o.status, o.total_fen, o.carrier, o.tracking_number) for o in db.scalars(select(Order)).all()]
        inventory = [(i.product_id, i.available, i.reserved, i.sold) for i in db.scalars(select(ProductInventory)).all()]
        return orders, inventory


def test_logistics_is_owner_scoped_and_does_not_contact_third_parties(shop, monkeypatch):
    client, sessions, owner, _ = shop
    order = checkout(shop)

    def unexpected_request(*args, **kwargs):
        pytest.fail("未接物流供应商时不应发起任何外部请求")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", unexpected_request)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", unexpected_request)
    path = f"/api/orders/{order['id']}/logistics"
    assert client.get(path).status_code == 403  # 与项目现有 HTTPBearer 未登录响应一致。
    token = client.post("/api/auth/wechat", json={"code": "logistics-outsider"}).json()["access_token"]
    assert client.get(path, headers={"Authorization": f"Bearer {token}"}).status_code == 404
    assert client.get("/api/orders/999999/logistics", headers=owner).status_code == 404
    before = snapshot(sessions)
    response = client.get(path, headers=owner)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    data = response.json()
    assert data["order_number"] == order["number"]
    assert data["tracking_status"] == "not_shipped" and data["tracking_events"] == []
    assert data["tracking_updated_at"] is None and not data["shipment_recorded"]
    assert "receiver_phone" not in data and "receiver_address" not in data and "user_id" not in data
    assert snapshot(sessions) == before


def test_buyer_sees_shipment_and_latest_tracking_number(shop):
    client, sessions, owner, _ = shop
    order = checkout(shop)
    paid(shop, order)
    path = f"/api/orders/{order['id']}/logistics"
    before_shipping = client.get(path, headers=owner).json()
    assert before_shipping["order_status"] == "paid"
    assert before_shipping["tracking_status"] == "not_shipped"
    assert "尚未登记发货" in before_shipping["tracking_message"]
    shipment = client.post(f"/api/admin/orders/{order['id']}/ship", headers=ADMIN,
                           json={"carrier": "顺丰速运", "tracking_number": "SF1234567890"})
    assert shipment.status_code == 200
    before = snapshot(sessions)
    result = client.get(path, headers=owner).json()
    assert result["carrier"] == "顺丰速运" and result["tracking_number"] == "SF1234567890"
    assert result["shipment_recorded"] and result["tracking_status"] == "not_connected"
    assert result["tracking_events"] == [] and result["tracking_updated_at"] is None
    assert result["order_events"][0]["title"] == "商家已登记发货"
    assert "揽收与运输进度以快递公司信息为准" in result["order_events"][0]["description"]
    assert result["order_events"][0]["time"].endswith(("Z", "+00:00"))
    assert snapshot(sessions) == before
    update = client.put(f"/api/admin/orders/{order['id']}/logistics", headers=ADMIN,
                        json={"carrier": "中通快递", "tracking_number": "ZT9876543210"})
    assert update.status_code == 200
    result = client.get(path, headers=owner).json()
    assert result["carrier"] == "中通快递" and result["tracking_number"] == "ZT9876543210"
    assert client.post(f"/api/orders/{order['id']}/complete", headers=owner).status_code == 200
    result = client.get(path, headers=owner).json()
    assert result["order_events"][0]["title"] == "买家已确认收货"
    assert result["tracking_events"] == []  # 确认收货不是快递平台的签收轨迹。


def test_refunded_shipped_order_keeps_original_shipment_visible(shop):
    client, _, owner, _ = shop
    order = checkout(shop)
    paid(shop, order)
    client.post(f"/api/admin/orders/{order['id']}/ship", headers=ADMIN,
                json={"carrier": "顺丰速运", "tracking_number": "SF1234567890"})
    client.post(f"/api/admin/orders/{order['id']}/refund", headers=ADMIN, json={"reason": "测试售后"})
    result = client.get(f"/api/orders/{order['id']}/logistics", headers=owner).json()
    assert result["order_status"] == "refunded" and result["shipment_recorded"]
    assert result["tracking_number"] == "SF1234567890"
    assert result["order_events"][0]["title"] == "退款已完成"
    assert result["tracking_events"] == []


def test_cancelled_order_does_not_claim_to_be_awaiting_shipment(shop):
    client, _, owner, _ = shop
    order = checkout(shop)
    client.post(f"/api/orders/{order['id']}/cancel", headers=owner)
    result = client.get(f"/api/orders/{order['id']}/logistics", headers=owner).json()
    assert result["order_status"] == "cancelled"
    assert not result["shipment_recorded"]
    assert result["tracking_message"] == "这笔订单暂无发货记录。"
    assert result["order_events"][0]["title"] == "订单已取消"
