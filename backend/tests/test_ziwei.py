from fastapi.testclient import TestClient

from app.main import app


def login_headers(client: TestClient, code: str) -> dict[str, str]:
    response = client.post("/api/auth/wechat", json={"code": code})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def person(label: str, name: str, date: str, time: str, gender: str) -> dict:
    return {"label": label, "name": name, "birth_date": date, "birth_time": time, "gender": gender,
            "birth_location": "福建省泉州市"}


def test_ziwei_chart_and_compatibility_are_saved_per_user():
    with TestClient(app) as client:
        owner = login_headers(client, "ziwei-owner")
        other = login_headers(client, "ziwei-other")
        alice = person("我的命盘", "甲", "1990-01-02", "08:00", "male")
        chart = client.post("/api/ziwei/charts", headers=owner, json=alice)
        assert chart.status_code == 200
        payload = chart.json()
        assert payload["chart"]["calculationVersion"] == "iztro-2.5.8"
        assert len(payload["chart"]["palaces"]) == 12
        assert payload["chart"]["lunarInfo"]["yearGanZhi"]

        lunar_chart = client.post("/api/ziwei/charts", headers=owner, json={
            **person("农历命盘", "农历测试", "1990-01-02", "08:00", "male"),
            "calendar_type": "lunar", "is_leap_month": False,
        })
        assert lunar_chart.status_code == 200
        assert lunar_chart.json()["calendar_type"] == "lunar"
        assert lunar_chart.json()["chart"]["inputCalendar"]["solarDate"] != "1990-01-02"

        listed = client.get("/api/ziwei/charts", headers=owner)
        assert {item["id"] for item in listed.json()} == {payload["id"], lunar_chart.json()["id"]}
        assert client.get("/api/ziwei/charts", headers=other).json() == []

        result = client.post("/api/ziwei/compatibilities", headers=owner, json={
            "relation_type": "business", "person_a": alice,
            "person_b": person("合作伙伴", "乙", "1992-05-20", "14:30", "female"),
        })
        assert result.status_code == 200
        compatibility = result.json()
        assert compatibility["result"]["title"] == "生意与合伙"
        assert len(compatibility["result"]["observations"]) == 3

        assert len(client.get("/api/ziwei/compatibilities", headers=owner).json()) == 1
        assert client.get("/api/ziwei/compatibilities", headers=other).json() == []
        client.delete("/api/account", headers=owner)
        client.delete("/api/account", headers=other)
