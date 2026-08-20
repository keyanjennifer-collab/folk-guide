"""个人五色“资料综合版”配置契约。

古籍提供的是五行、月令、旺衰、扶抑和中和等判断原则，并不存在一张可直接复制
到小程序里的“颜色百分制公式”。因此本模块把两类内容明确分开：

1. 可追溯原则：五行生克、以日主为中心、重视月令、强则泄耗克、弱则生扶；
2. 工程参数：柱权重、藏干比例、旺衰倍率、强弱阈值和公共/个人融合比例。

工程参数都进入版本化配置和内容指纹，日后调整时不会悄悄改变历史结果。
"""

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from .daily_color_rule_config import TendencyThresholds
from .daily_color_schemas import (
    EARTHLY_BRANCH_PRIMARY_ELEMENT,
    HEAVENLY_STEM_ELEMENT,
    Element,
    ImmutableModel,
    RuleStatus,
)
from .public_guide_schemas import COLOR_ELEMENT_MAP


StrengthRegime = Literal["weak", "balanced", "strong"]
ElementRole = Literal["resource", "peer", "output", "wealth", "officer"]


PERSONAL_PILLAR_CODE_TO_FIELD = {
    "PERSON_YEAR_STEM": "year_stem",
    "PERSON_YEAR_BRANCH": "year_branch",
    "PERSON_MONTH_STEM": "month_stem",
    "PERSON_MONTH_BRANCH": "month_branch",
    "PERSON_DAY_STEM": "day_stem",
    "PERSON_DAY_BRANCH": "day_branch",
    "PERSON_TIME_STEM": "time_stem",
    "PERSON_TIME_BRANCH": "time_branch",
}


class PersonalPillarWeights(ImmutableModel):
    """四柱各位置的结构权重，总计固定为100。

    未知时辰时，引擎会删除时干、时支并把其余六项重新归一化，绝不补造时柱。
    月支用于表达月令，通常应当是权重最高的单项。
    """

    year_stem: int = Field(ge=0, le=100)
    year_branch: int = Field(ge=0, le=100)
    month_stem: int = Field(ge=0, le=100)
    month_branch: int = Field(ge=0, le=100)
    day_stem: int = Field(ge=0, le=100)
    day_branch: int = Field(ge=0, le=100)
    time_stem: int = Field(ge=0, le=100)
    time_branch: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_weights(self):
        values = self.model_dump()
        if sum(values.values()) != 100:
            raise ValueError("个人柱权重合计必须等于100")
        if self.month_branch != max(values.values()):
            raise ValueError("资料综合版要求月支权重为单项最高值")
        if self.day_stem == 0:
            raise ValueError("日干权重不能为0")
        return self

    def by_code(self) -> dict[str, int]:
        return {code: getattr(self, field) for code, field in PERSONAL_PILLAR_CODE_TO_FIELD.items()}


class HiddenStemShare(ImmutableModel):
    """一个地支内某个藏干的工程占比。"""

    stem: str = Field(min_length=1, max_length=1)
    share: int = Field(ge=1, le=100)

    @model_validator(mode="after")
    def validate_stem(self):
        if self.stem not in HEAVENLY_STEM_ELEMENT:
            raise ValueError(f"未知天干：{self.stem}")
        return self


class SeasonalStateMultipliers(ImmutableModel):
    """旺、相、休、囚、死换算为结构计算倍率。

    名称来自传统四时旺衰；倍率是本项目为了可计算而设的启发式参数，不是古籍
    原数值。倍率必须严格递减，避免配置把旺衰含义反转。
    """

    wang: float = Field(gt=0, le=3)
    xiang: float = Field(gt=0, le=3)
    xiu: float = Field(gt=0, le=3)
    qiu: float = Field(gt=0, le=3)
    si: float = Field(gt=0, le=3)

    @model_validator(mode="after")
    def validate_descending(self):
        values = [self.wang, self.xiang, self.xiu, self.qiu, self.si]
        if not all(left > right for left, right in zip(values, values[1:])):
            raise ValueError("旺相休囚死倍率必须严格递减")
        return self

    def by_state(self) -> dict[str, float]:
        return {
            "旺": self.wang,
            "相": self.xiang,
            "休": self.xiu,
            "囚": self.qiu,
            "死": self.si,
        }


class DayMasterStrengthThresholds(ImmutableModel):
    """用“同我＋生我”的结构占比划分偏弱、相对平衡、偏强。"""

    weak_max: float = Field(ge=0, le=100)
    strong_min: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_gap(self):
        if self.weak_max >= self.strong_min:
            raise ValueError("偏弱上限必须小于偏强下限")
        return self

    def classify(self, support_ratio: float) -> StrengthRegime:
        if support_ratio < self.weak_max:
            return "weak"
        if support_ratio > self.strong_min:
            return "strong"
        return "balanced"


class ElementRoleScores(ImmutableModel):
    """一种强弱状态下，五种十神式五行角色的工程基础分。"""

    resource: int = Field(ge=-100, le=100, description="生我")
    peer: int = Field(ge=-100, le=100, description="同我")
    output: int = Field(ge=-100, le=100, description="我生")
    wealth: int = Field(ge=-100, le=100, description="我克")
    officer: int = Field(ge=-100, le=100, description="克我")

    def for_role(self, role: ElementRole) -> int:
        return int(getattr(self, role))


class DayMasterStrategyScores(ImmutableModel):
    """偏弱、平衡、偏强三种情况下的角色分值表。"""

    weak: ElementRoleScores
    balanced: ElementRoleScores
    strong: ElementRoleScores

    def for_regime(self, regime: StrengthRegime) -> ElementRoleScores:
        return getattr(self, regime)


class PersonalRuleConfiguration(ImmutableModel):
    """驱动个人五色计算的完整、可追溯配置。"""

    version: str = Field(min_length=1, max_length=64)
    status: RuleStatus = "source_reviewed"
    public_rule_version: str = Field(min_length=1, max_length=64)
    algorithm_summary: str = Field(min_length=1, max_length=1600)
    pillar_weights: PersonalPillarWeights
    hidden_stems: dict[str, list[HiddenStemShare]]
    month_dominant_elements: dict[str, Element]
    seasonal_multipliers: SeasonalStateMultipliers
    strength_thresholds: DayMasterStrengthThresholds
    strategy_scores: DayMasterStrategyScores
    balance_target_percent: float = Field(ge=0, le=100)
    deficiency_weight: float = Field(ge=0, le=10)
    deficiency_adjustment_limit: float = Field(ge=0, le=100)
    birth_structure_weight: int = Field(ge=0, le=100)
    public_environment_weight: int = Field(ge=0, le=100)
    tie_break_color_order: list[str] = Field(min_length=5, max_length=5)
    tendency_thresholds: TendencyThresholds
    research_references: list[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_configuration(self):
        branches = set(EARTHLY_BRANCH_PRIMARY_ELEMENT)
        if set(self.hidden_stems) != branches:
            raise ValueError("藏干配置必须完整包含十二地支")
        for branch, shares in self.hidden_stems.items():
            if not shares:
                raise ValueError(f"{branch}的藏干不能为空")
            if sum(item.share for item in shares) != 100:
                raise ValueError(f"{branch}的藏干比例合计必须等于100")
            stems = [item.stem for item in shares]
            if len(stems) != len(set(stems)):
                raise ValueError(f"{branch}的藏干不能重复")
        if set(self.month_dominant_elements) != branches:
            raise ValueError("月支主气配置必须完整包含十二地支")
        if self.birth_structure_weight + self.public_environment_weight != 100:
            raise ValueError("出生结构与公共环境融合权重合计必须等于100")
        if set(self.tie_break_color_order) != set(COLOR_ELEMENT_MAP):
            raise ValueError("个人同分顺序必须完整且不重复地包含五种颜色")
        return self

    def fingerprint(self) -> str:
        """个人配置内容指纹，不含公共配置本身的指纹。"""
        payload = json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

