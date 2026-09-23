"""验证开售版的服务端计价、库存、支付、退款和发货闭环。"""

from fastapi.testclient import TestClient

from app.main import app


ADMIN = {"X-Admin-Key": "dev-admin-key", "X-Admin-Name": "pytest"}


def login(client: TestClient, code: str) -> dict[str, str]:
    token = client.post("/api/auth/wechat", json={"code": code}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def address(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post("/api/addresses", headers=headers, json={
        "recipient_name": "测试收货人", "phone": "13800138000", "province": "浙江省",
        "city": "杭州市", "district": "西湖区", "detail": "测试路1号",
        "postal_code": "310000", "is_default": True,
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def set_stock(client: TestClient, product_id: str, available: int):
    response = client.put(f"/api/admin/inventory/{product_id}", headers=ADMIN,
                          json={"available": available, "active": True})
    assert response.status_code == 200, response.text


def test_checkout_uses_server_price_and_idempotency_then_refunds():
    with TestClient(app) as client:
        owner = login(client, "commerce-owner")
        outsider = login(client, "commerce-outsider")
        set_stock(client, "green", 2)
        address_id = address(client, owner)
        outsider_address = address(client, outsider)

        payload = {
            "items": [{"product_id": "green", "quantity": 2, "unit_price_fen": 1}],
            "address_id": address_id, "idempotency_key": "same-checkout-key", "total_fen": 1,
        }
        created = client.post("/api/orders", headers=owner, json=payload)
        assert created.status_code == 201, created.text
        order = created.json()
        assert order["subtotal_fen"] == 11800
        assert order["shipping_fee_fen"] == 1000
        assert order["total_fen"] == 12800
        assert order["items"][0]["unit_price_fen"] == 5900

        repeated = client.post("/api/orders", headers=owner, json=payload)
        assert repeated.status_code == 201
        assert repeated.json()["id"] == order["id"]
        sold_out = client.post("/api/orders", headers=outsider, json={
            "items": [{"product_id": "green", "quantity": 1}],
            "address_id": outsider_address, "idempotency_key": "outsider-checkout",
        })
        assert sold_out.status_code == 409
        assert client.get(f"/api/orders/{order['id']}", headers=outsider).status_code == 404

        payment = client.post(f"/api/orders/{order['id']}/pay", headers=owner)
        assert payment.status_code == 200 and payment.json()["mock"] is True
        paid = client.post(f"/api/orders/{order['id']}/mock-pay", headers=owner)
        assert paid.status_code == 200 and paid.json()["status"] == "paid"
        inventory = {row["product_id"]: row for row in client.get("/api/admin/inventory", headers=ADMIN).json()}
        assert inventory["green"]["available"] == 0
        assert inventory["green"]["reserved"] == 0
        assert inventory["green"]["sold"] == 2

        refunded = client.post(f"/api/orders/{order['id']}/refund", headers=owner,
                               json={"reason": "测试整单退款"})
        assert refunded.status_code == 200 and refunded.json()["status"] == "refunded"
        inventory = {row["product_id"]: row for row in client.get("/api/admin/inventory", headers=ADMIN).json()}
        assert inventory["green"]["available"] == 2 and inventory["green"]["sold"] == 0


def test_cancel_releases_stock_and_admin_can_ship_paid_order():
    with TestClient(app) as client:
        user = login(client, "commerce-ship-user")
        address_id = address(client, user)
        set_stock(client, "gold", 2)
        first = client.post("/api/orders", headers=user, json={
            "items": [{"product_id": "gold", "quantity": 1}], "address_id": address_id,
            "idempotency_key": "cancel-this-order",
        }).json()
        cancelled = client.post(f"/api/orders/{first['id']}/cancel", headers=user)
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        inventory = {row["product_id"]: row for row in client.get("/api/admin/inventory", headers=ADMIN).json()}
        assert inventory["gold"]["available"] == 2 and inventory["gold"]["reserved"] == 0

        second = client.post("/api/orders", headers=user, json={
            "items": [{"product_id": "gold", "quantity": 1}], "address_id": address_id,
            "idempotency_key": "ship-this-order",
        }).json()
        client.post(f"/api/orders/{second['id']}/mock-pay", headers=user)
        shipped = client.post(f"/api/admin/orders/{second['id']}/ship", headers=ADMIN,
                              json={"carrier": "顺丰速运", "tracking_number": "SF1234567890"})
        assert shipped.status_code == 200 and shipped.json()["status"] == "shipped"
        assert shipped.json()["tracking_number"] == "SF1234567890"
        completed = client.post(f"/api/orders/{second['id']}/complete", headers=user)
        assert completed.status_code == 200 and completed.json()["status"] == "completed"
