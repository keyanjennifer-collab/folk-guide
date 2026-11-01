"""管理员生成运单，后台持久化处理；取号与确认发货分别执行。

运单生成/取消支持两种渠道：
- 微信物流助手（默认）：与小程序深度集成，物流轨迹推送由微信负责
- 快递100电子面单（可选）：支持取消运单、回收面单，需开通中通月结账号
两者并存，由 KUAIDI100_ENABLED 开关切换发货渠道，物流轨迹始终走微信推送。
"""

import asyncio
import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import kuaidi100_client as kd100
from . import wechat_express as api
from .admin_models import AdminAuditLog
from .commerce_models import LogisticsQueryCache, Order, WechatExpressOrder
from .config import get_settings
from .database import SessionLocal
from .models import User

logger = logging.getLogger(__name__)
QUERY_INTERVAL = timedelta(minutes=10, seconds=1)
LEASE_SECONDS = 90
RETRY_DELAY_LONG = timedelta(minutes=5)


class LogisticsEvent(BaseModel):
    time: datetime
    title: str
    description: str = ""


class TrackingResult(BaseModel):
    status: Literal["not_connected", "available", "temporarily_unavailable"]
    message: str
    updated_at: datetime | None = None
    events: list[LogisticsEvent] = Field(default_factory=list)


def _now() -> datetime:
    return datetime.utcnow()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _remote_order_id(number: str, attempt_round: int) -> str:
    return number if attempt_round == 1 else f"{number}_R{attempt_round}"


def _audit(db: Session, order: Order, action: str) -> None:
    db.add(AdminAuditLog(operator_username="wechat-express", action=action,
        target_type="order", target_id=str(order.id), detail_json=json.dumps({
            "order_number": order.number, "carrier": order.carrier, "tracking_number": order.tracking_number}, ensure_ascii=False)))


def _openid_of(db: Session, order: Order) -> str:
    value = db.scalar(select(User.openid).where(User.id == order.user_id))
    if not value:
        raise api.WechatExpressError("买家微信账号缺失，请核对原订单")
    return value


def _cancelled(db: Session, order: Order, row: WechatExpressOrder) -> None:
    if not order.shipped_at and order.tracking_number == row.waybill_id:
        order.carrier, order.tracking_number = None, None
    row.status, row.next_action, row.message = "cancelled", "none", "运单已停止或已确认撤销，可重新生成或继续退款"
    row.lease_token, row.lease_until = "", None


def save_waybill(db: Session, order: Order, row: WechatExpressOrder, number: str) -> None:
    row.waybill_id = number  # 即使本地冲突，也保留外部单号供核对和撤销。
    if order.status == "paid" and not order.refund_number and (not order.tracking_number or order.tracking_number == number):
        order.carrier, order.tracking_number = row.carrier_name, number
        row.status, row.message = "ordered", "已取号待发货，请打印面单、打包后确认发货"
        _audit(db, order, "wechat_waybill_created")
    else:
        row.status, row.message = "conflict", "微信已有运单，但订单状态或原单号冲突，请核对包裹与售后"
        _audit(db, order, "wechat_waybill_conflict")
    row.next_action = "none"
    if row.cancel_requested and row.status == "ordered":
        row.status, row.next_action, row.next_attempt_at = "cancelling", "cancel", _now()


def _claim(db: Session) -> dict | None:
    now = _now()
    row = db.scalar(select(WechatExpressOrder).where(
        WechatExpressOrder.next_action.in_(["create", "verify", "cancel"]),
        WechatExpressOrder.next_attempt_at <= now,
        or_(WechatExpressOrder.lease_until.is_(None), WechatExpressOrder.lease_until <= now),
    ).order_by(WechatExpressOrder.next_attempt_at, WechatExpressOrder.order_id).limit(1))
    if row is None:
        return None
    order = db.scalar(select(Order).where(Order.id == row.order_id).with_for_update())
    db.refresh(row)
    if row.next_action == "none" or row.next_attempt_at > now or (row.lease_until and row.lease_until > now):
        db.rollback()
        return None
    if row.status == "creating":
        # 崩溃恢复只补查：上次请求可能已由微信受理。
        row.status, row.next_action = "unknown", "verify"
    if row.next_action == "create":
        if order.status != "paid" or order.refund_number or order.tracking_number or row.cancel_requested:
            _cancelled(db, order, row)
            db.commit()
            return None
        row.remote_order_id = _remote_order_id(order.number, row.attempt_round)
        row.delivery_id = get_settings().wechat_express_delivery_id.strip().upper()
        row.carrier_name = get_settings().wechat_express_carrier_name.strip()
        row.status, row.message = "creating", "正在向微信申请运单"
        row.attempts += 1
    lease = secrets.token_hex(16)
    claimed = db.execute(update(WechatExpressOrder).where(WechatExpressOrder.order_id == row.order_id,
        or_(WechatExpressOrder.lease_until.is_(None), WechatExpressOrder.lease_until <= now)
    ).values(lease_token=lease, lease_until=now + timedelta(seconds=LEASE_SECONDS)).execution_options(synchronize_session="fetch")).rowcount
    if not claimed:
        db.rollback()
        return None
    job = {"order_id": row.order_id, "action": row.next_action, "lease": lease,
        "remote": row.remote_order_id, "delivery_id": row.delivery_id, "waybill_id": row.waybill_id}
    row.next_attempt_at = now + timedelta(seconds=LEASE_SECONDS)
    db.commit()  # 在任何网络请求之前落库编号、次数及租约。
    return job


def _execute(sessions, job: dict) -> None:
    result, error = None, None
    try:
        with sessions() as db:
            order = db.get(Order, job["order_id"])
            row = db.get(WechatExpressOrder, job["order_id"])
            if row is None or row.lease_token != job["lease"]:
                return
            openid = _openid_of(db, order)
            if job["action"] == "create":
                # 关键决策：运单生成走快递100还是微信物流助手
                # 物流轨迹始终由微信物流助手推送，但运单号生成渠道可切换
                if kd100.configured():
                    # 快递100：直接生成运单号，下单数据由快递100构造
                    order = db.scalar(select(Order).where(Order.id == job["order_id"]).with_for_update().execution_options(populate_existing=True))
                    db.refresh(row)
                    if row.lease_token != job["lease"]:
                        return
                    if row.cancel_requested or order.status != "paid" or order.refund_number:
                        _cancelled(db, order, row)
                        db.commit()
                        return
                    db.commit()
                    waybill = kd100.create_waybill(db, order, job["remote"], json.loads(row.package_json))
                    result = {"waybill_id": waybill}
                else:
                    payload = api.order_payload(db, order, job["remote"], openid, json.loads(row.package_json))
                    # 配置/绑定检查可能耗时；真正下单前再检查撤销请求。
                    order = db.scalar(select(Order).where(Order.id == job["order_id"]).with_for_update().execution_options(populate_existing=True))
                    db.refresh(row)
                    if row.lease_token != job["lease"]:
                        return
                    if row.cancel_requested or order.status != "paid" or order.refund_number:
                        _cancelled(db, order, row)
                        db.commit()
                        return
                    db.commit()
                    result = {"waybill_id": api.create_waybill(db, payload)}
            elif job["action"] == "verify":
                # 仅微信物流助手需要 verify（崩溃恢复补查）；快递100下单是同步的，无 verify
                if kd100.configured():
                    # 快递100下单同步返回运单号，无需补查；unknown 状态保持异步任务
                    result = {"order_status": 0, "waybill_id": row.waybill_id}
                else:
                    result = api.lookup_waybill(db, job["delivery_id"], job["remote"])
            else:
                # cancel：优先走快递100（支持取消运单）；未启用则走微信（中通会拒绝）
                if kd100.configured() and row.waybill_id:
                    kd100.cancel_waybill(row.waybill_id, job["remote"])
                else:
                    api.cancel_waybill(db, job["delivery_id"], job["remote"], job["waybill_id"], openid)
    except (api.WechatExpressError, kd100.Kuaidi100Error) as exc:
        error = exc
    with sessions() as db:
        order = db.scalar(select(Order).where(Order.id == job["order_id"]).with_for_update())
        row = db.get(WechatExpressOrder, job["order_id"], populate_existing=True)
        if row.lease_token != job["lease"]:
            return
        row.lease_token, row.lease_until = "", None
        row.next_attempt_at = _now() + RETRY_DELAY_LONG
        if error:
            row.message = error.message
            if job["action"] != "create" or error.uncertain:
                row.status, row.next_action = "unknown", "verify"
            else:
                row.status, row.next_action = "failed", "none"
                if row.cancel_requested:
                    _cancelled(db, order, row)
        elif job["action"] == "cancel" or (job["action"] == "verify" and result.get("order_status") == 1):
            _cancelled(db, order, row)
        else:
            save_waybill(db, order, row, result["waybill_id"])
        db.commit()


def run_batch(sessions=SessionLocal, limit: int = 10) -> None:
    # 启用快递100时不检查微信物流助手配置（这是微信侧负责，由 wechat_express_routes 单独检查）
    if not kd100.configured() and (not get_settings().wechat_express_enabled or not api.configured()):
        return
    # 付款本身不生成运单；任务由管理员按钮创建。
    for _ in range(limit):
        with sessions() as db:
            job = _claim(db)
        if job is None:
            break
        _execute(sessions, job)


async def worker_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(run_batch)
        except Exception:
            logger.error("wechat express worker interrupted; persisted jobs retained")
        await asyncio.sleep(10)


def request_cancel(db: Session, order: Order, row: WechatExpressOrder) -> None:
    row.cancel_requested = True
    if row.status in {"queued", "failed"} and not row.waybill_id:
        _cancelled(db, order, row)
    elif row.status == "ordered":
        # 快递100启用时：同步调用取消接口，成功则直接 cancelled
        if kd100.configured() and row.waybill_id:
            try:
                kd100.cancel_waybill(row.waybill_id, row.remote_order_id)
                _cancelled(db, order, row)
                return
            except kd100.Kuaidi100Error as exc:
                # 业务失败（运单已揽收等）保留原状态；guard_refund 兜底允许退款
                row.message = f"快递100取消失败：{exc.message}"
                return
        # 微信物流助手：异步任务，等待 worker 执行
        row.status, row.next_action, row.next_attempt_at = "cancelling", "cancel", _now()
    elif row.status == "unknown":
        row.next_action, row.next_attempt_at = "verify", _now()
    elif row.status == "conflict":
        raise HTTPException(409, "运单存在冲突，请先核对外部包裹和售后")
    # creating 保留租约，正在执行的请求收到结果后继续安排撤单。


def guard_refund(db: Session, order: Order) -> None:
    row = db.get(WechatExpressOrder, order.id)
    if row is None or row.status == "cancelled" or order.shipped_at:
        return
    # 未发货的订单：尝试撤销运单，但不因撤销失败而阻止退款
    # 快递100：同步调用取消接口，成功回收面单；中通支持取消运单
    # 微信物流助手：异步任务，中通不支持取消运单，会返回 failed 但不阻止退款
    request_cancel(db, order, row)
    if row.status == "cancelled":
        return
    # 撤销未确认（unknown/cancelling）：清空运单关联，允许退款
    if order.tracking_number and (not row.waybill_id or order.tracking_number == row.waybill_id):
        order.carrier, order.tracking_number = None, None
    db.commit()


def guard_manual_shipment(db: Session, order: Order, carrier: str, number: str) -> None:
    row = db.get(WechatExpressOrder, order.id)
    if row is None or row.status == "cancelled":
        return
    if row.status == "ordered" and not row.cancel_requested and carrier == row.carrier_name and number == row.waybill_id:
        return
    if row.status == "failed" and not row.waybill_id:
        row.next_action = "none"
        return
    raise HTTPException(409, "请先完成微信运单处理；确认发货必须使用已生成的原运单")


def get_tracking(db: Session, order: Order) -> TrackingResult:
    """买家物流页轨迹：仅本人订单调用；轨迹写入独立缓存，不改交易状态。"""
    s = get_settings()
    if not s.wechat_express_enabled or not api.configured():
        return TrackingResult(status="not_connected", message="运输轨迹暂不可用。可凭运单号向快递公司查询，或联系售后客服协助。")
    row = db.get(WechatExpressOrder, order.id)
    waybill_id = (order.tracking_number or "").strip()
    if not waybill_id or row is None or row.status != "ordered" or row.waybill_id != waybill_id or not row.remote_order_id:
        return TrackingResult(status="temporarily_unavailable", message="暂未查到运单信息，请稍后查看。")
    remote = row.remote_order_id
    openid = _openid_of(db, order)
    delivery_id = row.delivery_id
    fingerprint = _digest(f"{delivery_id}:{waybill_id}:{remote}")
    cache_key = _digest(f"wx:{delivery_id}:{waybill_id}")
    now = _now()
    cached_row = db.get(LogisticsQueryCache, cache_key)
    if cached_row is None:
        db.add(LogisticsQueryCache(cache_key=cache_key, next_query_at=now))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    claim_until = now + QUERY_INTERVAL
    claimed = db.execute(update(LogisticsQueryCache).where(
        LogisticsQueryCache.cache_key == cache_key, LogisticsQueryCache.next_query_at <= now,
    ).values(next_query_at=claim_until).execution_options(synchronize_session=False)).rowcount
    db.commit()
    cached_row = db.get(LogisticsQueryCache, cache_key, populate_existing=True)

    def _cached(row: LogisticsQueryCache) -> TrackingResult:
        if row.request_fingerprint != fingerprint:
            return TrackingResult(status="temporarily_unavailable", message="物流信息正在更新，请稍后刷新或联系售后客服。")
        return TrackingResult(
            status=row.tracking_status, message=row.tracking_message,
            updated_at=row.fetched_at.replace(tzinfo=timezone.utc) if row.fetched_at else None,
            events=[LogisticsEvent.model_validate(event) for event in json.loads(row.events_json)],
        )

    if not claimed:
        return _cached(cached_row)
    previous = _cached(cached_row)
    try:
        rows = api.query_track(db, delivery_id, remote, waybill_id, openid)
        events = [LogisticsEvent(time=row["time"], title=row["title"], description=row["description"]) for row in rows]
        result = TrackingResult(
            status="available" if events else "temporarily_unavailable",
            message="物流信息由微信物流助手提供。" if events else "暂未查到运输轨迹，快递揽收后信息可能延迟更新，请稍后查看。",
            updated_at=_now().replace(tzinfo=timezone.utc), events=events,
        )
    except api.WechatExpressError as exc:
        logger.warning("wechat express query failed: %s", exc.code)
        message = "物流查询暂时不可用，请稍后查看或联系售后客服。"
        if exc.code == "9300501":
            message = "暂未查到运输轨迹，快递揽收后信息可能延迟更新，请稍后查看。"
        if previous.events:
            message = "物流更新暂时失败，以下为上次查询记录，请稍后查看。"
        result = TrackingResult(status="temporarily_unavailable", message=message,
                                updated_at=previous.updated_at, events=previous.events)
    db.execute(update(LogisticsQueryCache).where(
        LogisticsQueryCache.cache_key == cache_key, LogisticsQueryCache.next_query_at == claim_until,
    ).values(
        request_fingerprint=fingerprint, tracking_status=result.status, tracking_message=result.message,
        events_json=json.dumps([event.model_dump(mode="json") for event in result.events], ensure_ascii=False),
        fetched_at=result.updated_at.replace(tzinfo=None) if result.updated_at else None,
        next_query_at=_now() + QUERY_INTERVAL,
    ).execution_options(synchronize_session=False))
    db.commit()
    return result
