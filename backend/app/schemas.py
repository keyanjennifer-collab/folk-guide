"""用户端 API 的输入输出模型和字段校验规则。"""

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator


class LoginRequest(BaseModel):
    """微信 wx.login 返回的短期 code。"""
    code: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    """登录成功后的 Bearer Token。"""
    access_token: str
    token_type: str = "bearer"


class CurrentUserOutput(BaseModel):
    """“我的”页面所需账号状态，不返回敏感的微信 openid。"""
    id: int
    phone_number: str | None
    phone_bound: bool
    wechat_phone_available: bool
    created_at: datetime


class PhoneCodeInput(BaseModel):
    """微信手机号按钮回传的一次性 code，不接受前端直接提交手机号。"""
    code: str = Field(min_length=1, max_length=512)


class BirthProfileInput(BaseModel):
    """生辰档案输入；出生钟表时间统一解释为北京时间。"""
    calendar_type: str = Field(default="solar", pattern="^(solar|lunar)$")
    is_leap_month: bool = False
    birth_date: date
    time_known: bool = False
    birth_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    birth_city: str | None = Field(default=None, max_length=64)
    gender: str = Field(default="unspecified", pattern="^(male|female|unspecified)$")
    timezone: str = Field(default="Asia/Shanghai", pattern=r"^Asia/Shanghai$")

    @model_validator(mode="after")
    def normalize_profile(self):
        """以显式选择项为准，消除闰月、时辰和城市文本之间的矛盾。

        ``time_known`` 是用户明确操作的开关。即使异常客户端残留提交了
        ``birth_time``，只要开关为 false 就必须清空时间，不能擅自改成已知时辰。
        """
        if self.calendar_type == "solar":
            self.is_leap_month = False
        if not self.time_known:
            self.birth_time = None
        if self.birth_city:
            self.birth_city = self.birth_city.strip() or None
        return self


class CalendarConversionOutput(BaseModel):
    """历法转换结果，包含公农历、生肖、星座、节气和可用四柱。"""
    solar_date: str
    solar_datetime: str | None
    lunar_date: str
    lunar_text: str
    lunar_year: int
    lunar_month: int
    lunar_day: int
    is_leap_month: bool
    zodiac: str
    western_sign: str
    solar_term: str | None
    previous_solar_term: dict[str, str]
    next_solar_term: dict[str, str]
    pillars: dict
    time_pillar_available: bool
    timezone: str
    time_standard: str
    day_boundary_rule: str
    calculation_version: str


class BirthProfileOutput(BirthProfileInput):
    """保存/读取后的完整档案视图，包含引导信息和历法计算结果。"""
    id: int
    profile_version: int
    completeness: int = Field(ge=0, le=100)
    missing_fields: list[str]
    result_mode: str = Field(pattern="^(full|simplified)$")
    calendar: CalendarConversionOutput
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DailyGuidanceColorOutput(BaseModel):
    """个人五色中的一种颜色；不向用户暴露内部原始评分。"""
    rank: int = Field(ge=1, le=5)
    name: str
    element: str
    tendency: str
    suitable: list[str] = Field(min_length=1)
    resistance: str = Field(min_length=1, max_length=500)
    advice: str = Field(min_length=1, max_length=500)
    incense: str = Field(min_length=1, max_length=100)
    scent: str = Field(min_length=1, max_length=300)
    reason: str = Field(min_length=1, max_length=500)


class DailyGuidanceOutput(BaseModel):
    """有AI国学有效权益时返回的个人每日五色结果。"""
    date: date
    timezone: str = "Asia/Shanghai"
    content_version: str
    rule_version: str
    rule_status: str
    precision_mode: str = Field(pattern="^(three_pillars|four_pillars)$")
    profile_version: int = Field(ge=1)
    entitlement_plan: str
    primary_color: str
    supporting_colors: list[str] = Field(min_length=2, max_length=2)
    combination_advice: str = Field(min_length=1, max_length=500)
    personal_focus: str = Field(min_length=1, max_length=500)
    comparison_note: str = Field(min_length=1, max_length=500)
    colors: list[DailyGuidanceColorOutput] = Field(min_length=5, max_length=5)
    suitable: list[str]
    reminders: list[str]
    culture_note: str
    disclaimer: str


class ChatRequest(BaseModel):
    """问答输入；长度限制用于防止异常超长请求。"""
    question: str = Field(min_length=1, max_length=500)


class ChatResponse(BaseModel):
    """旧版规则问答的回答、分类及来源提示。"""
    answer: str
    category: str
    references: list[str] = Field(default_factory=list)
"""用户端 API 的 Pydantic 输入输出模型，负责字段格式和长度校验。"""
