"""正式 AI 国学问答、次数权益、历史记录和反馈接口的数据模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AIChatInput(BaseModel):
    """用户问题。question_type 可让前端明确标记“七日比较”功能。"""
    question: str = Field(min_length=1, max_length=500)
    question_type: str | None = Field(default=None, pattern="^(normal|seven_day_comparison)$")


class AICitation(BaseModel):
    """回答依据；知识片段精确到切片，个人结果明确标成独立规则来源。"""
    kind: Literal["knowledge", "personal_daily", "web"] = "knowledge"
    document_id: int | None
    chunk_id: int | None
    title: str
    heading: str | None
    source_name: str
    page_start: int | None = None
    page_end: int | None = None


class AIChatOutput(BaseModel):
    """正式问答返回值；blocked=True 表示安全规则拦截。"""
    message_id: int
    answer: str
    category: str
    blocked: bool
    citations: list[AICitation]
    remaining_today: int
    model_name: str
    # safe / blocked / output_filtered / output_truncated；便于前端在必要时说明答案被安全处理。
    safety_status: str = "safe"
    disclaimer: str


class AIQuotaOutput(BaseModel):
    """当前权益及两类功能今日剩余次数。"""
    active: bool
    plan: str | None
    expires_at: datetime | None
    normal_limit: int
    normal_used: int
    normal_remaining: int
    comparison_limit: int
    comparison_used: int
    comparison_remaining: int
    answer_ready: bool


class AIHistoryItem(BaseModel):
    """只返回当前用户自己的问答历史。"""
    id: int
    question: str
    answer: str
    category: str
    citations: list[AICitation]
    feedback: str | None
    safety_status: str = "safe"
    created_at: datetime


class AIFeedbackInput(BaseModel):
    """用户可以点赞或点踩，并可补充短说明。"""
    rating: str = Field(pattern="^(helpful|unhelpful)$")
    note: str | None = Field(default=None, max_length=500)
