"""北京时间每日自动缓存、批量权益筛选、幂等与运维接口测试。"""

import json
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.calendar_service import apply_calendar_calculation
from app.daily_update_service import (
    DailyUpdateResult,
    run_daily_cache_update,
    run_daily_cache_update_with_retry,
    seconds_until_next_beijing_midnight,
)
from app.database import SessionLocal
from app.main import app
from app.models import (
    AIServiceGrant,
    BirthProfile,
    DailyCacheRun,
    DailyGuidance,
    PublicColorCache,
    User,
)
from app.schemas import BirthProfileInput
from app.time_service import utc_now_naive


ADMIN_HEADERS = {"X-Admin-Key": "dev-admin-key", "X-Admin-Name": "pytest"}


def _create_user_with_profile(
    db,
    *,
    openid: str,
    created_at: datetime,
    birth_date: date,
) -> tuple[User, BirthProfile]:
    """直接创建已完成历法计算的测试用户，避免依赖微信登录流程。"""
    user = User(openid=openid, created_at=created_at)
    db.add(user)
    db.flush()
    data = BirthProfileInput(
        calendar_type="solar",
        birth_date=birth_date,
        time_known=False,
        birth_city="杭州",
    )
    profile = BirthProfile(user_id=user.id, profile_version=1, **data.model_dump())
    db.add(profile)
    db.flush()
    apply_calendar_calculation(profile, data)
    return user, profile


def test_daily_batch_warms_only_entitled_users_and_is_idempotent():
    """公共生成7天；体验和付费用户生成3天；过期用户不读取个人结果。"""
    target = date(2044, 5, 6)
    end = target + timedelta(days=7)
    now = utc_now_naive()
    user_ids: list[int] = []

    with TestClient(app) as client:
        try:
            with SessionLocal() as db:
                trial_user, _ = _create_user_with_profile(
                    db,
                    openid="daily-job-active-trial",
                    created_at=now - timedelta(hours=12),
                    birth_date=date(1995, 6, 18),
                )
                paid_user, _ = _create_user_with_profile(
                    db,
                    openid="daily-job-paid",
                    created_at=now - timedelta(days=20),
                    birth_date=date(1982, 11, 3),
                )
                expired_user, _ = _create_user_with_profile(
                    db,
                    openid="daily-job-expired",
                    created_at=now - timedelta(days=20),
                    birth_date=date(1990, 1, 2),
                )
                user_ids = [trial_user.id, paid_user.id, expired_user.id]
                db.add(AIServiceGrant(
                    user_id=paid_user.id,
                    grant_type="paid_30_days",
                    start_at=now - timedelta(hours=1),
                    end_at=now + timedelta(days=30),
                ))
                db.query(DailyCacheRun).filter(DailyCacheRun.target_date == target).delete()
                db.query(PublicColorCache).filter(
                    PublicColorCache.guide_date >= target,
                    PublicColorCache.guide_date < end,
                ).delete()
                db.commit()

            # batch_size=1强制走多批次，验证用户增多后仍使用游标分批处理。
            first = run_daily_cache_update(target, trigger="pytest", batch_size=1)
            assert first.status == "succeeded"
            assert first.public_days == 7
            # 完整测试套件可能还有其他未过期测试账号；这里只要求本用例的两名有效
            # 用户一定包含在批任务中，再通过下方逐用户查询证明过期用户被排除。
            assert first.eligible_users >= 2
            assert first.personal_users >= 2
            assert first.failed_users == 0
            assert first.skipped is False

            with SessionLocal() as db:
                public_rows = db.scalars(select(PublicColorCache).where(
                    PublicColorCache.guide_date >= target,
                    PublicColorCache.guide_date < end,
                )).all()
                assert len(public_rows) == 7

                trial_rows = db.scalars(select(DailyGuidance).where(
                    DailyGuidance.user_id == user_ids[0],
                    DailyGuidance.guidance_date >= target,
                    DailyGuidance.guidance_date < target + timedelta(days=3),
                )).all()
                paid_rows = db.scalars(select(DailyGuidance).where(
                    DailyGuidance.user_id == user_ids[1],
                    DailyGuidance.guidance_date >= target,
                    DailyGuidance.guidance_date < target + timedelta(days=3),
                )).all()
                expired_rows = db.scalars(select(DailyGuidance).where(
                    DailyGuidance.user_id == user_ids[2],
                )).all()
                assert len(trial_rows) == 3
                assert len(paid_rows) == 3
                assert expired_rows == []
                assert {json.loads(row.payload_json)["entitlement_plan"] for row in trial_rows} == {
                    "new_user_3_days"
                }
                assert {json.loads(row.payload_json)["entitlement_plan"] for row in paid_rows} == {
                    "paid_30_days"
                }

            # 同日再次正常触发直接复用成功记录，不增加重复缓存。
            second = run_daily_cache_update(target, trigger="pytest")
            assert second.status == "succeeded"
            assert second.skipped is True
            assert second.attempt == first.attempt

            status = client.get("/api/admin/daily-cache/runs?limit=5", headers=ADMIN_HEADERS)
            assert status.status_code == 200
            matching = [item for item in status.json() if item["target_date"] == target.isoformat()]
            assert matching and matching[0]["personal_users"] == first.personal_users

            manual = client.post(
                "/api/admin/daily-cache/run",
                headers=ADMIN_HEADERS,
                json={"target_date": target.isoformat(), "force": False},
            )
            assert manual.status_code == 200
            assert manual.json()["skipped"] is True
            assert client.get("/api/admin/daily-cache/runs").status_code == 403
        finally:
            # 测试数据必须清理，避免影响同一测试进程内的其他权益和缓存用例。
            with SessionLocal() as db:
                if user_ids:
                    db.query(DailyGuidance).filter(
                        DailyGuidance.guidance_date >= target,
                        DailyGuidance.guidance_date < target + timedelta(days=3),
                    ).delete(
                        synchronize_session=False
                    )
                    db.query(AIServiceGrant).filter(AIServiceGrant.user_id.in_(user_ids)).delete(
                        synchronize_session=False
                    )
                    db.query(BirthProfile).filter(BirthProfile.user_id.in_(user_ids)).delete(
                        synchronize_session=False
                    )
                    db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
                db.query(DailyCacheRun).filter(DailyCacheRun.target_date == target).delete()
                db.query(PublicColorCache).filter(
                    PublicColorCache.guide_date >= target,
                    PublicColorCache.guide_date < end,
                ).delete()
                db.commit()


def test_retry_forces_failed_date_and_uses_exponential_delays():
    """前两次失败后第三次成功；重试必须强制接管同日failed记录。"""
    calls: list[bool] = []
    delays: list[float] = []
    target = date(2044, 6, 1)

    def flaky_run(target_date, **kwargs):
        calls.append(bool(kwargs["force"]))
        if len(calls) < 3:
            raise RuntimeError("temporary test error")
        now = utc_now_naive()
        return DailyUpdateResult(
            target_date=target_date,
            status="succeeded",
            trigger=kwargs["trigger"],
            attempt=3,
            public_days=7,
            eligible_users=0,
            personal_users=0,
            failed_users=0,
            error_message=None,
            started_at=now,
            finished_at=now,
        )

    result = run_daily_cache_update_with_retry(
        target,
        trigger="pytest",
        attempts=3,
        retry_seconds=2,
        sleep=delays.append,
        run_once=flaky_run,
    )
    assert result.status == "succeeded"
    assert calls == [False, True, True]
    assert delays == [2, 4]


def test_scheduler_waits_for_beijing_midnight_not_server_midnight():
    """北京时间23:59:30只等待30秒，不能按服务器本地日期重新计算。"""
    before_midnight = datetime(2026, 8, 21, 15, 59, 30, tzinfo=timezone.utc)
    at_midnight = datetime(2026, 8, 21, 16, 0, 0, tzinfo=timezone.utc)

    assert seconds_until_next_beijing_midnight(before_midnight) == 30
    assert seconds_until_next_beijing_midnight(at_midnight) == 86_400
