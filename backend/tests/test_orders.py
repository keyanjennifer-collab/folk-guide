"""验证本人订单隔离、状态筛选、分页、金额和注销清理。"""
import json
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.order_routes import Order


def test_orders_are_owner_scoped_and_read_only():
    with TestClient(app) as client:
        def login(code):
            token = client.post("/api/auth/wechat", json={"code": code}).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            return headers, client.get("/api/users/me", headers=headers).json()["id"]

        alice, alice_id = login("orders-alice")
        bob, bob_id = login("orders-bob")
        with SessionLocal() as db:
            for uid, number, status in [(alice_id, "TEST-A1", "pending"), (alice_id, "TEST-A2", "shipped"), (bob_id, "TEST-B1", "paid")]:
                db.add(Order(user_id=uid, number=number, status=status, total_fen=5900,
                    items_json=json.dumps([{"product_id": "green", "name": "青木香", "quantity": 1, "unit_price_fen": 5900}])))
            db.commit()
        assert client.get("/api/orders").status_code in (401, 403)
        result = client.get("/api/orders", headers=alice, params={"limit": 1}).json()
        assert len(result["items"]) == 1 and result["has_more"]
        assert result["counts"]["pending"] == 1 and result["counts"]["paid"] == 0
        item = result["items"][0]
        assert item["total_fen"] == 5900 and "user_id" not in item
        assert client.get(f"/api/orders/{item['id']}", headers=bob).status_code == 404
        assert client.get(f"/api/orders/{item['id']}", headers=alice).status_code == 200
        filtered = client.get("/api/orders?status=pending", headers=alice).json()
        assert [row["number"] for row in filtered["items"]] == ["TEST-A1"]
        assert not filtered["has_more"]
        page2 = client.get("/api/orders?limit=1&offset=1", headers=alice).json()
        assert page2["items"][0]["id"] != item["id"] and not page2["has_more"]
        assert client.get("/api/orders?status=unknown", headers=alice).status_code == 422
        assert client.get("/api/orders?offset=-1", headers=alice).status_code == 422
        assert client.post("/api/orders", headers=alice, json={"status": "paid"}).status_code == 405
        assert client.delete("/api/account", headers=alice).status_code == 204
        with SessionLocal() as db:
            assert db.query(Order).filter(Order.user_id == alice_id).count() == 0
            assert db.query(Order).filter(Order.user_id == bob_id).count() == 1
