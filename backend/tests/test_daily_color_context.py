"""每日五色规则输入输出契约测试。"""

from datetime import date

import pytest
from pydantic import ValidationError

from app.calendar_service import apply_calendar_calculation
from app.daily_color_context import build_personal_rule_input, build_public_rule_input
from app.daily_color_rule_catalog import FRAMEWORK_RULE_DEFINITION
from app.daily_color_schemas import ColorRuleItem
from app.models import BirthProfile
from app.schemas import BirthProfileInput


def make_profile(*, time_known: bool, birth_time: str | None, version: int = 1) -> BirthProfile:
    """创建不写数据库的档案对象，测试只关注历法缓存和规则输入。"""
    data = BirthProfileInput(
        birth_date=date(1995, 6, 18),
        time_known=time_known,
        birth_time=birth_time,
        birth_city="杭州",
        gender="female",
    )
    profile = BirthProfile(user_id=123, profile_version=version, **data.model_dump())
    apply_calendar_calculation(profile, data)
    return profile


def test_public_context_is_stable_and_uses_beijing_calendar_facts():
    first = build_public_rule_input(date(2026, 8, 19))
    second = build_public_rule_input(date(2026, 8, 19))

    assert first == second
    assert first.input_fingerprint == second.input_fingerprint
    assert first.calendar.time_standard == "北京时间"
    assert first.calendar.timezone_id == "Asia/Shanghai"
    assert first.calendar.weekday == "星期三"
    assert first.calendar.lunar_date == "2026-07-07"
    assert first.calendar.pillars.day.text == "乙丑"
    assert first.calendar.pillars.day.stem_element == "木"
    assert first.calendar.previous_solar_term.name == "立秋"
    assert first.calendar.previous_solar_term.at_beijing.isoformat().endswith("+08:00")
    assert FRAMEWORK_RULE_DEFINITION.status == "test_only"
    assert FRAMEWORK_RULE_DEFINITION.reviewed_by is None


def test_personal_context_uses_four_pillars_but_excludes_identity_fields():
    profile = make_profile(time_known=True, birth_time="14:30", version=3)
    result = build_personal_rule_input(profile, date(2026, 8, 19))
    serialized = result.model_dump(mode="json")

    assert result.precision_mode == "four_pillars"
    assert result.profile_version == 3
    assert result.birth_context.pillars.time is not None
    assert result.birth_context.day_master_stem == "庚"
    assert result.birth_context.day_master_element == "金"
    assert "user_id" not in serialized
    assert "birth_city" not in serialized
    assert "gender" not in serialized
    assert "phone_number" not in serialized


def test_unknown_birth_time_uses_three_pillars_without_inventing_time_pillar():
    profile = make_profile(time_known=False, birth_time=None)
    result = build_personal_rule_input(profile, date(2026, 8, 20))

    assert result.precision_mode == "three_pillars"
    assert result.birth_context.time_pillar_available is False
    assert result.birth_context.pillars.time is None


def test_color_rule_item_rejects_wrong_color_element_mapping():
    with pytest.raises(ValidationError, match="红金必须对应五行火"):
        ColorRuleItem(
            rank=1,
            color="红金",
            element="木",
            rule_score=100,
            tendency="strong_support",
            basis_codes=["DAY_STEM_RELATION"],
        )


def test_personal_fingerprint_changes_with_profile_version():
    first = build_personal_rule_input(make_profile(time_known=True, birth_time="14:30", version=1), date(2026, 8, 19))
    second = build_personal_rule_input(make_profile(time_known=True, birth_time="14:30", version=2), date(2026, 8, 19))

    assert first.input_fingerprint != second.input_fingerprint
