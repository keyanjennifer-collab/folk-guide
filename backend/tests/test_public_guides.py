"""公开每日五色自动更新接口。"""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import PublicColorCache


FORMAL_COLORS = {"白色系", "绿色系", "黑色系", "红色系", "黄色系"}


def clear_cache(day: date) -> None:
    with SessionLocal() as db:
        row = db.scalar(select(PublicColorCache).where(PublicColorCache.guide_date == day))
        if row:
            db.delete(row)
            db.commit()


def test_today_is_generated_automatically_for_beijing_date(monkeypatch):
    fixed_day = date(2036, 8, 20)
    monkeypatch.setattr("app.public_guide_routes.beijing_today", lambda: fixed_day)

    with TestClient(app) as client:
        clear_cache(fixed_day)
        response = client.get("/api/public-guides/today")

    assert response.status_code == 200
    payload = response.json()
    assert payload["guide_date"] == fixed_day.isoformat()
    assert [item["rank"] for item in payload["items"]] == [1, 2, 3, 4, 5]
    assert {item["color"] for item in payload["items"]} == FORMAL_COLORS
    assert all(item["suitable"] and item["resistance"] and item["advice"] for item in payload["items"])
    clear_cache(fixed_day)


def test_date_endpoint_reuses_the_deterministic_cache():
    fixed_day = date(2037, 1, 12)
    with TestClient(app) as client:
        clear_cache(fixed_day)
        first = client.get(f"/api/public-guides/{fixed_day}")
        second = client.get(f"/api/public-guides/{fixed_day}")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    with SessionLocal() as db:
        assert db.scalar(select(PublicColorCache).where(PublicColorCache.guide_date == fixed_day)) is not None
    clear_cache(fixed_day)


def test_manual_public_guide_backend_is_removed():
    with TestClient(app) as client:
        assert client.get("/admin/public-guides").status_code == 404
        assert client.get("/api/admin/public-guides", headers={"X-Admin-Key": "dev-admin-key"}).status_code == 404
