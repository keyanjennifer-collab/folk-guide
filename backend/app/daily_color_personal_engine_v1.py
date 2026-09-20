"""PERSONAL_FIVE_COLOR_V1：只计算个人五色，不计算公共五色。

公共五色由 ``public_color_snapshot`` 作为只读输入传入。本模块只负责把本命结构、
流日干支和已发布的公共排名合成个人结果，因此不会调用公共规则引擎，也不会改变
公共缓存或公共结果。
"""

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from .daily_color_personal_config import (
    PERSONAL_COLOR_ELEMENT_MAP,
    PERSONAL_PRODUCT_MAP,
    ElementRole,
    PersonalRuleConfiguration,
    StrengthRegime,
)
from .daily_color_rule_config import PublicRuleConfiguration
from .daily_color_rule_engine import ELEMENT_CONTROLS, ELEMENT_GENERATES
from .daily_color_schemas import (
    HEAVENLY_STEM_ELEMENT,
    Element,
    PersonalColorRuleInput,
    PillarContext,
    RuleStatus,
)


ELEMENTS: tuple[Element, ...] = ("金", "木", "水", "火", "土")
SeasonalState = Literal["旺", "相", "休", "囚", "死"]
RANK_TENDENCY = ("今日首选", "顺势辅助", "平衡使用", "适量使用", "今日少用")

# 成组关系只在个人层使用；公共引擎没有读取这些表。
LIUHE: dict[frozenset[str], Element] = {
    frozenset(("子", "丑")): "土", frozenset(("寅", "亥")): "木",
    frozenset(("卯", "戌")): "火", frozenset(("辰", "酉")): "金",
    frozenset(("巳", "申")): "水", frozenset(("午", "未")): "土",
}
SANHE: dict[frozenset[str], Element] = {
    frozenset(("申", "子", "辰")): "水", frozenset(("亥", "卯", "未")): "木",
    frozenset(("寅", "午", "戌")): "火", frozenset(("巳", "酉", "丑")): "金",
}
SANHUI: dict[frozenset[str], Element] = {
    frozenset(("寅", "卯", "辰")): "木", frozenset(("巳", "午", "未")): "火",
    frozenset(("申", "酉", "戌")): "金", frozenset(("亥", "子", "丑")): "水",
}
CHONG = {frozenset(pair) for pair in (("子", "午"), ("丑", "未"), ("寅", "申"), ("卯", "酉"), ("辰", "戌"), ("巳", "亥"))}
HAI = {frozenset(pair) for pair in (("子", "未"), ("丑", "午"), ("寅", "巳"), ("卯", "辰"), ("申", "亥"), ("酉", "戌"))}
PO = {frozenset(pair) for pair in (("子", "酉"), ("丑", "辰"), ("寅", "亥"), ("卯", "午"), ("巳", "申"), ("未", "戌"))}
PUNISH_GROUPS = (
    frozenset(("寅", "巳", "申")), frozenset(("丑", "未", "戌")),
    frozenset(("子", "卯")),
)
SELF_PUNISH = {"辰", "午", "酉", "亥"}


def combined_config_fingerprint(
    personal_config: PersonalRuleConfiguration,
    public_config: PublicRuleConfiguration,
) -> str:
    """将个人配置和被读取的公共版本绑定，便于缓存失效和审计。"""
    import hashlib
    import json

    payload = json.dumps(
        {"personal": personal_config.fingerprint(), "public": public_config.fingerprint()},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StructureContribution:
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
    color: str
    element: Element
    product: str
    role: ElementRole
    natal_response: float
    daily_stem: float
    daily_branch_interaction: float
    daily_element_dynamic: float
    public_score: float
    public_rank: int
    final_score: int

    @property
    def final_tendency(self) -> str:
        return RANK_TENDENCY[max(0, min(4, self.public_rank - 1))]


@dataclass(frozen=True)
class PersonalRankingItem:
    rank: int
    element: Element
    color: str
    product: str
    score: int
    public_rank: int
    rank_change: int
    tendency: str


@dataclass(frozen=True)
class PersonalRanking:
    items: tuple[PersonalRankingItem, ...]


@dataclass(frozen=True)
class PersonalColorResultV1:
    target_date: Any
    profile_version: int
    rule_version: str
    rule_status: RuleStatus
    input_fingerprint: str
    config_fingerprint: str
    precision_mode: str
    bazi: dict[str, str | None]
    public_ranking: list[dict[str, Any]]
    factors: dict[str, dict[Element, float]]
    final_scores: dict[Element, int]
    ranking: PersonalRanking


@dataclass(frozen=True)
class PersonalRuleCalculationV1:
    result: PersonalColorResultV1
    element_distribution: dict[Element, float]
    strength: DayMasterStrengthTrace
    structure_contributions: tuple[StructureContribution, ...]
    color_traces: tuple[PersonalColorCalculationTrace, ...]
    branch_events: tuple[tuple[str, str, str], ...]


def _seasonal_state(element: Element, dominant: Element) -> SeasonalState:
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
    """按月令、四柱、藏干、通根和得令关系形成稳定本命结构分布。"""
    dominant = config.month_dominant_elements[rule_input.birth_context.pillars.month.branch]
    multipliers = config.seasonal_multipliers.by_state()
    weights = config.pillar_weights.by_code()
    totals = {element: 0.0 for element in ELEMENTS}
    contributions: list[StructureContribution] = []
    for stem_code, branch_code, pillar in _pillar_sources(rule_input):
        stem_state = _seasonal_state(pillar.stem_element, dominant)
        stem_base = float(weights[stem_code])
        stem_adjusted = stem_base * multipliers[stem_state]
        totals[pillar.stem_element] += stem_adjusted
        contributions.append(StructureContribution(
            source_code=stem_code, source_kind="stem", pillar_text=pillar.text,
            stem=pillar.stem, element=pillar.stem_element, base_weight=stem_base,
            hidden_stem_share=None, seasonal_state=stem_state,
            seasonal_multiplier=multipliers[stem_state], adjusted_weight=round(stem_adjusted, 4),
        ))
        for hidden in config.hidden_stems[pillar.branch]:
            element: Element = HEAVENLY_STEM_ELEMENT[hidden.stem]  # type: ignore[assignment]
            state = _seasonal_state(element, dominant)
            base = weights[branch_code] * hidden.share / 100
            adjusted = base * multipliers[state]
            totals[element] += adjusted
            contributions.append(StructureContribution(
                source_code=branch_code, source_kind="hidden_stem", pillar_text=pillar.text,
                stem=hidden.stem, element=element, base_weight=round(base, 4),
                hidden_stem_share=hidden.share, seasonal_state=state,
                seasonal_multiplier=multipliers[state], adjusted_weight=round(adjusted, 4),
            ))
    total = sum(totals.values())
    if total <= 0:
        raise ValueError("个人五行结构总权重必须大于0")
    return ({element: round(totals[element] * 100 / total, 4) for element in ELEMENTS}, tuple(contributions))


def _resource_element(day_master: Element) -> Element:
    return next(candidate for candidate, generated in ELEMENT_GENERATES.items() if generated == day_master)


def element_role(candidate: Element, day_master: Element) -> ElementRole:
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


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _normalize(raw: Mapping[Element, float]) -> dict[Element, float]:
    values = list(raw.values())
    low, high = min(values), max(values)
    if high - low < 1e-9:
        return {element: 50.0 for element in ELEMENTS}
    return {element: round((value - low) * 100 / (high - low), 4) for element, value in raw.items()}


def _natal_response(distribution: Mapping[Element, float], day_master: Element, regime: StrengthRegime) -> dict[Element, float]:
    role_scores: dict[StrengthRegime, dict[ElementRole, float]] = {
        "weak": {"resource": 78, "peer": 70, "output": 50, "wealth": 44, "officer": 40},
        "balanced": {"resource": 60, "peer": 58, "output": 58, "wealth": 56, "officer": 55},
        "strong": {"resource": 38, "peer": 42, "output": 76, "wealth": 70, "officer": 64},
    }
    result: dict[Element, float] = {}
    for element in ELEMENTS:
        balance = 100 - abs(distribution[element] - 20.0) * 3.5
        role = element_role(element, day_master)
        result[element] = _clamp(balance * 0.68 + role_scores[regime][role] * 0.32)
    return result


def _daily_stem_scores(stem_element: Element, day_master: Element, regime: StrengthRegime) -> dict[Element, float]:
    raw = {element: 50.0 for element in ELEMENTS}
    raw[stem_element] += 28
    raw[ELEMENT_GENERATES[stem_element]] += 12
    raw[ELEMENT_CONTROLS[stem_element]] -= 8
    raw[_resource_element(stem_element)] += 5
    role = element_role(stem_element, day_master)
    regime_adjust = {"weak": {"resource": 9, "peer": 6, "output": -4, "wealth": -3, "officer": -6},
                     "balanced": {"resource": 2, "peer": 1, "output": 1, "wealth": 0, "officer": 0},
                     "strong": {"resource": -6, "peer": -4, "output": 8, "wealth": 6, "officer": 4}}[regime]
    raw[stem_element] += regime_adjust[role]
    return _normalize({element: _clamp(value) for element, value in raw.items()})


def _branch_events(today: str, birth_branches: Sequence[str]) -> tuple[tuple[str, str, str], ...]:
    events: set[tuple[str, str, str]] = set()
    for branch in birth_branches:
        pair = frozenset((today, branch))
        if pair in LIUHE:
            events.add(("六合", branch, LIUHE[pair]))
        if pair in CHONG:
            events.add(("相冲", branch, ""))
        if pair in HAI:
            events.add(("相害", branch, ""))
        if pair in PO:
            events.add(("相破", branch, ""))
        if today == branch and today in SELF_PUNISH:
            events.add(("自刑", branch, ""))
        if any(today in group and branch in group for group in PUNISH_GROUPS):
            events.add(("相刑", branch, ""))
    branch_set = set(birth_branches) | {today}
    for group, element in (*SANHE.items(), *SANHUI.items()):
        if today in group and len(branch_set.intersection(group)) >= 3:
            events.add(("三合" if group in SANHE else "三会", "、".join(sorted(group)), element))
    return tuple(sorted(events))


def _branch_interaction_scores(
    today_branch: str,
    birth_branches: Sequence[str],
    distribution: Mapping[Element, float],
) -> tuple[dict[Element, float], tuple[tuple[str, str, str], ...]]:
    raw = {element: 50.0 + (20.0 - distribution[element]) * 0.65 for element in ELEMENTS}
    events = _branch_events(today_branch, birth_branches)
    for relation, counterpart, relation_element in events:
        if relation in {"六合", "三合", "三会"} and relation_element:
            pressure = 1.0 if distribution[relation_element] <= 20 else -0.55
            raw[relation_element] += 18 * pressure
        else:
            involved = [today_branch] + [part for part in counterpart if part in "子丑寅卯辰巳午未申酉戌亥"]
            for branch in involved:
                element: Element = {"子": "水", "丑": "土", "寅": "木", "卯": "木", "辰": "土", "巳": "火", "午": "火", "未": "土", "申": "金", "酉": "金", "戌": "土", "亥": "水"}[branch]  # type: ignore[assignment]
                raw[element] -= 8 + distribution[element] * 0.10
                raw[_resource_element(element)] += 3
    return _normalize({element: _clamp(value) for element, value in raw.items()}), events


def _daily_dynamic_scores(
    stem_element: Element,
    branch_element: Element,
    distribution: Mapping[Element, float],
    day_master: Element,
) -> dict[Element, float]:
    raw = {element: 50.0 for element in ELEMENTS}
    raw[stem_element] += 17
    raw[branch_element] += 17
    if stem_element == branch_element:
        raw[stem_element] += 8
    elif ELEMENT_GENERATES[stem_element] == branch_element:
        raw[branch_element] += 10
        raw[stem_element] -= 3
    elif ELEMENT_CONTROLS[stem_element] == branch_element:
        raw[branch_element] -= 8
        raw[ELEMENT_GENERATES[branch_element]] += 4
    else:
        raw[ELEMENT_GENERATES[stem_element]] += 4
    for element in ELEMENTS:
        if element in {stem_element, branch_element}:
            raw[element] += (20.0 - distribution[element]) * 0.45
        if element == day_master:
            raw[element] += 2
    return _normalize({element: _clamp(value) for element, value in raw.items()})


def _public_snapshot_scores(public_ranking: Sequence[Mapping[str, Any] | str]) -> tuple[dict[Element, float], list[dict[str, Any]]]:
    """将已缓存的公共五色排名转换为固定 100/80/60/40/20 分。"""
    old_colors = {"白金": "金", "绿金": "木", "黑金": "水", "红金": "火", "黄金": "土"}
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(public_ranking):
        if isinstance(row, str):
            color = row
            element = PERSONAL_COLOR_ELEMENT_MAP.get(color, old_colors.get(color))
            rank = index + 1
        else:
            color = str(row.get("color") or "")
            element = str(row.get("element") or PERSONAL_COLOR_ELEMENT_MAP.get(color) or old_colors.get(color) or "")
            rank = int(row.get("rank") or index + 1)
        if element not in ELEMENTS:
            raise ValueError("公共五色快照缺少有效五行")
        rows.append({
            "rank": rank,
            "element": element,
            "color": next(color_name for color_name, value in PERSONAL_COLOR_ELEMENT_MAP.items() if value == element),
            "product": PERSONAL_PRODUCT_MAP[element],
            "score": 100 - (rank - 1) * 20,
        })
    rows.sort(key=lambda item: item["rank"])
    if [row["rank"] for row in rows] != [1, 2, 3, 4, 5] or {row["element"] for row in rows} != set(ELEMENTS):
        raise ValueError("公共五色快照必须完整包含五种五行及1至5名")
    return ({row["element"]: float(row["score"]) for row in rows}, rows)


def calculate_personal_rule_v1(
    rule_input: PersonalColorRuleInput,
    personal_config: PersonalRuleConfiguration,
    public_config: PublicRuleConfiguration,
    *,
    public_ranking: Sequence[Mapping[str, Any] | str],
) -> PersonalRuleCalculationV1:
    """执行个人五项因子公式；公共结果只能作为只读快照传入。"""
    if rule_input.rule_version != personal_config.version:
        raise ValueError("个人规则输入版本与个人配置版本不一致")
    if personal_config.public_rule_version != public_config.version:
        raise ValueError("个人配置引用的公共规则版本与实际公共配置不一致")
    distribution, contributions = calculate_birth_structure(rule_input, personal_config)
    day_master = rule_input.birth_context.day_master_element
    resource = _resource_element(day_master)
    support_ratio = distribution[day_master] + distribution[resource]
    regime = personal_config.strength_thresholds.classify(support_ratio)
    strength = DayMasterStrengthTrace(
        day_master_stem=rule_input.birth_context.day_master_stem,
        day_master_element=day_master,
        resource_element=resource,
        peer_percent=distribution[day_master], resource_percent=distribution[resource],
        support_ratio=round(support_ratio, 4), regime=regime,
        weak_max=personal_config.strength_thresholds.weak_max,
        strong_min=personal_config.strength_thresholds.strong_min,
    )
    public_scores, public_rows = _public_snapshot_scores(public_ranking)
    stem_element = HEAVENLY_STEM_ELEMENT[rule_input.public_context.pillars.day.stem]
    branch = rule_input.public_context.pillars.day.branch
    branch_element = rule_input.public_context.pillars.day.branch_primary_element
    birth_branches = [pillar.branch for _, _, pillar in _pillar_sources(rule_input)]
    natal = _natal_response(distribution, day_master, regime)
    daily_stem = _daily_stem_scores(stem_element, day_master, regime)
    daily_branch, branch_events = _branch_interaction_scores(branch, birth_branches, distribution)
    daily_dynamic = _daily_dynamic_scores(stem_element, branch_element, distribution, day_master)
    factors = {
        "natalResponse": natal,
        "dailyStem": daily_stem,
        "dailyBranchInteraction": daily_branch,
        "dailyElementDynamic": daily_dynamic,
        "publicScore": public_scores,
    }
    weights = (
        ("natalResponse", personal_config.natal_response_weight),
        ("dailyStem", personal_config.daily_stem_weight),
        ("dailyBranchInteraction", personal_config.daily_branch_interaction_weight),
        ("dailyElementDynamic", personal_config.daily_element_dynamic_weight),
        ("publicScore", personal_config.public_score_weight),
    )
    public_rank = {row["element"]: row["rank"] for row in public_rows}
    traces: list[PersonalColorCalculationTrace] = []
    for element in ELEMENTS:
        score = round(sum(factors[name][element] * weight for name, weight in weights) / 100)
        color = next(color_name for color_name, value in PERSONAL_COLOR_ELEMENT_MAP.items() if value == element)
        traces.append(PersonalColorCalculationTrace(
            color=color, element=element, product=PERSONAL_PRODUCT_MAP[element], role=element_role(element, day_master),
            natal_response=natal[element], daily_stem=daily_stem[element],
            daily_branch_interaction=daily_branch[element], daily_element_dynamic=daily_dynamic[element],
            public_score=public_scores[element], public_rank=public_rank[element], final_score=score,
        ))
    tie_index = {color: index for index, color in enumerate(personal_config.tie_break_color_order)}
    traces.sort(key=lambda trace: (-trace.final_score, tie_index[trace.color]))
    ranking = PersonalRanking(items=tuple(
        PersonalRankingItem(
            rank=index,
            element=trace.element,
            color=trace.color,
            product=trace.product,
            score=trace.final_score,
            public_rank=trace.public_rank,
            rank_change=trace.public_rank - index,
            tendency=RANK_TENDENCY[index - 1],
        ) for index, trace in enumerate(traces, start=1)
    ))
    result = PersonalColorResultV1(
        target_date=rule_input.public_context.target_date,
        profile_version=rule_input.profile_version,
        rule_version=personal_config.version,
        rule_status=personal_config.status,
        input_fingerprint=rule_input.input_fingerprint,
        config_fingerprint=personal_config.fingerprint(),
        precision_mode=rule_input.precision_mode,
        bazi={
            "yearPillar": rule_input.birth_context.pillars.year.text,
            "monthPillar": rule_input.birth_context.pillars.month.text,
            "dayPillar": rule_input.birth_context.pillars.day.text,
            "hourPillar": rule_input.birth_context.pillars.time.text if rule_input.birth_context.pillars.time else None,
            "dayMaster": rule_input.birth_context.day_master_stem,
        },
        public_ranking=public_rows,
        factors=factors,
        final_scores={item.element: item.score for item in ranking.items},
        ranking=ranking,
    )
    return PersonalRuleCalculationV1(
        result=result, element_distribution=distribution, strength=strength,
        structure_contributions=contributions, color_traces=tuple(traces), branch_events=branch_events,
    )


# 公开入口名保持稳定，调用方必须提供已缓存的公共排名快照。
calculate_personal_rule = calculate_personal_rule_v1
