"""项目统一北京时间工具。

业务中的“今天”统一按北京时间（中国标准时间）计算，不能直接使用
``date.today()``，因为服务器将来可能部署在 UTC 或其他系统时区。

Windows 默认不一定携带 IANA 时区数据库，因此项目通过 requirements.txt
显式安装 tzdata；北京时间在 IANA 数据库中的标准标识是 ``Asia/Shanghai``，
并不存在 ``Asia/Beijing`` 这个可移植标识。
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


# ZoneInfo 会优先使用操作系统时区数据，系统没有时会读取 Python 的 tzdata 包。
# 在模块加载时创建一次即可，无需在每个请求中重复构造。
BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")


def beijing_now(now_utc: datetime | None = None) -> datetime:
    """返回带时区的北京时间。

    ``now_utc`` 只用于自动化测试或调用方已经取得可靠 UTC 时间的场景。
    为避免把含义不清楚的本地时间误当 UTC，传入值必须携带时区信息。
    """
    source = now_utc or datetime.now(timezone.utc)
    if source.tzinfo is None:
        raise ValueError("now_utc 必须是带时区的 datetime")
    return source.astimezone(BEIJING_TIMEZONE)


def beijing_today(now_utc: datetime | None = None) -> date:
    """返回北京时间自然日，用作每日内容和个人缓存的统一日期边界。"""
    return beijing_now(now_utc).date()


def utc_now_naive() -> datetime:
    """返回数据库当前采用的无时区 UTC 时间。

    业务自然日统一按北京时间，但事件时间仍以 UTC 存储，这是跨服务器部署时更稳妥
    的做法。数据库迁移为带时区列之前，集中通过此函数生成兼容的 naive UTC 值。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def beijing_day_bounds_utc_naive(now_utc: datetime | None = None) -> tuple[datetime, datetime]:
    """返回当前北京时间自然日在数据库中的 UTC 起止边界（左闭右开）。

    例如北京时间 2026-08-20 的数据库查询范围是 UTC 2026-08-19 16:00 至
    2026-08-20 16:00。返回 naive UTC 是为了兼容当前 SQLite 的 DateTime 字段。
    """
    source = now_utc or datetime.now(timezone.utc)
    if source.tzinfo is None:
        # 当前业务调用传入的 now 来自数据库兼容代码，约定无时区值表示 UTC。
        source = source.replace(tzinfo=timezone.utc)
    local_date = beijing_today(source)
    local_start = datetime.combine(local_date, time.min, tzinfo=BEIJING_TIMEZONE)
    local_end = local_start + timedelta(days=1)
    return (
        local_start.astimezone(timezone.utc).replace(tzinfo=None),
        local_end.astimezone(timezone.utc).replace(tzinfo=None),
    )
