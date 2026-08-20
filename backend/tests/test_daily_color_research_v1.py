"""资料综合版 V1.0 公共与个人五色规则测试。"""

from datetime import date

import pytest

from app.calendar_service import apply_calendar_calculation
from app.daily_color_context import build_personal_rule_input, build_public_rule_input
from app.daily_color_personal_engine import calculate_birth_structure, calculate_personal_rule, element_role
from app.daily_color_research_v1 import PERSONAL_RESEARCH_CONFIG, PUBLIC_RESEARCH_CONFIG
from app.daily_color_rule_engine import calculate_public_rule
from app.models import BirthProfile
from app.schemas import BirthProfileInput


def make_profile(*, time_known: bool, birth_time: str | None, version: int = 1) -> BirthProfile:
    """构造虚构档案；姓名、手机号等身份信息不进入规则输入。"""
    data = BirthProfileInput(
        birth_date=date(1995, 6, 18),
        time_known=time_known,
        birth_time=birth_time,
        birth_city="杭州",
        gender="female",
    )
    profile = BirthProfile(user_id=9001, profile_version=version, **data.model_dump())
    apply_calendar_calculation(profile, data)
    return profile


def test_research_public_configuration_is_complete_and_transparent():
    assert PUBLIC_RESEARCH_CONFIG.status == "source_reviewed"
    assert sum(PUBLIC_RESEARCH_CONFIG.factor_weights.model_dump().values()) == 100
    assert PUBLIC_RESEARCH_CONFIG.factor_weights.month_stem + PUBLIC_RESEARCH_CONFIG.factor_weights.month_branch == 40
    assert PUBLIC_RESEARCH_CONFIG.factor_weights.day_stem + PUBLIC_RESEARCH_CONFIG.factor_weights.day_branch == 45
    assert PUBLIC_RESEARCH_CONFIG.solar_term_elements["立春"] == "木"
    assert PUBLIC_RESEARCH_CONFIG.solar_term_elements["清明"] == "土"
    assert PUBLIC_RESEARCH_CONFIG.solar_term_elements["立秋"] == "金"
    assert any("工程参数" in item for item in PUBLIC_RESEARCH_CONFIG.professional_references)


def test_public_research_snapshot_for_fixed_beijing_date():
    rule_input = build_public_rule_input(date(2026, 8, 19), PUBLIC_RESEARCH_CONFIG.version)
    calculation = calculate_public_rule(rule_input, PUBLIC_RESEARCH_CONFIG)

    assert calculation.result.rule_status == "source_reviewed"
    assert [(item.color, item.rule_score) for item in calculation.result.ranking.items] == [
        ("红金", 12), ("白金", 7), ("黑金", 3), ("黄金", 2), ("绿金", -4),
    ]
    assert all(trace.contributions for trace in calculation.traces)


def test_personal_four_pillar_result_has_distribution_strength_and_audit_trace():
    rule_input = build_personal_rule_input(
        make_profile(time_known=True, birth_time="14:30", version=3),
        date(2026, 8, 19),
        PERSONAL_RESEARCH_CONFIG.version,
    )
    calculation = calculate_personal_rule(rule_input, PERSONAL_RESEARCH_CONFIG, PUBLIC_RESEARCH_CONFIG)

    assert calculation.result.precision_mode == "four_pillars"
    assert calculation.result.rule_status == "source_reviewed"
    assert calculation.result.profile_version == 3
    assert sum(calculation.element_distribution.values()) == pytest.approx(100, abs=0.001)
    assert calculation.strength.day_master_element == "金"
    assert calculation.strength.resource_element == "土"
    assert calculation.strength.regime == "weak"
    assert [(item.color, item.rule_score) for item in calculation.result.ranking.items] == [
        ("白金", 26), ("黄金", 23), ("黑金", -5), ("绿金", -10), ("红金", -19),
    ]
    assert any(item.source_code == "PERSON_TIME_STEM" for item in calculation.structure_contributions)
    assert all(len(item.basis_codes) == 4 for item in calculation.result.ranking.items)


def test_unknown_time_removes_time_pillar_and_marks_lower_precision():
    rule_input = build_personal_rule_input(
        make_profile(time_known=False, birth_time=None),
        date(2026, 8, 19),
        PERSONAL_RESEARCH_CONFIG.version,
    )
    distribution, contributions = calculate_birth_structure(rule_input, PERSONAL_RESEARCH_CONFIG)
    calculation = calculate_personal_rule(rule_input, PERSONAL_RESEARCH_CONFIG, PUBLIC_RESEARCH_CONFIG)

    assert sum(distribution.values()) == pytest.approx(100, abs=0.001)
    assert not any(item.source_code.startswith("PERSON_TIME") for item in contributions)
    assert calculation.result.precision_mode == "three_pillars"
    assert all("PERSON_MISSING_TIME" in item.basis_codes for item in calculation.result.ranking.items)


def test_element_roles_are_relative_to_day_master():
    # 金日主：土生金、金同类、金生水、金克木、火克金。
    assert element_role("土", "金") == "resource"
    assert element_role("金", "金") == "peer"
    assert element_role("水", "金") == "output"
    assert element_role("木", "金") == "wealth"
    assert element_role("火", "金") == "officer"


def test_personal_rule_rejects_wrong_version():
    rule_input = build_personal_rule_input(
        make_profile(time_known=True, birth_time="14:30"),
        date(2026, 8, 19),
        "wrong-version",
    )
    with pytest.raises(ValueError, match="个人规则输入版本"):
        calculate_personal_rule(rule_input, PERSONAL_RESEARCH_CONFIG, PUBLIC_RESEARCH_CONFIG)

