"""每日缓存运维接口的数据模型。"""

from datetime import date, datetime

from pydantic import BaseModel, Field


class DailyUpdateInput(BaseModel):
    """管理员手动补跑参数；不传日期时使用当前北京时间日期。"""

    target_date: date | None = None
    force: bool = False


class DailyUpdateOutput(BaseModel):
    """一次缓存任务的汇总，不包含用户编号或个人内容。"""

    target_date: date
    status: str = Field(pattern="^(running|succeeded|failed)$")
    trigger: str
    attempt: int = Field(ge=1)
    public_days: int = Field(ge=0)
    eligible_users: int = Field(ge=0)
    personal_users: int = Field(ge=0)
    failed_users: int = Field(ge=0)
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None
    skipped: bool = False
