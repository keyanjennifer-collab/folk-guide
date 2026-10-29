"""个人五色与测一测共用的七天体验、套装永久权益。

套装权益直接依据服务端已收款订单判断：历史购买自动生效，成功退款后
自动失效，多笔购买中仍有有效订单时保留权益，不额外维护一份容易失步的状态。
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .commerce_models import Order
from .models import AIServiceGrant, User
from .time_service import utc_now_naive

TRIAL_DAYS = 7
TRIAL_PLAN = "new_user_7_days"
LIFETIME_PLAN = "gift_lifetime"
GIFT_PRODUCT_ID = "gift"
ACCESS_REQUIRED_MESSAGE = "7天体验已结束，购买268元五色套装可获赠小程序全部功能的永久使用权。"


@dataclass(frozen=True)
class FeatureAccess:
    active: bool
    plan: str | None
    expires_at: datetime | None


def _contains_gift(items_json: str) -> bool:
    try:
        items = json.loads(items_json)
    except (TypeError, ValueError):
        return False
    return isinstance(items, list) and any(
        isinstance(item, dict) and item.get("product_id") == GIFT_PRODUCT_ID
        and isinstance(item.get("quantity"), int) and not isinstance(item["quantity"], bool)
        and item["quantity"] > 0
        for item in items
    )


def active_paid_access(db: Session, user_ids: list[int], now: datetime) -> dict[int, FeatureAccess]:
    """按批读取付费权益，套装永久权益优先；退款处理中仍保留，成功退款才撤销。"""
    if not user_ids:
        return {}
    grants = db.scalars(select(AIServiceGrant).where(
        AIServiceGrant.user_id.in_(user_ids), AIServiceGrant.start_at <= now,
        AIServiceGrant.end_at > now,
    ).order_by(AIServiceGrant.end_at.desc())).all()
    access: dict[int, FeatureAccess] = {}
    for grant in grants:
        access.setdefault(grant.user_id, FeatureAccess(True, grant.grant_type, grant.end_at))
    orders = db.execute(select(Order.user_id, Order.items_json).where(
        Order.user_id.in_(user_ids), Order.paid_at.is_not(None), Order.paid_at <= now,
        Order.refunded_at.is_(None), Order.cancelled_at.is_(None),
        Order.status.in_(("paid", "shipped", "completed", "after_sale")),
    )).all()
    for user_id, items_json in orders:
        if _contains_gift(items_json):
            access[user_id] = FeatureAccess(True, LIFETIME_PLAN, None)
    return access


def trial_access(user: User, now: datetime) -> FeatureAccess:
    trial_end = user.created_at + timedelta(days=TRIAL_DAYS)
    if user.created_at <= now < trial_end:
        return FeatureAccess(True, TRIAL_PLAN, trial_end)
    return FeatureAccess(False, None, None)


def feature_access_for_user(db: Session, user: User, now: datetime | None = None) -> FeatureAccess:
    now = now or utc_now_naive()
    paid = active_paid_access(db, [user.id], now)
    return paid.get(user.id) or trial_access(user, now)


def require_feature_access(db: Session, user: User) -> FeatureAccess:
    access = feature_access_for_user(db, user)
    if not access.active:
        raise HTTPException(403, detail={"code": "feature_access_required", "message": ACCESS_REQUIRED_MESSAGE})
    return access
