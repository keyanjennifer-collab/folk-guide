"""个人五色资料综合版评分引擎。

引擎只执行配置，不在运行时向大模型询问五行、藏干或权重。这样同一档案版本、
同一日期和同一规则版本永远得到同一结果，适合提前缓存三天，也便于后台审计。
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from .daily_color_context import build_public_rule_input_from_context
from .daily_color_personal_config import ElementRole, PersonalRuleConfiguration, StrengthRegime
from .daily_color_rule_config import PublicRuleConfiguration
from .daily_color_rule_engine import (
    ELEMENT_CONTROLS,
    ELEMENT_GENERATES,
    PublicRuleCalculation,
    calculate_public_rule,
)
from .daily_color_schemas import (
    HEAVENLY_STEM_ELEMENT,
    ColorRanking,
    ColorRuleItem,
    Element,
    PersonalColorRuleInput,
    PersonalColorRuleResult,
    PillarContext,
    RuleStatus,
)
from .public_guide_schemas import COLOR_ELEMENT_MAP


SeasonalState = Literal["旺", "相", "休", "囚", "死"]


@dataclass(frozen=True)
class StructureContribution:
    """出生结构中一个天干或一个地支藏干的逐项贡献。"""

    source_code: str
    source_kind: Literal["stem", "hidden_stem"]
    pillar_text: str
    stem: str
    element: Element
    base_weight: float
    hidden_stem_share: int | None
    seasonal_state: SeasonalState
    seasonal_multiplier: float
    adjusted_weight: float


@dataclass(frozen=True)
class DayMasterStrengthTrace:
    """日主强弱的最小可解释摘要。"""

    day_master_stem: str
    day_master_element: Element
    resource_element: Element
    peer_percent: float
    resource_percent: float
    support_ratio: float
    regime: StrengthRegime
    weak_max: float
    strong_min: float


@dataclass(frozen=True)
class PersonalColorCalculationTrace:
    """一种颜色从出生结构到当天融合分的完整计算记录。"""

    color: str
    element: Element
    role: ElementRole
    structure_percent: float
    role_score: int
    deficiency_adjustment: float
    birth_need_score: float
    public_environment_score: int
    final_score: int


@dataclass(frozen=True)
class PersonalRuleCalculation:
    """个人规则结果与仅供后台、测试使用的审计明细。"""

    result: PersonalColorRuleResult
    element_distribution: dict[Element, float]
    strength: DayMasterStrengthTrace
    structure_contributions: tuple[StructureContribution, ...]
    color_traces: tuple[PersonalColorCalculationTrace, ...]
    public_calculation: PublicRuleCalculation


def _seasonal_state(element: Element, dominant: Element) -> SeasonalState:
    """按《五行大义》四时关系把五行归入旺、相、休、囚、死。

    例如春木旺：木旺、木所生之火相、生木之水休、克木之金囚、木所克之土死。
    土月也用同一关系展开，避免为十二个月硬编码五套重复表格。
    """
    if element == dominant:
        return "旺"
    if ELEMENT_GENERATES[dominant] == element:
        return "相"
    if ELEMENT_GENERATES[element] == dominant:
        return "休"
    if ELEMENT_CONTROLS[element] == dominant:
        return "囚"
    if ELEMENT_CONTROLS[dominant] == element:
        return "死"
    raise ValueError(f"无法判断{dominant}月中的{element}旺衰状态")


def _pillar_sources(rule_input: PersonalColorRuleInput) -> list[tuple[str, str, PillarContext]]:
    """把三柱/四柱转换成稳定顺序的干支来源列表。"""
    pillars = rule_input.birth_context.pillars
    sources = [
        ("PERSON_YEAR_STEM", "PERSON_YEAR_BRANCH", pillars.year),
        ("PERSON_MONTH_STEM", "PERSON_MONTH_BRANCH", pillars.month),
        ("PERSON_DAY_STEM", "PERSON_DAY_BRANCH", pillars.day),
    ]
    if pillars.time is not None:
        sources.append(("PERSON_TIME_STEM", "PERSON_TIME_BRANCH", pillars.time))
    return sources


def calculate_birth_structure(
    rule_input: PersonalColorRuleInput,
    config: PersonalRuleConfiguration,
) -> tuple[dict[Element, float], tuple[StructureContribution, ...]]:
    """展开天干与地支藏干，应用月令倍率并归一化为五行百分比。"""
    month_branch = rule_input.birth_context.pillars.month.branch
    dominant = config.month_dominant_elements[month_branch]
    multipliers = config.seasonal_multipliers.by_state()
    weights = config.pillar_weights.by_code()
    totals: dict[Element, float] = {"金": 0.0, "木": 0.0, "水": 0.0, "火": 0.0, "土": 0.0}
    contributions: list[StructureContribution] = []

    for stem_code, branch_code, pillar in _pillar_sources(rule_input):
        # 天干直接使用其固定五行。
        stem_element = pillar.stem_element
        stem_state = _seasonal_state(stem_element, dominant)
        stem_base = float(weights[stem_code])
        stem_adjusted = stem_base * multipliers[stem_state]
        totals[stem_element] += stem_adjusted
        contributions.append(StructureContribution(
            source_code=stem_code,
            source_kind="stem",
            pillar_text=pillar.text,
            stem=pillar.stem,
            element=stem_element,
            base_weight=stem_base,
            hidden_stem_share=None,
            seasonal_state=stem_state,
            seasonal_multiplier=multipliers[stem_state],
            adjusted_weight=round(stem_adjusted, 4),
        ))

        # 地支按版本化藏干比例拆开。这里不再额外叠加“地支主五行”，避免重复计分。
        for hidden in config.hidden_stems[pillar.branch]:
            hidden_element: Element = HEAVENLY_STEM_ELEMENT[hidden.stem]  # type: ignore[assignment]
            hidden_state = _seasonal_state(hidden_element, dominant)
            hidden_base = weights[branch_code] * hidden.share / 100
            hidden_adjusted = hidden_base * multipliers[hidden_state]
            totals[hidden_element] += hidden_adjusted
            contributions.append(StructureContribution(
                source_code=branch_code,
                source_kind="hidden_stem",
                pillar_text=pillar.text,
                stem=hidden.stem,
                element=hidden_element,
                base_weight=round(hidden_base, 4),
                hidden_stem_share=hidden.share,
                seasonal_state=hidden_state,
                seasonal_multiplier=multipliers[hidden_state],
                adjusted_weight=round(hidden_adjusted, 4),
            ))

    adjusted_total = sum(totals.values())
    if adjusted_total <= 0:
        raise ValueError("个人五行结构总权重必须大于0")
    distribution = {
        element: round(value * 100 / adjusted_total, 4)
        for element, value in totals.items()
    }
    return distribution, tuple(contributions)


def _resource_element(day_master: Element) -> Element:
    """找出“生我”的五行。"""
    for candidate, generated in ELEMENT_GENERATES.items():
        if generated == day_master:
            return candidate
    raise ValueError(f"无法找到{day_master}的生我五行")


def element_role(candidate: Element, day_master: Element) -> ElementRole:
    """判断候选五行相对于个人日主的角色。"""
    if candidate == day_master:
        return "peer"
    if ELEMENT_GENERATES[candidate] == day_master:
        return "resource"
    if ELEMENT_GENERATES[day_master] == candidate:
        return "output"
    if ELEMENT_CONTROLS[day_master] == candidate:
        return "wealth"
    if ELEMENT_CONTROLS[candidate] == day_master:
        return "officer"
    raise ValueError(f"无法判断{candidate}相对于日主{day_master}的角色")


def combined_config_fingerprint(
    personal_config: PersonalRuleConfiguration,
    public_config: PublicRuleConfiguration,
) -> str:
    """把公共、个人两份配置指纹合成最终指纹。"""
    payload = json.dumps(
        {
            "personal": personal_config.fingerprint(),
            "public": public_config.fingerprint(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _combined_status(personal: RuleStatus, public: RuleStatus) -> RuleStatus:
    """组合链路以成熟度较低的一端作为最终状态。"""
    order: list[RuleStatus] = ["test_only", "source_reviewed", "expert_reviewed", "active"]
    return order[min(order.index(personal), order.index(public))]


def calculate_personal_rule(
    rule_input: PersonalColorRuleInput,
    personal_config: PersonalRuleConfiguration,
    public_config: PublicRuleConfiguration,
) -> PersonalRuleCalculation:
    """计算个人五色排名，并保留出生结构与当天环境的全部审计数据。"""
    if rule_input.rule_version != personal_config.version:
        raise ValueError("个人规则输入版本与个人配置版本不一致")
    if personal_config.public_rule_version != public_config.version:
        raise ValueError("个人配置引用的公共规则版本与实际公共配置不一致")

    distribution, structure_contributions = calculate_birth_structure(rule_input, personal_config)
    day_master = rule_input.birth_context.day_master_element
    resource = _resource_element(day_master)
    support_ratio = distribution[day_master] + distribution[resource]
    regime = personal_config.strength_thresholds.classify(support_ratio)
    strength = DayMasterStrengthTrace(
        day_master_stem=rule_input.birth_context.day_master_stem,
        day_master_element=day_master,
        resource_element=resource,
        peer_percent=distribution[day_master],
        resource_percent=distribution[resource],
        support_ratio=round(support_ratio, 4),
        regime=regime,
        weak_max=personal_config.strength_thresholds.weak_max,
        strong_min=personal_config.strength_thresholds.strong_min,
    )

    # 个人结果中的公共环境必须复用同一个日期上下文，只把规则版本切换为公共版本。
    public_input = build_public_rule_input_from_context(rule_input.public_context, public_config.version)
    public_calculation = calculate_public_rule(public_input, public_config)
    public_scores = {
        item.element: item.rule_score
        for item in public_calculation.result.ranking.items
    }
    tie_index = {color: index for index, color in enumerate(personal_config.tie_break_color_order)}
    traces: list[PersonalColorCalculationTrace] = []

    for color, element in COLOR_ELEMENT_MAP.items():
        role = element_role(element, day_master)
        role_score = personal_config.strategy_scores.for_regime(regime).for_role(role)
        raw_adjustment = (
            personal_config.balance_target_percent - distribution[element]
        ) * personal_config.deficiency_weight
        limit = personal_config.deficiency_adjustment_limit
        deficiency_adjustment = max(-limit, min(limit, raw_adjustment))
        birth_need_score = role_score + deficiency_adjustment
        final_score = round(
            birth_need_score * personal_config.birth_structure_weight / 100
            + public_scores[element] * personal_config.public_environment_weight / 100
        )
        traces.append(PersonalColorCalculationTrace(
            color=color,
            element=element,
            role=role,
            structure_percent=distribution[element],
            role_score=role_score,
            deficiency_adjustment=round(deficiency_adjustment, 4),
            birth_need_score=round(birth_need_score, 4),
            public_environment_score=public_scores[element],
            final_score=final_score,
        ))

    ordered = sorted(traces, key=lambda trace: (-trace.final_score, tie_index[trace.color]))
    role_basis = {
        "resource": "PERSON_ROLE_RESOURCE",
        "peer": "PERSON_ROLE_PEER",
        "output": "PERSON_ROLE_OUTPUT",
        "wealth": "PERSON_ROLE_WEALTH",
        "officer": "PERSON_ROLE_OFFICER",
    }
    items: list[ColorRuleItem] = []
    for rank, trace in enumerate(ordered, start=1):
        basis_codes = [
            "PERSON_DAY_MASTER",
            "PERSON_PILLAR_BALANCE",
            role_basis[trace.role],
            "PERSON_TODAY_RELATION",
        ]
        if rule_input.precision_mode == "three_pillars":
            basis_codes.append("PERSON_MISSING_TIME")
        items.append(ColorRuleItem(
            rank=rank,
            color=trace.color,  # type: ignore[arg-type]
            element=trace.element,
            rule_score=trace.final_score,
            tendency=personal_config.tendency_thresholds.classify(trace.final_score),  # type: ignore[arg-type]
            basis_codes=basis_codes,
        ))

    result = PersonalColorRuleResult(
        target_date=rule_input.public_context.target_date,
        profile_version=rule_input.profile_version,
        rule_version=personal_config.version,
        rule_status=_combined_status(personal_config.status, public_config.status),
        input_fingerprint=rule_input.input_fingerprint,
        config_fingerprint=combined_config_fingerprint(personal_config, public_config),
        precision_mode=rule_input.precision_mode,
        ranking=ColorRanking(items=items),
    )
    return PersonalRuleCalculation(
        result=result,
        element_distribution=distribution,
        strength=strength,
        structure_contributions=structure_contributions,
        color_traces=tuple(ordered),
        public_calculation=public_calculation,
    )
