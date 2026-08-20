"""今日五色内容、排期、导入和审计的数据模型。"""

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator


COLOR_ELEMENT_MAP = {
    "白金": "金",
    "绿金": "木",
    "黑金": "水",
    "红金": "火",
    "黄金": "土",
}

SMOOTHNESS_VALUES = {"今天很顺", "比较合适", "平稳一般", "会比较累", "成效偏弱"}


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
        expected = COLOR_ELEMENT_MAP.get(self.color)
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
    rule_version: str = Field(default="manual-v1", max_length=64)

    @model_validator(mode="after")
    def validate_complete_ranking(self):
        """保证五色和第一至第五名完整且不重复。"""
        ranks = [item.rank for item in self.items]
        colors = [item.color for item in self.items]
        if sorted(ranks) != [1, 2, 3, 4, 5]:
            raise ValueError("排名必须完整且不重复地包含1至5")
        if set(colors) != set(COLOR_ELEMENT_MAP):
            raise ValueError("每天必须完整包含白金、绿金、黑金、红金、黄金")
        self.items.sort(key=lambda item: item.rank)
        return self


class ScheduleGuideInput(BaseModel):
    """定时发布请求。"""
    scheduled_at: datetime


class PublicGuideOutput(PublicGuideInput):
    """内容字段加上数据库状态与审计时间。"""
    id: int
    status: str
    version: int
    scheduled_at: datetime | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ImportResult(BaseModel):
    """批量导入的成功数量和逐行错误。"""
    created: int
    updated: int
    dates: list[date]


class AuditOutput(BaseModel):
    """运营动作审计返回结构。"""
    id: int
    action: str
    operator: str
    before_status: str | None
    after_status: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
"""今日五色内容、排期、导入结果和审计记录的数据契约。"""
