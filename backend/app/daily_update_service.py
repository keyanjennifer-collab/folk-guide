"""北京时间每日缓存批处理与应用内调度器。

任务职责只有两项：

1. 每天生成包含当天在内的未来7天公共五色；
2. 分批扫描有生辰档案的用户，仅为权益有效者生成未来3天个人五色。

生成规则仍由 ``daily_color_cache_service`` 负责。本模块只解决什么时候执行、如何
分批、失败怎样重试、多进程如何避免重复，以及运维人员怎样查看结果。它不会调用
大模型，也不会把个人资料发送到任何外部服务。
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as datetime_time, timedelta
from typing import Callable
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .daily_color_cache_service import (
    PERSONAL_CACHE_DAYS,
    PUBLIC_CACHE_DAYS,
    warm_personal_color_cache,
    warm_public_color_cache,
)
from .database import SessionLocal
from .models import AIServiceGrant, BirthProfile, DailyCacheRun, User
from .time_service import BEIJING_TIMEZONE, beijing_now, beijing_today, utc_now_naive


logger = logging.getLogger("folk_guide.daily_update")


@dataclass(frozen=True)
class DailyUpdateResult:
    """一次任务的结构化结果，可直接转换为管理员接口响应。"""

    target_date: date
    status: str
    trigger: str
    attempt: int
    public_days: int
    eligible_users: int
    personal_users: int
    failed_users: int
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None
    skipped: bool = False

    def to_dict(self) -> dict:
        """为FastAPI响应和日志提供稳定字段，不暴露worker_id或租约细节。"""
        return asdict(self)


class PartialDailyUpdateError(RuntimeError):
    """公共缓存成功，但一个或多个个人缓存失败，需要再次执行幂等重试。"""


def _worker_id() -> str:
    """标识本次执行者，用于防止过期worker覆盖接管者的最终状态。"""
    return f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:10]}"


def _result_from_row(row: DailyCacheRun, *, skipped: bool = False) -> DailyUpdateResult:
    """把数据库任务记录转换成不含内部租约信息的结果。"""
    return DailyUpdateResult(
        target_date=row.target_date,
        status=row.status,
        trigger=row.trigger,
        attempt=row.attempt,
        public_days=row.public_days,
        eligible_users=row.eligible_users,
        personal_users=row.personal_users,
        failed_users=row.failed_users,
        error_message=row.error_message,
        started_at=row.started_at,
        finished_at=row.finished_at,
        skipped=skipped,
    )


def _acquire_run(
    db: Session,
    target_date: date,
    trigger: str,
    *,
    force: bool,
    lease_minutes: int,
) -> tuple[DailyCacheRun, str] | DailyUpdateResult:
    """取得某个北京时间日期的数据库执行租约。

    同一天正常调度只成功一次。管理员可以用 ``force=true`` 重跑已完成任务，但不能
    抢占仍在有效租约内的运行中任务。SQLite 的首次插入竞争由唯一约束兜底；已有
    记录通过条件UPDATE原子接管，迁移PostgreSQL后仍可沿用。
    """
    now = utc_now_naive()
    lease_until = now + timedelta(minutes=max(lease_minutes, 1))
    worker_id = _worker_id()
    row = db.scalar(select(DailyCacheRun).where(DailyCacheRun.target_date == target_date))

    if row is None:
        row = DailyCacheRun(
            target_date=target_date,
            status="running",
            trigger=trigger,
            attempt=1,
            worker_id=worker_id,
            lease_expires_at=lease_until,
            started_at=now,
        )
        db.add(row)
        try:
            db.commit()
            db.refresh(row)
            return row, worker_id
        except IntegrityError:
            # 另一个worker刚刚插入同一天记录。回滚后读取获胜者，不重复执行。
            db.rollback()
            winner = db.scalar(select(DailyCacheRun).where(DailyCacheRun.target_date == target_date))
            if winner is None:  # pragma: no cover - 数据库异常时的防御性保护
                raise
            return _result_from_row(winner, skipped=True)

    lease_active = (
        row.status == "running"
        and row.lease_expires_at is not None
        and row.lease_expires_at > now
    )
    if lease_active or (row.status == "succeeded" and not force):
        return _result_from_row(row, skipped=True)

    # 条件UPDATE防止两个worker同时接管同一条过期或失败记录。
    allowed = or_(
        DailyCacheRun.status != "running",
        DailyCacheRun.lease_expires_at.is_(None),
        DailyCacheRun.lease_expires_at <= now,
    )
    statement = (
        update(DailyCacheRun)
        .where(DailyCacheRun.id == row.id, allowed)
        .values(
            status="running",
            trigger=trigger,
            attempt=DailyCacheRun.attempt + 1,
            public_days=0,
            eligible_users=0,
            personal_users=0,
            failed_users=0,
            error_message=None,
            worker_id=worker_id,
            lease_expires_at=lease_until,
            started_at=now,
            finished_at=None,
        )
    )
    changed = db.execute(statement).rowcount
    db.commit()
    refreshed = db.scalar(select(DailyCacheRun).where(DailyCacheRun.id == row.id))
    if refreshed is None:  # pragma: no cover - 主键记录不应在任务期间消失
        raise RuntimeError("每日缓存任务记录不存在")
    if changed != 1:
        return _result_from_row(refreshed, skipped=True)
    return refreshed, worker_id


def _active_paid_plans(db: Session, user_ids: list[int], now: datetime) -> dict[int, str]:
    """一次查询取得本批用户的有效正式权益，结束时间更晚的记录优先。"""
    if not user_ids:
        return {}
    grants = db.scalars(
        select(AIServiceGrant)
        .where(
            AIServiceGrant.user_id.in_(user_ids),
            AIServiceGrant.start_at <= now,
            AIServiceGrant.end_at > now,
        )
        .order_by(AIServiceGrant.user_id, AIServiceGrant.end_at.desc())
    ).all()
    plans: dict[int, str] = {}
    for grant in grants:
        plans.setdefault(grant.user_id, grant.grant_type)
    return plans


def _entitlement_plan(user: User, paid_plans: dict[int, str], now: datetime) -> str | None:
    """返回缓存所需权益计划；正式权益优先，其次是账号创建后72小时体验。"""
    paid = paid_plans.get(user.id)
    if paid:
        return paid
    if now < user.created_at + timedelta(days=3):
        return "new_user_3_days"
    return None


def _safe_error_message(exc: Exception) -> str:
    """数据库只存稳定错误类别，避免把SQL、配置路径或业务正文写进状态接口。"""
    if isinstance(exc, PartialDailyUpdateError):
        return str(exc)[:500]
    return f"{type(exc).__name__}：每日缓存任务执行失败，请查看服务端日志"[:500]


def _mark_failed(
    session_factory: Callable[[], Session],
    run_id: int,
    worker_id: str,
    *,
    public_days: int,
    eligible_users: int,
    personal_users: int,
    failed_users: int,
    exc: Exception,
) -> None:
    """使用新会话记录失败，避免原业务事务已损坏时无法保存任务状态。"""
    with session_factory() as status_db:
        row = status_db.scalar(select(DailyCacheRun).where(
            DailyCacheRun.id == run_id,
            DailyCacheRun.worker_id == worker_id,
        ))
        if row is None:
            return
        row.status = "failed"
        row.public_days = public_days
        row.eligible_users = eligible_users
        row.personal_users = personal_users
        row.failed_users = failed_users
        row.error_message = _safe_error_message(exc)
        row.finished_at = utc_now_naive()
        row.lease_expires_at = None
        status_db.commit()


def run_daily_cache_update(
    target_date: date | None = None,
    *,
    trigger: str = "scheduler",
    force: bool = False,
    batch_size: int | None = None,
    lease_minutes: int | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
) -> DailyUpdateResult:
    """执行一次公共和个人缓存更新。

    用户按档案主键游标分批读取，不使用一次性 ``.all()`` 加载全量用户，也不使用
    数据量越大越慢的深分页OFFSET。每个用户在SAVEPOINT内生成；某一份异常档案不
    会回滚同批其他用户已经生成的结果。成功结果是幂等的，重试不会增加重复行。
    """
    settings = get_settings()
    target_date = target_date or beijing_today()
    batch_size = max(batch_size or settings.daily_cache_batch_size, 1)
    lease_minutes = max(lease_minutes or settings.daily_cache_lease_minutes, 1)
    trigger = trigger[:24] or "scheduler"

    public_days = 0
    eligible_users = 0
    personal_users = 0
    failed_users = 0

    with session_factory() as db:
        acquired = _acquire_run(
            db, target_date, trigger, force=force, lease_minutes=lease_minutes
        )
        if isinstance(acquired, DailyUpdateResult):
            logger.info(
                "daily_cache_skipped target_date=%s status=%s attempt=%s",
                target_date,
                acquired.status,
                acquired.attempt,
            )
            return acquired
        run, worker_id = acquired

        logger.info(
            "daily_cache_started target_date=%s trigger=%s attempt=%s",
            target_date,
            trigger,
            run.attempt,
        )
        try:
            # 公共结果完全不含用户数据，先一次性准备未来7天。
            public_days = len(warm_public_color_cache(db, target_date, PUBLIC_CACHE_DAYS))

            last_profile_id = 0
            now = utc_now_naive()
            while True:
                rows = db.execute(
                    select(BirthProfile, User)
                    .join(User, User.id == BirthProfile.user_id)
                    .where(BirthProfile.id > last_profile_id)
                    .order_by(BirthProfile.id)
                    .limit(batch_size)
                ).all()
                if not rows:
                    break
                last_profile_id = rows[-1][0].id
                paid_plans = _active_paid_plans(db, [user.id for _, user in rows], now)

                for profile, user in rows:
                    plan = _entitlement_plan(user, paid_plans, now)
                    if plan is None:
                        continue
                    eligible_users += 1
                    try:
                        # SAVEPOINT只隔离当前用户；失败时继续处理其他用户。
                        with db.begin_nested():
                            warm_personal_color_cache(
                                db,
                                profile,
                                plan,
                                target_date,
                                PERSONAL_CACHE_DAYS,
                                commit=False,
                            )
                        personal_users += 1
                    except Exception as exc:  # noqa: BLE001 - 批任务必须记录并继续
                        failed_users += 1
                        logger.exception(
                            "daily_personal_cache_failed user_id=%s error_type=%s",
                            user.id,
                            type(exc).__name__,
                        )

                # 每批提交一次并续租；这样用户很多时不会形成超大事务。
                run.public_days = public_days
                run.eligible_users = eligible_users
                run.personal_users = personal_users
                run.failed_users = failed_users
                run.lease_expires_at = utc_now_naive() + timedelta(minutes=lease_minutes)
                db.commit()

            if failed_users:
                raise PartialDailyUpdateError(f"{failed_users}个用户的个人缓存生成失败")

            run.status = "succeeded"
            run.public_days = public_days
            run.eligible_users = eligible_users
            run.personal_users = personal_users
            run.failed_users = 0
            run.error_message = None
            run.finished_at = utc_now_naive()
            run.lease_expires_at = None
            db.commit()
            db.refresh(run)
            result = _result_from_row(run)
            logger.info(
                "daily_cache_succeeded target_date=%s public_days=%s personal_users=%s",
                target_date,
                public_days,
                personal_users,
            )
            return result
        except Exception as exc:
            db.rollback()
            _mark_failed(
                session_factory,
                run.id,
                worker_id,
                public_days=public_days,
                eligible_users=eligible_users,
                personal_users=personal_users,
                failed_users=failed_users,
                exc=exc,
            )
            logger.exception(
                "daily_cache_failed target_date=%s attempt=%s error_type=%s",
                target_date,
                run.attempt,
                type(exc).__name__,
            )
            raise


def get_daily_update_result(
    target_date: date,
    *,
    session_factory: Callable[[], Session] = SessionLocal,
) -> DailyUpdateResult | None:
    """读取某天任务结果，供最终重试失败和运维接口复用。"""
    with session_factory() as db:
        row = db.scalar(select(DailyCacheRun).where(DailyCacheRun.target_date == target_date))
        return _result_from_row(row) if row else None


def list_daily_update_results(
    limit: int = 30,
    *,
    session_factory: Callable[[], Session] = SessionLocal,
) -> list[DailyUpdateResult]:
    """按目标日期倒序返回最近任务，不包含任何用户级数据。"""
    with session_factory() as db:
        rows = db.scalars(
            select(DailyCacheRun)
            .order_by(DailyCacheRun.target_date.desc())
            .limit(max(1, min(limit, 100)))
        ).all()
        return [_result_from_row(row) for row in rows]


def run_daily_cache_update_with_retry(
    target_date: date | None = None,
    *,
    trigger: str = "scheduler",
    force: bool = False,
    attempts: int | None = None,
    retry_seconds: float | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
    sleep: Callable[[float], None] = time.sleep,
    run_once: Callable[..., DailyUpdateResult] = run_daily_cache_update,
) -> DailyUpdateResult:
    """失败后按配置重试，最终仍失败时返回数据库中的失败状态。

    重试会强制接管上一轮已经标记为failed的同日记录。已经成功或正被其他worker
    执行的任务会直接返回，不会因为每个worker都启动调度循环而重复计算。
    """
    settings = get_settings()
    target_date = target_date or beijing_today()
    attempts = max(attempts or settings.daily_cache_retry_attempts, 1)
    retry_seconds = max(
        settings.daily_cache_retry_seconds if retry_seconds is None else retry_seconds,
        0.0,
    )
    last_error: Exception | None = None

    for index in range(attempts):
        try:
            return run_once(
                target_date,
                trigger=trigger,
                force=force or index > 0,
                session_factory=session_factory,
            )
        except Exception as exc:  # noqa: BLE001 - 统一控制调度重试边界
            last_error = exc
            if index + 1 < attempts:
                delay = retry_seconds * (2 ** index)
                logger.warning(
                    "daily_cache_retry target_date=%s next_attempt=%s delay_seconds=%s",
                    target_date,
                    index + 2,
                    delay,
                )
                sleep(delay)

    result = get_daily_update_result(target_date, session_factory=session_factory)
    if result is not None:
        return result
    # 正常情况下首次执行一定会写入任务记录；这里只处理数据库在写记录前即失效的情况。
    now = utc_now_naive()
    return DailyUpdateResult(
        target_date=target_date,
        status="failed",
        trigger=trigger,
        attempt=attempts,
        public_days=0,
        eligible_users=0,
        personal_users=0,
        failed_users=0,
        error_message=_safe_error_message(last_error or RuntimeError("未知错误")),
        started_at=now,
        finished_at=now,
    )


def seconds_until_next_beijing_midnight(now_utc: datetime | None = None) -> float:
    """计算距离下一个北京时间00:00的秒数，服务器自身时区不会影响结果。"""
    local_now = beijing_now(now_utc)
    next_date = local_now.date() + timedelta(days=1)
    next_midnight = datetime.combine(next_date, datetime_time.min, tzinfo=BEIJING_TIMEZONE)
    return max((next_midnight - local_now).total_seconds(), 0.0)


async def daily_cache_scheduler_loop() -> None:
    """应用启动后的常驻调度循环；关闭服务时由lifespan取消。

    启动后立即补跑当天，防止服务器在零点停机时漏掉任务。完成后睡眠到下一个
    北京时间零点。计算和数据库操作放在线程中，避免阻塞FastAPI异步事件循环。
    """
    logger.info("daily_cache_scheduler_started timezone=Asia/Shanghai hour=00:00")
    while True:
        result = await asyncio.to_thread(
            run_daily_cache_update_with_retry,
            trigger="scheduler",
        )
        # 最终失败不能直接睡到下一个零点，否则当天内容会整日断更。
        # 失败日期下一轮会接管 failed 租约并按幂等缓存重试；限制间隔避免
        # 外部依赖持续故障时形成紧循环，同时不影响跨零点的日期切换。
        if result.status == "failed":
            retry_delay = max(min(get_settings().daily_cache_retry_seconds, 300.0), 1.0)
            logger.warning(
                "daily_cache_scheduler_retry_after_failure target_date=%s delay_seconds=%.1f",
                result.target_date,
                retry_delay,
            )
            await asyncio.sleep(retry_delay)
            continue
        # 极端情况下任务在23:59启动并跨过零点，应立即补跑新的北京时间日期。
        if result.target_date != beijing_today():
            continue
        delay = seconds_until_next_beijing_midnight() + 1.0
        logger.info("daily_cache_scheduler_sleep seconds=%.1f", delay)
        await asyncio.sleep(delay)
