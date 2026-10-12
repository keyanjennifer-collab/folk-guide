"""商城库存、地址、订单和支付事件模型。"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Product(Base):
    """商品主数据：名称、价格、图片与详情文案全部入库，由管理后台维护。

    价格和上下架状态以本表为准；小程序与下单接口只按 product_id 读取，
    不信任客户端提交的名称或金额。图片字段保存相对路径，客户端拼上
    ``/product-assets/`` 前缀即可访问。
    """

    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    price_fen: Mapped[int] = mapped_column(Integer, default=0)
    # 成本价（分），用于后台利润统计；不对外暴露给小程序。
    cost_fen: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str] = mapped_column(String(16), default="single", index=True)
    length_cm: Mapped[float] = mapped_column(default=0.0)
    weight_grams: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # 五行归属与品牌文案
    color: Mapped[str] = mapped_column(String(32), default="")
    element: Mapped[str] = mapped_column(String(32), default="")
    beast: Mapped[str] = mapped_column(String(64), default="")
    mood: Mapped[str] = mapped_column(String(128), default="")
    scent: Mapped[str] = mapped_column(String(255), default="")
    story: Mapped[str] = mapped_column(Text, default="")
    meaning: Mapped[str] = mapped_column(Text, default="")

    # 图片：主图、角标图、详情图库（JSON 数组）与色板（JSON 数组）。
    image: Mapped[str] = mapped_column(String(512), default="")
    emblem: Mapped[str] = mapped_column(String(512), default="")
    gallery_json: Mapped[str] = mapped_column(Text, default="[]")
    swatches_json: Mapped[str] = mapped_column(Text, default="[]")

    # 扩展详情段落，保留给「使用与养护」等可编辑富文本。
    detail_json: Mapped[str] = mapped_column(Text, default="{}")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
