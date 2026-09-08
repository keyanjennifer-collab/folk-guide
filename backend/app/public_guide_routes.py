"""今日五色公开自动更新接口。"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .database import get_db
from .daily_color_cache_service import ensure_public_color_cache, warm_public_color_cache
from .public_guide_schemas import PublicGuideInput
from .time_service import beijing_today


router = APIRouter()
logger = logging.getLogger("folk_guide.public_guides")
PUBLIC_TAG = "今日五色·用户端"


def _automatic_guide(guide_date: date, db: Session, *, warm_week: bool = False) -> dict:
    """按确定性历法规则生成并缓存公开内容，不依赖人工发布。"""
    try:
        payload = (
            warm_public_color_cache(db, guide_date)[guide_date]
            if warm_week
            else ensure_public_color_cache(db, guide_date)
        )
        db.commit()
        return payload
    except Exception as exc:  # noqa: BLE001 - 对外隐藏数据库与规则实现细节
        db.rollback()
        logger.exception(
            "automatic_daily_guide_unavailable guide_date=%s error_type=%s",
            guide_date,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail={
                "code": "daily_guide_unavailable",
                "status": "unavailable",
                "guide_date": guide_date.isoformat(),
                "message": "今日五色暂时无法读取，请稍后重试",
            },
        ) from exc


@router.get(
    "/api/public-guides/today",
    response_model=PublicGuideInput,
    tags=[PUBLIC_TAG],
    summary="自动生成今日五色",
)
def public_today(db: Session = Depends(get_db)):
    """按北京时间读取当天结果，首次请求时自动计算并缓存。"""
    return _automatic_guide(beijing_today(), db, warm_week=True)


@router.get(
    "/api/public-guides/{guide_date}",
    response_model=PublicGuideInput,
    tags=[PUBLIC_TAG],
    summary="按日期自动生成五色内容",
)
def public_by_date(guide_date: date, db: Session = Depends(get_db)):
    """为指定日期返回相同规则、相同输入下可复现的结果。"""
    return _automatic_guide(guide_date, db)
