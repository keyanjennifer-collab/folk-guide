import json
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.models import BirthProfile, DailyGuidance
from app.schemas import BirthProfileInput


def login_headers(client: TestClient, code: str) -> dict[str, str]:
    response = client.post("/api/auth/wechat", json={"code": code})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_profile_input_normalizes_calendar_time_and_city_conflicts():
    """显式开关优先，异常客户端携带的残留字段不能反向改变用户选择。"""
    normalized = BirthProfileInput(
        calendar_type="solar",
        is_leap_month=True,
        birth_date=date(1990, 1, 2),
        time_known=False,
        birth_time="08:15",
        birth_city="   ",
    )

    assert normalized.is_leap_month is False
    assert normalized.time_known is False
    assert normalized.birth_time is None
    assert normalized.birth_city is None


def test_profile_supports_unknown_time_and_completeness():
    with TestClient(app) as client:
        headers = login_headers(client, "profile-unknown-time")
        response = client.put(
            "/api/profiles/current",
            headers=headers,
            json={
                "calendar_type": "lunar",
                "is_leap_month": True,
                "birth_date": "2023-02-01",
                "time_known": False,
                "birth_time": None,
                "birth_city": None,
                "gender": "unspecified",
                "timezone": "Asia/Shanghai",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["is_leap_month"] is True
        assert payload["birth_time"] is None
        assert payload["result_mode"] == "simplified"
        assert payload["completeness"] == 50
        assert set(payload["missing_fields"]) == {"birth_time", "birth_city", "gender"}
        assert payload["calendar"]["solar_date"] == "2023-03-22"
        assert payload["calendar"]["is_leap_month"] is True
        assert payload["calendar"]["pillars"]["time"] is None
        client.delete("/api/account", headers=headers)


def test_profile_full_mode_and_version_increment():
    with TestClient(app) as client:
        headers = login_headers(client, "profile-full-mode")
        data = {
            "calendar_type": "solar",
            "is_leap_month": True,
            "birth_date": "1990-01-02",
            "time_known": True,
            "birth_time": "08:15",
            "birth_city": " 杭州 ",
            "gender": "female",
            "timezone": "Asia/Shanghai",
        }
        created = client.put("/api/profiles/current", headers=headers, json=data)
        assert created.status_code == 200
        first = created.json()
        assert first["is_leap_month"] is False
        assert first["time_known"] is True
        assert first["birth_city"] == "杭州"
        assert first["result_mode"] == "full"
        assert first["completeness"] == 100
        assert first["calendar"]["solar_date"] == "1990-01-02"
        assert first["calendar"]["pillars"]["time"] is not None

        updated = client.put("/api/profiles/current", headers=headers, json=data)
        assert updated.status_code == 200
        assert updated.json()["profile_version"] == first["profile_version"] + 1
        client.delete("/api/account", headers=headers)


def test_profile_rejects_future_date():
    with TestClient(app) as client:
        headers = login_headers(client, "profile-future-date")
        response = client.put(
            "/api/profiles/current",
            headers=headers,
            json={
                "birth_date": (date.today() + timedelta(days=1)).isoformat(),
                "time_known": False,
            },
        )
        assert response.status_code == 422
        client.delete("/api/account", headers=headers)


def test_profile_rejects_nonexistent_leap_month():
    with TestClient(app) as client:
        headers = login_headers(client, "profile-invalid-leap")
        response = client.put(
            "/api/profiles/current",
            headers=headers,
            json={
                "calendar_type": "lunar",
                "is_leap_month": True,
                "birth_date": "1992-05-12",
                "time_known": False,
            },
        )
        assert response.status_code == 422
        assert "闰月" in response.json()["detail"]
        client.delete("/api/account", headers=headers)


def test_profile_change_deletes_old_daily_guidance_cache():
    """档案版本变化与缓存删除必须在同一次保存事务中完成。"""
    with TestClient(app) as client:
        headers = login_headers(client, "profile-cache-invalidation")
        user_id = client.get("/api/users/me", headers=headers).json()["id"]
        original = {
            "calendar_type": "solar",
            "birth_date": "1995-06-18",
            "time_known": False,
        }
        created = client.put("/api/profiles/current", headers=headers, json=original)
        assert created.status_code == 200
        assert client.get("/api/daily", headers=headers).status_code == 200

        with SessionLocal() as db:
            before_rows = db.scalars(
                select(DailyGuidance).where(DailyGuidance.user_id == user_id)
            ).all()
            assert len(before_rows) == 3
            before_version = created.json()["profile_version"]
            assert all(json.loads(row.payload_json)["profile_version"] == before_version for row in before_rows)

        changed = client.put(
            "/api/profiles/current",
            headers=headers,
            json={**original, "birth_date": "1996-07-20"},
        )
        assert changed.status_code == 200
        assert changed.json()["profile_version"] == created.json()["profile_version"] + 1

        with SessionLocal() as db:
            after_rows = db.scalars(
                select(DailyGuidance).where(DailyGuidance.user_id == user_id)
            ).all()
            assert len(after_rows) == 3
            assert all(
                json.loads(row.payload_json)["profile_version"] == changed.json()["profile_version"]
                for row in after_rows
            )

        client.delete("/api/account", headers=headers)


def test_profile_read_create_update_delete_and_user_isolation():
    """验证小程序真实链路，并确保档案始终按JWT所属用户隔离。"""
    with TestClient(app) as client:
        owner_headers = login_headers(client, "profile-chain-owner")
        other_headers = login_headers(client, "profile-chain-other")
        owner_user_id = client.get("/api/users/me", headers=owner_headers).json()["id"]

        # 新账号第一次进入档案页时应得到明确404，前端据此展示“创建档案”。
        missing = client.get("/api/profiles/current", headers=owner_headers)
        assert missing.status_code == 404
        assert missing.json()["detail"] == "尚未创建生辰档案"

        created = client.put(
            "/api/profiles/current",
            headers=owner_headers,
            json={
                "calendar_type": "solar",
                "birth_date": "1988-05-20",
                "time_known": False,
                "birth_city": None,
                "gender": "unspecified",
                "timezone": "Asia/Shanghai",
            },
        )
        assert created.status_code == 200
        created_payload = created.json()
        assert created_payload["profile_version"] == 1
        assert created_payload["completeness"] == 50
        assert set(created_payload["missing_fields"]) == {"birth_time", "birth_city", "gender"}
        assert created_payload["result_mode"] == "simplified"
        assert created_payload["calendar"]["solar_date"] == "1988-05-20"
        assert created_payload["calendar"]["pillars"]["time"] is None

        # 创建后再次进入页面必须从数据库读回同一档案。
        loaded = client.get("/api/profiles/current", headers=owner_headers)
        assert loaded.status_code == 200
        assert loaded.json()["id"] == created_payload["id"]
        assert loaded.json()["birth_date"] == "1988-05-20"

        # 另一个JWT不能读取拥有者档案，而是保持自己的未创建状态。
        isolated = client.get("/api/profiles/current", headers=other_headers)
        assert isolated.status_code == 404

        updated_data = {
            "calendar_type": "solar",
            "birth_date": "1988-05-20",
            "time_known": True,
            "birth_time": "09:30",
            "birth_city": "苏州",
            "gender": "male",
            "timezone": "Asia/Shanghai",
        }
        updated = client.put("/api/profiles/current", headers=owner_headers, json=updated_data)
        assert updated.status_code == 200
        assert updated.json()["id"] == created_payload["id"]
        assert updated.json()["profile_version"] == created_payload["profile_version"] + 1
        assert updated.json()["completeness"] == 100
        assert updated.json()["missing_fields"] == []
        assert updated.json()["result_mode"] == "full"
        assert updated.json()["calendar"]["pillars"]["time"] is not None

        # 先生成一条个人每日缓存，再验证删除档案会一起删除缓存。
        assert client.get("/api/daily", headers=owner_headers).status_code == 200

        deleted = client.delete("/api/profiles/current", headers=owner_headers)
        assert deleted.status_code == 204
        assert client.get("/api/profiles/current", headers=owner_headers).status_code == 404
        assert client.get("/api/daily", headers=owner_headers).status_code == 409

        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(BirthProfile).where(BirthProfile.user_id == owner_user_id)) == 0
            assert db.scalar(select(func.count()).select_from(DailyGuidance).where(DailyGuidance.user_id == owner_user_id)) == 0

        # 删除档案不等于注销账号：原JWT仍然可以读取同一个微信账号。
        account_after_profile_delete = client.get("/api/users/me", headers=owner_headers)
        assert account_after_profile_delete.status_code == 200
        assert account_after_profile_delete.json()["id"] == owner_user_id

        client.delete("/api/account", headers=owner_headers)
        client.delete("/api/account", headers=other_headers)
