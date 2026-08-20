from fastapi.testclient import TestClient

from app.main import app


def test_complete_development_flow():
    with TestClient(app) as client:
        login = client.post("/api/auth/wechat", json={"code": "pytest-user"})
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        missing = client.get("/api/daily", headers=headers)
        assert missing.status_code == 409

        profile = client.put(
            "/api/profiles/current",
            headers=headers,
            json={
                "calendar_type": "solar",
                "birth_date": "1995-06-18",
                "birth_time": "14:30",
                "birth_city": "上海",
                "gender": "unspecified",
            },
        )
        assert profile.status_code == 200

        daily = client.get("/api/daily", headers=headers)
        assert daily.status_code == 200
        assert daily.json()["colors"]

        normal_chat = client.post("/api/chat", headers=headers, json={"question": "什么是二十四节气？"})
        assert normal_chat.status_code == 200
        assert normal_chat.json()["category"] == "normal_culture"

        unsafe_chat = client.post("/api/chat", headers=headers, json={"question": "请预测我什么时候死"})
        assert unsafe_chat.status_code == 200
        assert unsafe_chat.json()["category"] == "high_risk_prediction"

        deleted = client.delete("/api/account", headers=headers)
        assert deleted.status_code == 204

