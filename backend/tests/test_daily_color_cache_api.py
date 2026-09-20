"""公共7天缓存、个人3天缓存和AI国学权益门槛测试。"""

import json
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import AIServiceGrant, DailyGuidance, PublicColorCache, User
from app.time_service import utc_now_naive


def login(client: TestClient, code: str) -> tuple[dict[str, str], int]:
    token = client.post("/api/auth/wechat", json={"code": code}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    user_id = client.get("/api/users/me", headers=headers).json()["id"]
    return headers, user_id


def test_public_today_warms_seven_days_and_returns_automatic_result(monkeypatch):
    fixed_day = date(2042, 3, 5)
    end_day = fixed_day + timedelta(days=7)
    monkeypatch.setattr("app.public_guide_routes.beijing_today", lambda: fixed_day)

    with TestClient(app) as client:
        with SessionLocal() as db:
            db.query(PublicColorCache).filter(
                PublicColorCache.guide_date >= fixed_day,
                PublicColorCache.guide_date < end_day,
            ).delete()
            db.commit()
        response = client.get("/api/public-guides/today")

    assert response.status_code == 200
    assert response.json()["guide_date"] == fixed_day.isoformat()
    assert [item["smoothness"] for item in response.json()["items"]] == [
        "得生助旺", "同气相和", "克制求进", "生泄耗气", "受制势弱",
    ]
    with SessionLocal() as db:
        rows = db.scalars(select(PublicColorCache).where(
            PublicColorCache.guide_date >= fixed_day,
            PublicColorCache.guide_date < end_day,
        ).order_by(PublicColorCache.guide_date)).all()
        assert len(rows) == 7
        assert all(row.rule_version == "wuse-public-day-branch-v2.1" for row in rows)


def test_active_ai_trial_warms_three_personal_days_from_birth_profile():
    with TestClient(app) as client:
        headers, user_id = login(client, "personal-color-active-trial")
        assert client.get("/api/daily", headers=headers).status_code == 409

        created = client.put(
            "/api/profiles/current",
            headers=headers,
            json={
                "calendar_type": "solar",
                "birth_date": "1995-06-18",
                "time_known": True,
                "birth_time": "14:30",
                "birth_city": "杭州",
            },
        )
        assert created.status_code == 200
        daily = client.get("/api/daily", headers=headers)
        assert daily.status_code == 200
        payload = daily.json()
        assert payload["rule_version"] == "PERSONAL_FIVE_COLOR_V1"
        assert payload["precision_mode"] == "four_pillars"
        assert payload["profile_version"] == created.json()["profile_version"]
        assert payload["entitlement_plan"] == "new_user_3_days"
        assert payload["content_version"] == "personal-guidance-v1.2"
        assert payload["primary_color"] == payload["colors"][0]["name"]
        assert payload["supporting_colors"] == [payload["colors"][1]["name"], payload["colors"][2]["name"]]
        assert payload["algorithm_version"] == "PERSONAL_FIVE_COLOR_V1"
        assert set(payload["factors"]) == {"natalResponse", "dailyStem", "dailyBranchInteraction", "dailyElementDynamic", "publicScore"}
        assert len(payload["ranking"]) == 5
        assert len(payload["colors"]) == 5
        assert {item["name"] for item in payload["colors"]} == {"白色系", "绿色系", "黑色系", "红色系", "黄色系"}
        assert {item["product"] for item in payload["colors"]} == {"白桂", "青木", "墨沉", "朱蜜", "黄檀"}
        assert all(item["reason"] and item["resistance"] and item["advice"] for item in payload["colors"])
        assert "config_fingerprint" not in payload
        assert "input_fingerprint" not in payload

        next_date = date.fromisoformat(payload["date"]) + timedelta(days=1)
        next_daily = client.get(f"/api/daily?date={next_date.isoformat()}", headers=headers)
        assert next_daily.status_code == 200
        assert next_daily.json()["date"] == next_date.isoformat()

        with SessionLocal() as db:
            rows = db.scalars(select(DailyGuidance).where(
                DailyGuidance.user_id == user_id
            ).order_by(DailyGuidance.guidance_date)).all()
            assert len(rows) == 3
            assert all(json.loads(row.payload_json)["profile_version"] == created.json()["profile_version"] for row in rows)

        client.delete("/api/account", headers=headers)


def test_expired_ai_trial_still_reads_default_unlocked_personal_colors():
    with TestClient(app) as client:
        headers, user_id = login(client, "personal-color-expired-trial")
        now = utc_now_naive()
        with SessionLocal() as db:
            user = db.get(User, user_id)
            assert user is not None
            user.created_at = now - timedelta(days=10)
            db.commit()

        created = client.put(
            "/api/profiles/current",
            headers=headers,
            json={
                "calendar_type": "solar",
                "birth_date": "1982-11-03",
                "time_known": False,
            },
        )
        assert created.status_code == 200
        allowed = client.get("/api/daily", headers=headers)
        assert allowed.status_code == 200
        assert allowed.json()["entitlement_plan"] == "default_unlocked"
        with SessionLocal() as db:
            assert len(db.scalars(select(DailyGuidance).where(DailyGuidance.user_id == user_id)).all()) == 3

        client.delete("/api/account", headers=headers)
