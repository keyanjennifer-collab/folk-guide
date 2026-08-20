"""由专业配置驱动的公共五色评分执行骨架。

本引擎没有内置权重。只有调用方显式传入通过 Pydantic 完整校验的配置后才会
计算；test_only 配置的结果仍标记为 test_only，不能在后续流程中冒充正式内容。
"""

from dataclasses import dataclass

from .daily_color_rule_config import PublicRuleConfiguration
from .daily_color_schemas import ColorRanking, ColorRuleItem, Element, PublicColorRuleInput, PublicColorRuleResult
from .public_guide_schemas import COLOR_ELEMENT_MAP


ELEMENT_GENERATES: dict[Element, Element] = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
ELEMENT_CONTROLS: dict[Element, Element] = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}


@dataclass(frozen=True)
class FactorContribution:
    """一个候选颜色在一个规则因子上的计算明细。"""

    factor_code: str
    reference_element: Element
    relation_code: str
    relation_score: int
    factor_weight: int
    weighted_score: float


@dataclass(frozen=True)
class ColorCalculationTrace:
    """一种颜色的完整内部计算明细，仅供测试和后台审核。"""

    color: str
    element: Element
    final_score: int
    contributions: tuple[FactorContribution, ...]


@dataclass(frozen=True)
class PublicRuleCalculation:
    """公开规则结果和不向普通用户展示的审计明细。"""

    result: PublicColorRuleResult
    traces: tuple[ColorCalculationTrace, ...]


def element_relation(candidate: Element, reference: Element) -> str:
    """判断候选颜色五行相对于参考五行的唯一关系。"""
    if candidate == reference:
        return "SAME_ELEMENT"
    if ELEMENT_GENERATES[candidate] == reference:
        return "CANDIDATE_GENERATES_REFERENCE"
    if ELEMENT_GENERATES[reference] == candidate:
        return "REFERENCE_GENERATES_CANDIDATE"
    if ELEMENT_CONTROLS[candidate] == reference:
        return "CANDIDATE_CONTROLS_REFERENCE"
    if ELEMENT_CONTROLS[reference] == candidate:
        return "REFERENCE_CONTROLS_CANDIDATE"
    raise ValueError(f"无法判断五行关系：{candidate} -> {reference}")


def _reference_elements(rule_input: PublicColorRuleInput, config: PublicRuleConfiguration) -> dict[str, Element]:
    calendar = rule_input.calendar
    current_term = calendar.solar_term_on_day or calendar.previous_solar_term.name
    return {
        "PUBLIC_YEAR_STEM": calendar.pillars.year.stem_element,
        "PUBLIC_YEAR_BRANCH": calendar.pillars.year.branch_primary_element,
        "PUBLIC_MONTH_STEM": calendar.pillars.month.stem_element,
        "PUBLIC_MONTH_BRANCH": calendar.pillars.month.branch_primary_element,
        "PUBLIC_DAY_STEM": calendar.pillars.day.stem_element,
        "PUBLIC_DAY_BRANCH": calendar.pillars.day.branch_primary_element,
        "PUBLIC_SOLAR_TERM": config.solar_term_elements[current_term],
    }


def calculate_public_rule(
    rule_input: PublicColorRuleInput,
    config: PublicRuleConfiguration,
) -> PublicRuleCalculation:
    """按配置计算公共五色完整排名，并返回逐因子审计明细。"""
    if rule_input.rule_version != config.version:
        raise ValueError("规则输入版本与配置版本不一致")

    weights = config.factor_weights.by_code()
    relation_scores = config.relation_scores.by_code()
    references = _reference_elements(rule_input, config)
    tie_index = {color: index for index, color in enumerate(config.tie_break_color_order)}
    traces: list[ColorCalculationTrace] = []

    for color, element in COLOR_ELEMENT_MAP.items():
        contributions: list[FactorContribution] = []
        total = 0.0
        for factor_code, reference_element in references.items():
            weight = weights[factor_code]
            relation_code = element_relation(element, reference_element)
            relation_score = relation_scores[relation_code]
            weighted = relation_score * weight / 100
            total += weighted
            if weight:
                contributions.append(FactorContribution(
                    factor_code=factor_code,
                    reference_element=reference_element,
                    relation_code=relation_code,
                    relation_score=relation_score,
                    factor_weight=weight,
                    weighted_score=weighted,
                ))
        traces.append(ColorCalculationTrace(
            color=color,
            element=element,
            final_score=round(total),
            contributions=tuple(contributions),
        ))

    ordered = sorted(traces, key=lambda trace: (-trace.final_score, tie_index[trace.color]))
    items = [ColorRuleItem(
        rank=index,
        color=trace.color,
        element=trace.element,
        rule_score=trace.final_score,
        tendency=config.tendency_thresholds.classify(trace.final_score),
        basis_codes=[item.factor_code for item in trace.contributions],
    ) for index, trace in enumerate(ordered, start=1)]

    result = PublicColorRuleResult(
        target_date=rule_input.calendar.target_date,
        rule_version=config.version,
        rule_status=config.status,
        input_fingerprint=rule_input.input_fingerprint,
        config_fingerprint=config.fingerprint(),
        ranking=ColorRanking(items=items),
    )
    return PublicRuleCalculation(result=result, traces=tuple(ordered))

