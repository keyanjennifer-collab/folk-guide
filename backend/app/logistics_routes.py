"""本人订单物流查询：发货记录与未来承运方轨迹使用独立字段。"""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .commerce_models import Order
from .database import get_db
from .models import User
from .order_routes import OrderStatus


router = APIRouter(tags=["商城交易"])


class LogisticsEvent(BaseModel):
    time: datetime
    title: str
    description: str = ""


class OrderLogistics(BaseModel):
    order_id: int
    order_number: str
    order_status: OrderStatus
    carrier: str | None
    tracking_number: str | None
    shipment_recorded: bool
    # 合作确定后由后端适配供应商，不能将录单时间伪装成揽收轨迹。
    tracking_status: Literal["not_shipped", "not_connected", "available", "temporarily_unavailable"]
    tracking_message: str
    tracking_updated_at: datetime | None = None
    tracking_events: list[LogisticsEvent] = Field(default_factory=list)
    order_events: list[LogisticsEvent]


def _utc(value: datetime) -> datetime:
    # 数据库无时区时间约定为 UTC；接口显式输出时区，避免手机误当成本地时间。
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@router.get("/api/orders/{order_id}/logistics", response_model=OrderLogistics, summary="查看本人订单物流信息")
def order_logistics(order_id: int, response: Response,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    order = db.scalar(select(Order).where(Order.id == order_id, Order.user_id == user.id))
    if order is None:
        raise HTTPException(404, "订单不存在")
    response.headers["Cache-Control"] = "private, no-store"

    events = []
    for timestamp, title, description in (
        (order.created_at, "订单已提交", ""),
        (order.paid_at, "付款成功", ""),
        (order.shipped_at, "商家已登记发货", "揽收与运输进度以快递公司信息为准。"),
        (order.completed_at, "买家已确认收货", ""),
        (order.cancelled_at, "订单已取消", ""),
        (order.refunded_at, "退款已完成", ""),
    ):
        if timestamp:
            events.append(LogisticsEvent(time=_utc(timestamp), title=title, description=description))
    events.sort(key=lambda event: event.time, reverse=True)
    shipment_recorded = bool(order.shipped_at or order.tracking_number)
    if shipment_recorded:
        message = "运输轨迹暂不可用。可凭运单号向快递公司查询，或联系售后客服协助。"
    elif order.status == "pending":
        message = "付款后我们会安排发货，发货后可在这里查看运单信息。"
    elif order.status in {"cancelled", "refunded"}:
        message = "这笔订单暂无发货记录。"
    elif order.status == "after_sale":
        message = "订单正在处理退款，暂无发货记录。如需帮助，请联系售后客服。"
    else:
        message = "商家尚未登记发货，发货后快递公司和运单号会显示在这里。"

    # 此阶段不调用任何第三方，不向外发送手机号或收货地址。
    # 未来供应商适配器在此填入真实 tracking_events / tracking_updated_at，
    # 通过 tracking_status 表达结果；查询不得直接修改交易状态或库存。
    return OrderLogistics(
        order_id=order.id, order_number=order.number, order_status=order.status,
        carrier=order.carrier, tracking_number=order.tracking_number,
        shipment_recorded=shipment_recorded,
        tracking_status="not_connected" if shipment_recorded else "not_shipped",
        tracking_message=message, order_events=events,
    )
