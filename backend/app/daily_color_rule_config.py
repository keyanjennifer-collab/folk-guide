"""公共五色规则配置契约。

代码规定配置必须完整、可审核、可复现。配置既可以来自人工填写的 Excel，也可以
来自代码内版本化的资料综合版；无论来源如何，都必须明确状态和参数性质。
"""

import hashlib
import json
from datetime import date, datetime

from pydantic import Field, model_validator

from .daily_color_schemas import Element, ImmutableModel, RuleStatus
from .public_guide_schemas import COLOR_ELEMENT_MAP


SOLAR_TERMS = (
    "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
    "立夏", "小满", "芒种", "夏至", "小暑", "大暑",
    "立秋", "处暑", "白露", "秋分", "寒露", "霜降",
    "立冬", "小雪", "大雪", "冬至", "小寒", "大寒",
)

PUBLIC_FACTOR_CODE_TO_FIELD = {
    "PUBLIC_YEAR_STEM": "year_stem",
    "PUBLIC_YEAR_BRANCH": "year_branch",
    "PUBLIC_MONTH_STEM": "month_stem",
    "PUBLIC_MONTH_BRANCH": "month_branch",
    "PUBLIC_DAY_STEM": "day_stem",
    "PUBLIC_DAY_BRANCH": "day_branch",
    "PUBLIC_SOLAR_TERM": "solar_term",
}

RELATION_CODE_TO_FIELD = {
    "SAME_ELEMENT": "same_element",
    "CANDIDATE_GENERATES_REFERENCE": "candidate_generates_reference",
    "REFERENCE_GENERATES_CANDIDATE": "reference_generates_candidate",
    "CANDIDATE_CONTROLS_REFERENCE": "candidate_controls_reference",
    "REFERENCE_CONTROLS_CANDIDATE": "reference_controls_candidate",
}


class PublicFactorWeights(ImmutableModel):
    """年、月、日干支和节气七类因素的百分制权重。"""

    year_stem: int = Field(ge=0, le=100)
    year_branch: int = Field(ge=0, le=100)
    month_stem: int = Field(ge=0, le=100)
    month_branch: int = Field(ge=0, le=100)
    day_stem: int = Field(ge=0, le=100)
    day_branch: int = Field(ge=0, le=100)
    solar_term: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_total(self):
        if sum(self.model_dump().values()) != 100:
            raise ValueError("公共因子权重合计必须等于100")
        if self.day_stem + self.day_branch == 0:
            raise ValueError("日干和日支权重不能同时为0")
        return self

    def by_code(self) -> dict[str, int]:
        """转换为规则依据编号到权重的映射。"""
        return {code: getattr(self, field) for code, field in PUBLIC_FACTOR_CODE_TO_FIELD.items()}


class ElementRelationScores(ImmutableModel):
    """候选颜色五行与某个参考五行之间五种关系的基础分。"""

    same_element: int = Field(ge=-1000, le=1000)
    candidate_generates_reference: int = Field(ge=-1000, le=1000)
    reference_generates_candidate: int = Field(ge=-1000, le=1000)
    candidate_controls_reference: int = Field(ge=-1000, le=1000)
    reference_controls_candidate: int = Field(ge=-1000, le=1000)

    def by_code(self) -> dict[str, int]:
        """转换为五行关系编号到基础分的映射。"""
        return {code: getattr(self, field) for code, field in RELATION_CODE_TO_FIELD.items()}


class TendencyThresholds(ImmutableModel):
    """规则分数转换成五档内部趋势的下限。"""

    strong_support_min: int = Field(ge=-1000, le=1000)
    support_min: int = Field(ge=-1000, le=1000)
    balanced_min: int = Field(ge=-1000, le=1000)
    caution_min: int = Field(ge=-1000, le=1000)

    @model_validator(mode="after")
    def validate_descending(self):
        values = [self.strong_support_min, self.support_min, self.balanced_min, self.caution_min]
        if not all(left > right for left, right in zip(values, values[1:])):
            raise ValueError("趋势阈值必须严格从高到低")
        return self

    def classify(self, score: int) -> str:
        if score >= self.strong_support_min:
            return "strong_support"
        if score >= self.support_min:
            return "support"
        if score >= self.balanced_min:
            return "balanced"
        if score >= self.caution_min:
            return "caution"
        return "restrained"


class PublicRuleConfiguration(ImmutableModel):
    """一份可以驱动公共五色评分的完整版本化配置。"""

    version: str = Field(min_length=1, max_length=64)
    status: RuleStatus = "test_only"
    effective_from: date | None = None
    algorithm_summary: str = Field(min_length=1, max_length=1000)
    factor_weights: PublicFactorWeights
    relation_scores: ElementRelationScores
    solar_term_elements: dict[str, Element]
    tie_break_color_order: list[str] = Field(min_length=5, max_length=5)
    tendency_thresholds: TendencyThresholds
    professional_references: list[str] = Field(default_factory=list, max_length=20)
    approved_test_case_count: int = Field(default=0, ge=0)
    reviewed_by: str | None = Field(default=None, max_length=128)
    reviewed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_configuration(self):
        if set(self.solar_term_elements) != set(SOLAR_TERMS):
            raise ValueError("节气五行映射必须完整包含二十四节气且不能有额外名称")
        if set(self.tie_break_color_order) != set(COLOR_ELEMENT_MAP):
            raise ValueError("同分顺序必须完整且不重复地包含五种颜色")
        if self.status in {"expert_reviewed", "active"}:
            if not self.reviewed_by or not self.reviewed_at:
                raise ValueError("专业审核后的规则必须记录审核人和审核时间")
            if self.approved_test_case_count < 10:
                raise ValueError("专业审核后的规则至少需要10个已确认测试案例")
            if not self.professional_references:
                raise ValueError("专业审核后的规则必须填写专业依据说明")
        if self.status == "active" and self.effective_from is None:
            raise ValueError("启用规则必须填写生效日期")
        return self

    def fingerprint(self) -> str:
        """配置内容指纹；相同版本号但内容变化时也能被发现。"""
        payload = json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
