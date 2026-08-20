"""北京时间自然日边界测试。"""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.time_service import beijing_day_bounds_utc_naive, beijing_now, beijing_today


def test_tzdata_can_load_beijing_timezone_identifier():
    """北京时间使用 IANA 标准标识 Asia/Shanghai，Windows 由 tzdata 补足。"""
    assert ZoneInfo("Asia/Shanghai").key == "Asia/Shanghai"


def test_beijing_today_uses_utc_plus_eight_day_boundary():
    """UTC 16:00 已经是北京时间次日零点，缓存日期必须随北京时间切换。"""
    before_midnight = datetime(2026, 8, 19, 15, 59, 59, tzinfo=timezone.utc)
    at_midnight = datetime(2026, 8, 19, 16, 0, 0, tzinfo=timezone.utc)

    assert beijing_today(before_midnight) == date(2026, 8, 19)
    assert beijing_today(at_midnight) == date(2026, 8, 20)
    assert beijing_now(at_midnight).isoformat() == "2026-08-20T00:00:00+08:00"


def test_beijing_now_rejects_ambiguous_naive_datetime():
    """无时区 datetime 含义不明确，拒绝后可避免日期悄悄偏移。"""
    with pytest.raises(ValueError, match="带时区"):
        beijing_now(datetime(2026, 8, 19, 12, 0, 0))


def test_beijing_business_day_converts_to_utc_database_bounds():
    reference = datetime(2026, 8, 19, 16, 30, tzinfo=timezone.utc)
    start, end = beijing_day_bounds_utc_naive(reference)

    assert start == datetime(2026, 8, 19, 16, 0)
    assert end == datetime(2026, 8, 20, 16, 0)
