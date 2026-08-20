"""生辰档案完整度和 API 输出组装。

本模块只负责“数据是否完整”和“如何返回”，不负责对用户作吉凶判断。
把输出组装从路由中独立出来，后续更换数据库或前端时更容易测试。
"""

from .calendar_service import load_calendar_payload
from .models import BirthProfile


def profile_completeness(profile: BirthProfile) -> tuple[int, list[str]]:
    """返回完整度百分比和缺失字段，用于前端引导用户补全，而非算命结论。"""
    score = 50
    missing: list[str] = []
    if profile.time_known and profile.birth_time:
        score += 25
    else:
        missing.append("birth_time")
    if profile.birth_city:
        score += 15
    else:
        missing.append("birth_city")
    if profile.gender != "unspecified":
        score += 10
    else:
        missing.append("gender")
    return score, missing


def profile_output(profile: BirthProfile) -> dict:
    """把 ORM 档案与历法缓存合并为稳定的接口返回结构。"""
    completeness, missing_fields = profile_completeness(profile)
    return {
        "id": profile.id,
        "calendar_type": profile.calendar_type,
        "is_leap_month": profile.is_leap_month,
        "birth_date": profile.birth_date,
        "time_known": profile.time_known,
        "birth_time": profile.birth_time,
        "birth_city": profile.birth_city,
        "gender": profile.gender,
        "timezone": profile.timezone,
        "profile_version": profile.profile_version,
        "completeness": completeness,
        "missing_fields": missing_fields,
        "result_mode": "full" if profile.time_known and profile.birth_time else "simplified",
        "calendar": load_calendar_payload(profile),
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }
"""生辰档案完整度和 API 输出组装，避免路由层重复业务判断。"""
