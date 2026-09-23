"""商城库存、地址、订单和支付事件模型。"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class ProductInventory(Base):
    """每个商品的可售、锁定和已售数量。"""

    __tablename__ = "product_inventory"
    product_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    available: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)
    sold: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ShippingAddress(Base):
    """用户收货地址；订单创建后另存快照，之后修改地址不影响历史订单。"""

    __tablename__ = "shipping_addresses"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    recipient_name: Mapped[str] = mapped_column(String(64))
    phone: Mapped[str] = mapped_column(String(32))
    province: Mapped[str] = mapped_column(String(64))
    city: Mapped[str] = mapped_column(String(64))
    district: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(String(255))
    postal_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Order(Base):
    """订单主表；商品和收件信息都保存下单时快照。"""

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_orders_user_idempotency"),
        Index("ix_orders_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    number: Mapped[str] = mapped_column(String(64), unique=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    subtotal_fen: Mapped[int] = mapped_column(Integer, default=0)
    shipping_fee_fen: Mapped[int] = mapped_column(Integer, default=0)
    total_fen: Mapped[int] = mapped_column(Integer)
    items_json: Mapped[str] = mapped_column(Text)
    receiver_name: Mapped[str] = mapped_column(String(64), default="")
    receiver_phone: Mapped[str] = mapped_column(String(32), default="")
    receiver_address: Mapped[str] = mapped_column(String(512), default="")
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True)
    carrier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    wx_transaction_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    payment_prepay_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    refund_number: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PaymentEvent(Base):
    """微信异步通知去重与审计记录；不保存支付密钥。"""

    __tablename__ = "payment_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    order_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload_digest: Mapped[str] = mapped_column(String(64))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
