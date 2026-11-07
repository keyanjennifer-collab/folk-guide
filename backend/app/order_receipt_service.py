"""商家确认发货满十天后，自动完成仍在等待收货的商城订单。"""

import asyncio
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, update

from .admin_models import AdminAuditLog
from .commerce_models import Order
from .database import SessionLocal
from .time_service import utc_now_naive

logger = logging.getLogger(__name__)
AUTO_RECEIPT_DAYS = 10


def complete_due_orders(sessions=SessionLocal, *, current_time: datetime | None = None) -> int:
    current = current_time if current_time is not None else utc_now_naive()
    conditions = (
        Order.status == "shipped",
        Order.shipped_at <= current - timedelta(days=AUTO_RECEIPT_DAYS),
        Order.refund_number.is_(None),
        Order.refunded_at.is_(None),
    )
    with sessions() as db:
        due_ids = select(Order.id).where(*conditions).order_by(Order.id).limit(200)
        # 条件更新与审计在同一事务中，防止多进程重复完成，或覆盖并发退款。
        completed = db.execute(update(Order).where(Order.id.in_(due_ids), *conditions).values(
            status="completed", completed_at=current, updated_at=current,
        ).returning(Order.id, Order.number).execution_options(synchronize_session=False)).all()
        for order_id, number in completed:
            db.add(AdminAuditLog(
                operator_username="system", action="order_auto_complete",
                target_type="order", target_id=str(order_id),
                detail_json=json.dumps({"order_number": number, "days_after_shipping": AUTO_RECEIPT_DAYS}),
            ))
        db.commit()
        return len(completed)


async def worker_loop() -> None:
    # 启动时补查，之后每分钟检查；停机期间到期的订单也会继续处理。
    while True:
        try:
            await asyncio.to_thread(complete_due_orders)
        except Exception:
            logger.exception("Automatic order receipt check failed; will retry")
        await asyncio.sleep(60)
