"""每日五色专业规则层的数据契约。

本文件只定义“规则需要什么”和“规则必须返回什么”，不包含尚未经过专业复核的
排序公式。后续 Agno 工作流只能接收规则层已经确定的结构化结果，不能自行修改
日期、干支、五行映射、排名或规则依据。
"""

import re
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .public_guide_schemas import COLOR_ELEMENT_MAP


HEAVENLY_STEM_ELEMENT = {
    "甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
    "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水",
}

# 当前上下文只记录地支主五行，不在这里展开藏干权重。藏干及月令权重必须在
# 专业规则评审后另行版本化，不能由模型自行补充。
EARTHLY_BRANCH_PRIMARY_ELEMENT = {
    "子": "水", "丑": "土", "寅": "木", "卯": "木", "辰": "土", "巳": "火",
    "午": "火", "未": "土", "申": "金", "酉": "金", "戌": "土", "亥": "水",
}

Element = Literal["金", "木", "水", "火", "土"]
Audience = Literal["public", "personal"]
PrecisionMode = Literal["calendar_day", "three_pillars", "four_pillars"]
# ``source_reviewed`` 表示规则已经完成公开古籍资料核对和工程化定义，但没有冒充
# 线下执业者或学术机构的“专家审核”。它可以用于内部体验版和样本验证；真正对外
# 宣称经过专家审核时，仍必须进入 ``expert_reviewed`` 并留下审核人和时间。
RuleStatus = Literal["test_only", "source_reviewed", "expert_reviewed", "active"]


class ImmutableModel(BaseModel):
    """规则输入输出生成后不可原地修改，避免缓存前后内容悄悄变化。"""

    model_config = ConfigDict(frozen=True)


class PillarContext(ImmutableModel):
    """一个干支柱及其可直接验证的主五行。"""

    text: str = Field(min_length=2, max_length=2)
    stem: str = Field(min_length=1, max_length=1)
    branch: str = Field(min_length=1, max_length=1)
    stem_element: Element
    branch_primary_element: Element

    @model_validator(mode="after")
    def validate_pillar(self):
        if self.text != self.stem + self.branch:
            raise ValueError("干支文本必须等于天干与地支拼接")
        if HEAVENLY_STEM_ELEMENT.get(self.stem) != self.stem_element:
            raise ValueError("天干与五行映射不一致")
        if EARTHLY_BRANCH_PRIMARY_ELEMENT.get(self.branch) != self.branch_primary_element:
            raise ValueError("地支与主五行映射不一致")
        return self


class DatePillars(ImmutableModel):
    """目标自然日使用的年、月、日三柱；公共日期不虚构时柱。"""

    year: PillarContext
    month: PillarContext
    day: PillarContext


class BirthPillars(DatePillars):
    """个人出生三柱或四柱；不知道出生时辰时 time 必须为空。"""

    time: PillarContext | None = None


class SolarTermPoint(ImmutableModel):
    """相邻节气及其带北京时间时区的准确时刻。"""

    name: str = Field(min_length=1, max_length=16)
    at_beijing: datetime

    @model_validator(mode="after")
    def validate_beijing_offset(self):
        if self.at_beijing.tzinfo is None or self.at_beijing.utcoffset() != timedelta(hours=8):
            raise ValueError("节气时刻必须是带 +08:00 时区的北京时间")
        return self


class DailyCalendarContext(ImmutableModel):
    """公共五色计算只允许使用的日期和历法事实。"""

    target_date: date
    timezone_id: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    time_standard: Literal["北京时间"] = "北京时间"
    weekday: str = Field(pattern=r"^星期[一二三四五六日]$")
    lunar_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    lunar_text: str = Field(min_length=1, max_length=64)
    zodiac: str = Field(min_length=1, max_length=8)
    solar_term_on_day: str | None = Field(default=None, max_length=16)
    previous_solar_term: SolarTermPoint
    next_solar_term: SolarTermPoint
    pillars: DatePillars
    calendar_version: str = Field(min_length=1, max_length=64)
    day_boundary_rule: Literal["sect2-midnight"] = "sect2-midnight"


class PublicColorRuleInput(ImmutableModel):
    """公共五色规则的完整输入，不包含用户隐私。"""

    audience: Literal["public"] = "public"
    calendar: DailyCalendarContext
    rule_version: str = Field(min_length=1, max_length=64)
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class BirthRuleContext(ImmutableModel):
    """个人规则使用的最小出生上下文。

    不携带 user_id、手机号、出生城市、性别和原始出生日期。当前规则只接收已经由
    历法服务算好的三柱/四柱、日主和档案版本，减少向后续模型暴露个人信息。
    """

    pillars: BirthPillars
    time_pillar_available: bool
    day_master_stem: str = Field(min_length=1, max_length=1)
    day_master_element: Element
    timezone_id: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    time_standard: Literal["beijing_standard_time"] = "beijing_standard_time"
    calendar_version: str = Field(min_length=1, max_length=64)
    day_boundary_rule: Literal["sect2-midnight"] = "sect2-midnight"

    @model_validator(mode="after")
    def validate_birth_context(self):
        if self.time_pillar_available != (self.pillars.time is not None):
            raise ValueError("时柱可用状态与时柱内容不一致")
        if self.day_master_stem != self.pillars.day.stem:
            raise ValueError("日主必须取出生日期柱的天干")
        if self.day_master_element != self.pillars.day.stem_element:
            raise ValueError("日主五行与日干不一致")
        return self


class PersonalColorRuleInput(ImmutableModel):
    """个人五色规则输入：当天公共上下文加本人出生上下文。"""

    audience: Literal["personal"] = "personal"
    public_context: DailyCalendarContext
    birth_context: BirthRuleContext
    profile_version: int = Field(ge=1)
    precision_mode: Literal["three_pillars", "four_pillars"]
    rule_version: str = Field(min_length=1, max_length=64)
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_precision(self):
        expected = "four_pillars" if self.birth_context.time_pillar_available else "three_pillars"
        if self.precision_mode != expected:
            raise ValueError("个人结果精度模式与出生时辰完整度不一致")
        return self


class RuleBasisDefinition(ImmutableModel):
    """一个可追溯的规则因子定义；这里只登记因子，不代表权重已获确认。"""

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    title: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=500)
    applies_to: list[Audience] = Field(min_length=1, max_length=2)
    professional_reference: str | None = Field(default=None, max_length=300)


class ProfessionalRuleDefinition(ImmutableModel):
    """整套专业规则的版本、成熟度和审核责任人。"""

    version: str = Field(min_length=1, max_length=64)
    status: RuleStatus
    time_standard: Literal["北京时间"] = "北京时间"
    algorithm_summary: str = Field(min_length=1, max_length=1000)
    factors: list[RuleBasisDefinition] = Field(min_length=1)
    reviewed_by: str | None = Field(default=None, max_length=128)
    reviewed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_review_state(self):
        codes = [factor.code for factor in self.factors]
        if len(codes) != len(set(codes)):
            raise ValueError("规则因子编号不能重复")
        if self.status in {"expert_reviewed", "active"} and (not self.reviewed_by or not self.reviewed_at):
            raise ValueError("通过专业审核或启用的规则必须记录审核人和审核时间")
        return self


class ColorRuleItem(ImmutableModel):
    """专业规则对一种颜色给出的可解释排名。

    rule_score 是当前规则版本内部使用的相对分，不直接展示给用户；它只有在专业
    公式确认后才会由规则引擎产生。basis_codes 必须能追溯到具体规则条目。
    """

    rank: int = Field(ge=1, le=5)
    color: Literal["白金", "绿金", "黑金", "红金", "黄金"]
    element: Element
    rule_score: int = Field(ge=-1000, le=1000)
    tendency: Literal["strong_support", "support", "balanced", "caution", "restrained"]
    basis_codes: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_color_item(self):
        if COLOR_ELEMENT_MAP[self.color] != self.element:
            raise ValueError(f"{self.color}必须对应五行{COLOR_ELEMENT_MAP[self.color]}")
        cleaned = [code.strip() for code in self.basis_codes if code.strip()]
        valid_format = all(re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", code) for code in cleaned)
        if cleaned != self.basis_codes or len(set(cleaned)) != len(cleaned) or not valid_format:
            raise ValueError("规则依据编号必须是无空格、不重复的大写字母数字下划线")
        return self


class ColorRanking(ImmutableModel):
    """完整五色排名；排名、颜色必须齐全，分数必须按排名非递增。"""

    items: list[ColorRuleItem] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_complete_ranking(self):
        ordered = sorted(self.items, key=lambda item: item.rank)
        if [item.rank for item in ordered] != [1, 2, 3, 4, 5]:
            raise ValueError("排名必须完整且不重复地包含1至5")
        if {item.color for item in ordered} != set(COLOR_ELEMENT_MAP):
            raise ValueError("排名必须完整包含白金、绿金、黑金、红金、黄金")
        scores = [item.rule_score for item in ordered]
        if any(left < right for left, right in zip(scores, scores[1:])):
            raise ValueError("rule_score 必须按照名次从高到低排列")
        return self


class PublicColorRuleResult(ImmutableModel):
    """公共专业规则结果；仍不包含大模型生成的展示文案。"""

    audience: Literal["public"] = "public"
    target_date: date
    rule_version: str = Field(min_length=1, max_length=64)
    rule_status: RuleStatus
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    precision_mode: Literal["calendar_day"] = "calendar_day"
    ranking: ColorRanking


class PersonalColorRuleResult(ImmutableModel):
    """个人专业规则结果；档案版本用于判断缓存是否仍有效。"""

    audience: Literal["personal"] = "personal"
    target_date: date
    profile_version: int = Field(ge=1)
    rule_version: str = Field(min_length=1, max_length=64)
    rule_status: RuleStatus
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    precision_mode: Literal["three_pillars", "four_pillars"]
    ranking: ColorRanking
