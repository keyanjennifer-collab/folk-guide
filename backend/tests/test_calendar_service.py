from datetime import date

from app.calendar_service import (
    CALCULATION_VERSION,
    apply_calendar_calculation,
    calculate_birth_calendar,
    load_calendar_payload,
)
from app.models import BirthProfile
from app.schemas import BirthProfileInput
from fastapi.testclient import TestClient

from app.main import app


def test_known_solar_to_lunar_and_four_pillars():
    result = calculate_birth_calendar(
        BirthProfileInput(
            calendar_type="solar",
            birth_date=date(1995, 6, 18),
            time_known=True,
            birth_time="14:30",
            birth_city="上海",
        )
    )
    assert result["solar_date"] == "1995-06-18"
    assert result["solar_datetime"] == "1995-06-18 14:30:00"
    assert result["lunar_date"] == "1995-05-21"
    assert result["lunar_text"] == "一九九五年五月廿一"
    assert result["zodiac"] == "猪"
    assert result["western_sign"] == "双子"
    assert result["solar_term"] is None
    assert result["pillars"]["year"]["text"] == "乙亥"
    assert result["pillars"]["month"]["text"] == "壬午"
    assert result["pillars"]["day"]["text"] == "庚辰"
    assert result["pillars"]["time"]["text"] == "癸未"
    assert result["previous_solar_term"]["name"] == "芒种"
    assert result["previous_solar_term"]["datetime"] == "1995-06-06 11:42:28"
    assert result["next_solar_term"]["name"] == "夏至"
    assert result["next_solar_term"]["datetime"] == "1995-06-22 04:34:22"
    assert result["time_pillar_available"] is True
    assert result["timezone"] == "Asia/Shanghai"
    assert result["time_standard"] == "beijing_standard_time"
    assert result["day_boundary_rule"] == "sect2-midnight"
    assert result["calculation_version"] == CALCULATION_VERSION


def test_unknown_time_omits_time_pillar():
    result = calculate_birth_calendar(
        BirthProfileInput(
            calendar_type="solar",
            birth_date=date(1995, 6, 18),
            time_known=False,
        )
    )
    assert result["time_pillar_available"] is False
    assert result["pillars"]["time"] is None
    assert result["solar_datetime"] is None


def test_unknown_time_result_is_cached_with_calculation_version():
    data = BirthProfileInput(
        calendar_type="solar",
        birth_date=date(1995, 6, 18),
        time_known=False,
    )
    profile = BirthProfile(user_id=12345, profile_version=1, **data.model_dump())

    result = apply_calendar_calculation(profile, data)
    cached = load_calendar_payload(profile)

    assert result["pillars"]["time"] is None
    assert result["time_pillar_available"] is False
    assert profile.calendar_data_json is not None
    assert cached == result
    assert cached["pillars"]["time"] is None
    assert profile.normalized_solar_date == date(1995, 6, 18)
    assert profile.calculation_version == CALCULATION_VERSION
    assert cached["calculation_version"] == CALCULATION_VERSION


def test_calendar_conversion_api():
    with TestClient(app) as client:
        login = client.post("/api/auth/wechat", json={"code": "calendar-api-user"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = client.post(
            "/api/calendar/convert",
            headers=headers,
            json={
                "calendar_type": "lunar",
                "is_leap_month": True,
                "birth_date": "2023-02-01",
                "time_known": False,
            },
        )
        assert response.status_code == 200
        assert response.json()["solar_date"] == "2023-03-22"
        client.delete("/api/account", headers=headers)
