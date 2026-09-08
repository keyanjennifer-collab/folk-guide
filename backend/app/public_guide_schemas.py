"""今日五色自动生成内容的数据模型。"""

from datetime import date

from pydantic import BaseModel, Field, model_validator


COLOR_ELEMENT_MAP = {
    "白金": "金",
    "绿金": "木",
    "黑金": "水",
    "红金": "火",
    "黄金": "土",
}

# 公开运营内容只使用用户确认的“色系”命名；旧键仅保留给既有确定性规则引擎，
# 不再出现在小程序和每日内容录入模板中。
PUBLIC_COLOR_ELEMENT_MAP = {
    "白色系": "金",
    "绿色系": "木",
    "黑色系": "水",
    "红色系": "火",
    "黄色系": "土",
}

SMOOTHNESS_VALUES = {"得生助旺", "同气相和", "克制求进", "生泄耗气", "受制势弱"}


class PublicGuideItemInput(BaseModel):
    """一种颜色的排名、说明、宜忌和对应香品。"""
    rank: int = Field(ge=1, le=5)
    color: str
    element: str
    smoothness: str
    suitable: list[str] = Field(min_length=1)
    resistance: str = Field(min_length=1, max_length=500)
    advice: str = Field(min_length=1, max_length=500)
    product_code: str = Field(min_length=1, max_length=64)
    incense_name: str = Field(min_length=1, max_length=100)
    scent: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_fixed_values(self):
        """检查颜色与五行映射，并清理适合事项列表。"""
        expected = PUBLIC_COLOR_ELEMENT_MAP.get(self.color)
        if not expected:
            raise ValueError(f"不支持的五色名称：{self.color}")
        if self.element != expected:
            raise ValueError(f"{self.color}必须对应五行{expected}")
        if self.smoothness not in SMOOTHNESS_VALUES:
            raise ValueError(f"不支持的顺畅度：{self.smoothness}")
        self.suitable = [value.strip() for value in self.suitable if value.strip()]
        if not self.suitable:
            raise ValueError("适合事项不能为空")
        return self


class PublicGuideInput(BaseModel):
    """某一天完整的公共五色内容，要求颜色和排名不重复。"""
    guide_date: date
    weekday: str = Field(min_length=1, max_length=16)
    lunar_date: str = Field(min_length=1, max_length=64)
    solar_term: str = Field(min_length=1, max_length=32)
    day_ganzhi: str = Field(min_length=2, max_length=16)
    items: list[PublicGuideItemInput] = Field(min_length=5, max_length=5)
    share_title: str = Field(min_length=1, max_length=100)
    share_summary: str = Field(min_length=1, max_length=300)
    push_summary: str = Field(min_length=1, max_length=200)
    rule_version: str = Field(default="daily-rule-v1", max_length=64)

    @model_validator(mode="after")
    def validate_complete_ranking(self):
        """保证五色和第一至第五名完整且不重复。"""
        ranks = [item.rank for item in self.items]
        colors = [item.color for item in self.items]
        if sorted(ranks) != [1, 2, 3, 4, 5]:
            raise ValueError("排名必须完整且不重复地包含1至5")
        if set(colors) != set(PUBLIC_COLOR_ELEMENT_MAP):
            raise ValueError("每天必须完整包含白色系、绿色系、黑色系、红色系、黄色系")
        self.items.sort(key=lambda item: item.rank)
        return self
