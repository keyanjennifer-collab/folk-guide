"""本人订单只读接口。订单只能由后续服务端交易流程写入，客户端不能伪造支付状态。"""
from datetime import datetime
from typing import Literal
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import ForeignKey, Integer, String, Text, DateTime, func, select
from sqlalchemy.orm import Mapped, mapped_column, Session

from .auth import current_user
from .database import Base, get_db
from .models import User

OrderStatus = Literal["pending", "paid", "shipped", "completed", "after_sale", "cancelled"]
STATUSES = ("pending", "paid", "shipped", "completed", "after_sale", "cancelled")
router = APIRouter(prefix="/api/orders", tags=["我的订单"])


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    number: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    total_fen: Mapped[int] = mapped_column(Integer)
    items_json: Mapped[str] = mapped_column(Text)
    carrier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OrderItem(BaseModel):
    product_id: str
    name: str
    quantity: int = Field(ge=1)
    unit_price_fen: int = Field(ge=0)


class OrderOutput(BaseModel):
    id: int
    number: str
    status: OrderStatus
    total_fen: int = Field(ge=0)
    items: list[OrderItem]
    carrier: str | None
    tracking_number: str | None
    created_at: datetime


class OrderList(BaseModel):
    items: list[OrderOutput]
    counts: dict[str, int]
    has_more: bool


def output(order: Order) -> OrderOutput:
    return OrderOutput(
        id=order.id, number=order.number, status=order.status,
        total_fen=order.total_fen, items=json.loads(order.items_json),
        carrier=order.carrier, tracking_number=order.tracking_number,
        created_at=order.created_at,
    )


@router.get("", response_model=OrderList)
def list_orders(
    status: OrderStatus | None = None,
    offset: int = Query(0, ge=0, le=10000),
    limit: int = Query(20, ge=1, le=50),
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    owner = Order.user_id == user.id
    counts = {name: 0 for name in STATUSES}
    counts.update(dict(db.execute(select(Order.status, func.count(Order.id)).where(owner).group_by(Order.status)).all()))
    query = select(Order).where(owner)
    if status:
        query = query.where(Order.status == status)
    rows = db.scalars(query.order_by(Order.created_at.desc(), Order.id.desc()).offset(offset).limit(limit + 1)).all()
    return {"items": [output(row) for row in rows[:limit]], "counts": counts, "has_more": len(rows) > limit}


@router.get("/{order_id}", response_model=OrderOutput)
def get_order(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    order = db.scalar(select(Order).where(Order.id == order_id, Order.user_id == user.id))
    if order is None:
        raise HTTPException(404, "订单不存在")
    return output(order)
