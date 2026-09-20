"""兼容入口：个人五色统一使用 ``PERSONAL_FIVE_COLOR_V1``。"""

from .daily_color_personal_engine_v1 import (  # noqa: F401
    DayMasterStrengthTrace,
    PersonalColorCalculationTrace,
    PersonalColorResultV1,
    PersonalRanking,
    PersonalRankingItem,
    PersonalRuleCalculationV1,
    StructureContribution,
    calculate_birth_structure,
    calculate_personal_rule_v1,
    combined_config_fingerprint,
    element_role,
)

calculate_personal_rule = calculate_personal_rule_v1
PersonalRuleCalculation = PersonalRuleCalculationV1
