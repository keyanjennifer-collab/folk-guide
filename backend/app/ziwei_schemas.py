"""紫微起盘与合盘的 API 输入输出结构。"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ZiweiBirthInput(BaseModel):
    label: str = Field(default="我的命盘", min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=64)
    birth_date: date
    calendar_type: Literal["solar", "lunar"] = "solar"
    is_leap_month: bool = False
    birth_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    gender: Literal["male", "female"]
    birth_location: str | None = Field(default=None, max_length=128)

    @field_validator("label", "name", "birth_location", mode="before")
    @classmethod
    def trim_text(cls, value: str | None):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_birth_date(self):
        if self.birth_date.year < 1900 or self.birth_date.year > date.today().year:
            raise ValueError("出生年份需在1900年至今之间")
        if self.calendar_type == "solar" and self.birth_date > date.today():
            raise ValueError("公历出生日期不能晚于今天")
        if self.calendar_type == "solar":
            self.is_leap_month = False
        return self


class ZiweiChartOutput(BaseModel):
    id: int
    label: str
    name: str | None
    birth_date: date
    calendar_type: str
    is_leap_month: bool
    birth_time: str
    gender: str
    birth_location: str | None
    chart: dict
    created_at: datetime
    updated_at: datetime


class ZiweiCompatibilityInput(BaseModel):
    relation_type: Literal["business", "love", "family", "friend"]
    person_a: ZiweiBirthInput
    person_b: ZiweiBirthInput


class ZiweiCompatibilityOutput(BaseModel):
    id: int
    relation_type: str
    person_a: dict
    person_b: dict
    result: dict
    created_at: datetime
