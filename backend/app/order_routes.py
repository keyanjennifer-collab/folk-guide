"""商城目录、收货地址、下单、支付、退款与本人订单接口。"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import re
import secrets
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import current_user
from .commerce_catalog import PRODUCTS, product_or_none
from .commerce_models import Order, PaymentEvent, ProductInventory, ShippingAddress
from .config import get_settings
from .database import get_db
from .models import User
from .wechat_pay import WechatPayError, close_payment, create_jsapi_payment, create_refund, jsapi_payment_params, verify_and_decrypt_notification


OrderStatus = Literal["pending", "paid", "shipped", "completed", "after_sale", "refunded", "cancelled"]
STATUSES = ("pending", "paid", "shipped", "completed", "after_sale", "refunded", "cancelled")
router = APIRouter(tags=["商城交易"])


class CatalogItemOutput(BaseModel):
    id: str
    name: str
    price_fen: int
    category: str
    length_cm: float
    weight_grams: int
    sale_mode: Literal["ready", "preorder"]
    available: int
    active: bool


class CatalogOutput(BaseModel):
    sale_enabled: bool
    sale_mode: Literal["ready", "preorder"]
    shipping_fee_fen: int
    free_shipping_threshold_fen: int
    merchant_name: str
    customer_service: str
    shipping_eta: str
    items: list[CatalogItemOutput]


class AddressInput(BaseModel):
    recipient_name: str = Field(min_length=2, max_length=64)
    phone: str = Field(min_length=7, max_length=32)
    province: str = Field(min_length=1, max_length=64)
    city: str = Field(min_length=1, max_length=64)
    district: str = Field(default="", max_length=64)
    detail: str = Field(min_length=2, max_length=255)
    postal_code: str | None = Field(default=None, max_length=16)
    is_default: bool = False

    @field_validator("recipient_name", "phone", "province", "city", "district", "detail", "postal_code")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        normalized = re.sub(r"[\s-]", "", value)
        if not re.fullmatch(r"\+?[0-9]{7,20}", normalized):
            raise ValueError("联系电话格式不正确")
        return normalized


class AddressOutput(AddressInput):
    id: int


class CheckoutItemInput(BaseModel):
    product_id: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, le=99)


class CheckoutInput(BaseModel):
    items: list[CheckoutItemInput] = Field(min_length=1, max_length=20)
    address_id: int
    idempotency_key: str = Field(min_length=8, max_length=64)
    remark: str | None = Field(default=None, max_length=200)

    @field_validator("idempotency_key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("幂等键格式不正确")
        return value


class OrderItem(BaseModel):
    product_id: str
    name: str
    quantity: int = Field(ge=1)
    unit_price_fen: int = Field(ge=0)
    subtotal_fen: int = Field(ge=0)
    sale_mode: Literal["ready", "preorder"] = "ready"
    shipping_eta: str = ""


class OrderOutput(BaseModel):
    id: int
    number: str
    status: OrderStatus
    subtotal_fen: int = Field(ge=0)
    shipping_fee_fen: int = Field(ge=0)
    total_fen: int = Field(ge=0)
    items: list[OrderItem]
    receiver_name: str
    receiver_phone: str
    receiver_address: str
    remark: str | None
    carrier: str | None
    tracking_number: str | None
    expires_at: datetime | None
    paid_at: datetime | None
    shipped_at: datetime | None
    refunded_at: datetime | None
    created_at: datetime


class OrderList(BaseModel):
    items: list[OrderOutput]
    counts: dict[str, int]
    has_more: bool


class PaymentOutput(BaseModel):
    mock: bool = False
    order_id: int
    timeStamp: str | None = None
    nonceStr: str | None = None
    package: str | None = None
    signType: str | None = None
    paySign: str | None = None


class RefundInput(BaseModel):
    reason: str = Field(default="用户申请整单退款", min_length=2, max_length=80)


def ensure_inventory_rows(db: Session) -> None:
    """为代码目录中的新品补库存记录；正式盘点后可在后台覆盖数量。"""
    existing = set(db.scalars(select(ProductInventory.product_id)).all())
    settings = get_settings()
    if settings.commerce_sale_mode not in {"ready", "preorder"}:
        raise HTTPException(status_code=500, detail="商城销售模式配置无效")
    # 测试环境必须从零库存开始，生产/本机新库按当前首批盘点数量初始化。
    initial_stock = 0 if settings.testing else max(0, settings.commerce_initial_stock)
    for product in PRODUCTS:
        if product.id not in existing:
            db.add(ProductInventory(product_id=product.id, available=initial_stock, reserved=0, sold=0, active=product.active))
    if len(existing) != len(PRODUCTS):
        db.commit()


def _items(order: Order) -> list[dict[str, Any]]:
    rows = json.loads(order.items_json)
    for item in rows:
        item.setdefault("subtotal_fen", int(item["unit_price_fen"]) * int(item["quantity"]))
    return rows


def output(order: Order) -> OrderOutput:
    return OrderOutput(
        id=order.id, number=order.number, status=order.status,
        subtotal_fen=order.subtotal_fen, shipping_fee_fen=order.shipping_fee_fen,
        total_fen=order.total_fen, items=_items(order),
        receiver_name=order.receiver_name, receiver_phone=order.receiver_phone,
        receiver_address=order.receiver_address, remark=order.remark,
        carrier=order.carrier, tracking_number=order.tracking_number,
        expires_at=order.expires_at, paid_at=order.paid_at, shipped_at=order.shipped_at,
        refunded_at=order.refunded_at, created_at=order.created_at,
    )


def address_output(address: ShippingAddress) -> AddressOutput:
    return AddressOutput.model_validate({column.name: getattr(address, column.name) for column in ShippingAddress.__table__.columns})


def _change_stock(db: Session, product_id: str, *, available: int = 0, reserved: int = 0, sold: int = 0,
                  require_available: int = 0, require_reserved: int = 0, require_sold: int = 0) -> None:
    """用带条件的单条 UPDATE 修改库存，依靠数据库行锁避免并发超卖。"""
    conditions = [ProductInventory.product_id == product_id]
    if require_available:
        conditions.append(ProductInventory.available >= require_available)
    if require_reserved:
        conditions.append(ProductInventory.reserved >= require_reserved)
    if require_sold:
        conditions.append(ProductInventory.sold >= require_sold)
    result = db.execute(update(ProductInventory).where(*conditions).values(
        available=ProductInventory.available + available,
        reserved=ProductInventory.reserved + reserved,
        sold=ProductInventory.sold + sold,
        updated_at=datetime.utcnow(),
    ))
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="商品库存不足或库存状态已变化")


def _reserve_order_stock(db: Session, rows: list[dict[str, Any]]) -> None:
    for item in rows:
        quantity = int(item["quantity"])
        _change_stock(db, item["product_id"], available=-quantity, reserved=quantity, require_available=quantity)


def _release_order_stock(db: Session, order: Order) -> None:
    for item in _items(order):
        quantity = int(item["quantity"])
        _change_stock(db, item["product_id"], available=quantity, reserved=-quantity, require_reserved=quantity)


def _settle_order_stock(db: Session, order: Order) -> None:
    for item in _items(order):
        quantity = int(item["quantity"])
        _change_stock(db, item["product_id"], reserved=-quantity, sold=quantity, require_reserved=quantity)


def _restock_refund(db: Session, order: Order) -> None:
    for item in _items(order):
        quantity = int(item["quantity"])
        _change_stock(db, item["product_id"], available=quantity, sold=-quantity, require_sold=quantity)


def expire_pending_orders(db: Session, user_id: int | None = None) -> int:
    """认领并取消超时订单；只有成功把 pending 改为 cancelled 的请求才释放库存。"""
    now = datetime.utcnow()
    query = select(Order).where(Order.status == "pending", Order.expires_at.is_not(None), Order.expires_at <= now)
    if user_id is not None:
        query = query.where(Order.user_id == user_id)
    expired = list(db.scalars(query).all())
    for order in expired:
        claimed = db.execute(update(Order).where(Order.id == order.id, Order.status == "pending").values(
            status="cancelled", cancelled_at=now, updated_at=now,
        ))
        if claimed.rowcount == 1:
            _release_order_stock(db, order)
    if expired:
        db.commit()
    return len(expired)


def _order_number() -> str:
    return datetime.utcnow().strftime("WS%Y%m%d%H%M%S") + secrets.token_hex(4).upper()


def _refund_number(order: Order) -> str:
    return f"RF{order.number[2:]}"[:64]


def _owned_order(db: Session, order_id: int, user_id: int) -> Order:
    order = db.scalar(select(Order).where(Order.id == order_id, Order.user_id == user_id))
    if order is None:
        raise HTTPException(404, "订单不存在")
    return order


@router.get("/api/catalog", response_model=CatalogOutput, summary="读取正式商品价格与库存")
def catalog(db: Session = Depends(get_db)):
    ensure_inventory_rows(db)
    # 商品页本身也会触发过期订单释放，避免无人查看旧订单时库存长期被锁住。
    expire_pending_orders(db)
    inventory = {row.product_id: row for row in db.scalars(select(ProductInventory)).all()}
    settings = get_settings()
    return CatalogOutput(
        sale_enabled=settings.commerce_enabled,
        sale_mode=settings.commerce_sale_mode,
        shipping_fee_fen=settings.commerce_shipping_fee_fen,
        free_shipping_threshold_fen=settings.commerce_free_shipping_threshold_fen,
        merchant_name=settings.commerce_merchant_name,
        customer_service=settings.commerce_customer_service,
        shipping_eta=settings.commerce_shipping_eta,
        items=[CatalogItemOutput(
            id=product.id, name=product.name, price_fen=product.price_fen, category=product.category,
            length_cm=product.length_cm, weight_grams=product.weight_grams,
            sale_mode=settings.commerce_sale_mode,
            available=max(0, inventory[product.id].available),
            active=bool(product.active and inventory[product.id].active),
        ) for product in PRODUCTS],
    )


@router.get("/api/addresses", response_model=list[AddressOutput], summary="读取本人收货地址")
def list_addresses(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(ShippingAddress).where(ShippingAddress.user_id == user.id).order_by(
        ShippingAddress.is_default.desc(), ShippingAddress.updated_at.desc())).all()
    return [address_output(row) for row in rows]


def _set_default(db: Session, user_id: int, address: ShippingAddress, requested: bool) -> None:
    has_address = db.scalar(select(func.count(ShippingAddress.id)).where(ShippingAddress.user_id == user_id)) or 0
    if requested or has_address <= 1:
        db.execute(update(ShippingAddress).where(ShippingAddress.user_id == user_id).values(is_default=False))
        address.is_default = True


@router.post("/api/addresses", response_model=AddressOutput, status_code=201, summary="新增收货地址")
def create_address(data: AddressInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    address = ShippingAddress(user_id=user.id, **data.model_dump(exclude={"is_default"}))
    db.add(address)
    db.flush()
    _set_default(db, user.id, address, data.is_default)
    db.commit()
    db.refresh(address)
    return address_output(address)


@router.put("/api/addresses/{address_id}", response_model=AddressOutput, summary="修改收货地址")
def update_address(address_id: int, data: AddressInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    address = db.scalar(select(ShippingAddress).where(ShippingAddress.id == address_id, ShippingAddress.user_id == user.id))
    if not address:
        raise HTTPException(404, "收货地址不存在")
    for name, value in data.model_dump(exclude={"is_default"}).items():
        setattr(address, name, value)
    _set_default(db, user.id, address, data.is_default)
    db.commit()
    db.refresh(address)
    return address_output(address)


@router.delete("/api/addresses/{address_id}", status_code=204, summary="删除收货地址")
def delete_address(address_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    address = db.scalar(select(ShippingAddress).where(ShippingAddress.id == address_id, ShippingAddress.user_id == user.id))
    if not address:
        raise HTTPException(404, "收货地址不存在")
    was_default = address.is_default
    db.delete(address)
    db.flush()
    if was_default:
        replacement = db.scalar(select(ShippingAddress).where(ShippingAddress.user_id == user.id).order_by(ShippingAddress.id.desc()))
        if replacement:
            replacement.is_default = True
    db.commit()


@router.post("/api/orders", response_model=OrderOutput, status_code=201, summary="创建订单并锁定库存")
def create_order(data: CheckoutInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """按商品 ID 和数量创建订单；名称、价格、运费均由服务端重新生成。"""
    settings = get_settings()
    if not settings.commerce_enabled:
        raise HTTPException(503, "商城尚未开售")
    ensure_inventory_rows(db)
    expire_pending_orders(db)
    existing = db.scalar(select(Order).where(Order.user_id == user.id, Order.idempotency_key == data.idempotency_key))
    if existing:
        return output(existing)
    address = db.scalar(select(ShippingAddress).where(ShippingAddress.id == data.address_id, ShippingAddress.user_id == user.id))
    if not address:
        raise HTTPException(422, "请选择有效的收货地址")
    # 合并重复商品行，避免客户端用多行绕过单款数量上限。
    quantities: dict[str, int] = {}
    for requested in data.items:
        quantities[requested.product_id] = quantities.get(requested.product_id, 0) + requested.quantity
        if quantities[requested.product_id] > 99:
            raise HTTPException(422, "单款商品一次最多购买99件")
    inventory = {row.product_id: row for row in db.scalars(select(ProductInventory)).all()}
    rows: list[dict[str, Any]] = []
    for product_id, quantity in quantities.items():
        product = product_or_none(product_id)
        stock = inventory.get(product_id)
        if not product or not product.active or not stock or not stock.active:
            raise HTTPException(409, "购物袋中有商品已经下架")
        rows.append({
            "product_id": product.id, "name": product.name, "quantity": quantity,
            "unit_price_fen": product.price_fen, "subtotal_fen": product.price_fen * quantity,
            "sale_mode": settings.commerce_sale_mode, "shipping_eta": settings.commerce_shipping_eta,
        })
    subtotal = sum(item["subtotal_fen"] for item in rows)
    shipping = 0 if subtotal >= settings.commerce_free_shipping_threshold_fen else settings.commerce_shipping_fee_fen
    now = datetime.utcnow()
    try:
        # 库存锁定和订单写入属于同一事务，任一步失败都会整体回滚。
        _reserve_order_stock(db, rows)
        order = Order(
            user_id=user.id, number=_order_number(), idempotency_key=data.idempotency_key,
            status="pending", subtotal_fen=subtotal, shipping_fee_fen=shipping, total_fen=subtotal + shipping,
            items_json=json.dumps(rows, ensure_ascii=False, separators=(",", ":")),
            receiver_name=address.recipient_name, receiver_phone=address.phone,
            receiver_address=" ".join(filter(None, [address.province, address.city, address.district, address.detail])),
            remark=(data.remark or "").strip() or None,
            expires_at=now + timedelta(minutes=max(5, settings.commerce_pending_minutes)),
        )
        db.add(order)
        db.commit()
        db.refresh(order)
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(Order).where(Order.user_id == user.id, Order.idempotency_key == data.idempotency_key))
        if existing:
            return output(existing)
        raise HTTPException(409, "订单提交冲突，请重试")
    except Exception:
        db.rollback()
        raise
    return output(order)


@router.get("/api/orders", response_model=OrderList, summary="读取本人订单")
def list_orders(
    status: OrderStatus | None = None,
    offset: int = Query(0, ge=0, le=10000), limit: int = Query(20, ge=1, le=50),
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    expire_pending_orders(db, user.id)
    owner = Order.user_id == user.id
    counts = {name: 0 for name in STATUSES}
    counts.update(dict(db.execute(select(Order.status, func.count(Order.id)).where(owner).group_by(Order.status)).all()))
    query = select(Order).where(owner)
    if status:
        query = query.where(Order.status == status)
    rows = db.scalars(query.order_by(Order.created_at.desc(), Order.id.desc()).offset(offset).limit(limit + 1)).all()
    return {"items": [output(row) for row in rows[:limit]], "counts": counts, "has_more": len(rows) > limit}


@router.get("/api/orders/{order_id}", response_model=OrderOutput, summary="读取本人单个订单")
def get_order(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    expire_pending_orders(db, user.id)
    return output(_owned_order(db, order_id, user.id))


@router.post("/api/orders/{order_id}/pay", response_model=PaymentOutput, summary="发起微信支付")
def pay_order(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """生成小程序调起支付的短期参数；重复点击时复用尚未过期的 prepay_id。"""
    expire_pending_orders(db, user.id)
    order = _owned_order(db, order_id, user.id)
    if order.status != "pending":
        raise HTTPException(409, "当前订单不能支付")
    try:
        if order.payment_prepay_id and get_settings().wechat_pay_mode == "wechat":
            result = jsapi_payment_params(order.payment_prepay_id)
        else:
            result = create_jsapi_payment(order.number, "五色知时香品", order.total_fen, user.openid, order.expires_at)
    except WechatPayError as exc:
        raise HTTPException(502, str(exc)) from exc
    order.payment_prepay_id = str(result.get("prepay_id") or "") or order.payment_prepay_id
    db.commit()
    return PaymentOutput(order_id=order.id, **{key: value for key, value in result.items() if key != "prepay_id"})


@router.post("/api/orders/{order_id}/mock-pay", response_model=OrderOutput, summary="开发环境模拟支付", include_in_schema=False)
def mock_pay_order(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    settings = get_settings()
    if settings.environment == "production" or settings.wechat_pay_mode != "mock":
        raise HTTPException(404, "接口不存在")
    order = _owned_order(db, order_id, user.id)
    if order.status == "pending":
        _settle_order_stock(db, order)
        order.status = "paid"
        order.paid_at = datetime.utcnow()
        order.wx_transaction_id = f"MOCK-{order.number}"
        db.commit()
    return output(order)


@router.post("/api/orders/{order_id}/cancel", response_model=OrderOutput, summary="取消待付款订单")
def cancel_order(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    order = db.scalar(select(Order).where(Order.id == order_id, Order.user_id == user.id).with_for_update())
    if not order:
        raise HTTPException(404, "订单不存在")
    if order.status != "pending":
        raise HTTPException(409, "只有待付款订单可以取消")
    if order.payment_prepay_id:
        try:
            close_payment(order.number)
        except WechatPayError as exc:
            db.rollback()
            raise HTTPException(502, f"关闭微信支付订单失败：{exc}") from exc
    _release_order_stock(db, order)
    order.status = "cancelled"
    order.cancelled_at = datetime.utcnow()
    db.commit()
    return output(order)


@router.post("/api/orders/{order_id}/refund", response_model=OrderOutput, summary="申请未发货订单整单退款")
def refund_order(order_id: int, data: RefundInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """仅允许待发货订单整单退款；发货后必须进入人工售后流程。"""
    order = db.scalar(select(Order).where(Order.id == order_id, Order.user_id == user.id).with_for_update())
    if not order:
        raise HTTPException(404, "订单不存在")
    if order.status != "paid":
        raise HTTPException(409, "只有已付款且未发货订单可以直接申请整单退款")
    refund_number = order.refund_number or _refund_number(order)
    try:
        result = create_refund(order.number, refund_number, order.total_fen, data.reason)
    except WechatPayError as exc:
        raise HTTPException(502, str(exc)) from exc
    order.refund_number = refund_number
    if result.get("mock") and result.get("status") == "SUCCESS":
        _restock_refund(db, order)
        order.status = "refunded"
        order.refunded_at = datetime.utcnow()
    else:
        order.status = "after_sale"
    db.commit()
    return output(order)


@router.post("/api/orders/{order_id}/complete", response_model=OrderOutput, summary="确认收货")
def complete_order(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    order = _owned_order(db, order_id, user.id)
    if order.status != "shipped":
        raise HTTPException(409, "只有已发货订单可以确认收货")
    order.status = "completed"
    order.completed_at = datetime.utcnow()
    db.commit()
    return output(order)


def _record_event(db: Session, event: dict[str, Any], body: bytes) -> PaymentEvent | None:
    event_id = str(event.get("id") or "")
    if not event_id:
        raise WechatPayError("微信支付通知缺少事件编号")
    if db.scalar(select(PaymentEvent).where(PaymentEvent.event_id == event_id)):
        return None
    record = PaymentEvent(
        event_id=event_id, event_type=str(event.get("event_type") or ""),
        payload_digest=hashlib.sha256(body).hexdigest(),
    )
    db.add(record)
    db.flush()
    return record


@router.post("/api/payments/wechat/notify", summary="接收微信支付结果通知")
async def wechat_payment_notify(request: Request, db: Session = Depends(get_db)):
    """处理微信异步通知；前端支付成功回调不能直接改变订单状态。"""
    body = await request.body()
    try:
        event = verify_and_decrypt_notification(dict(request.headers), body)
        # 微信会重试通知，event_id 唯一约束保证库存和订单状态只处理一次。
        record = _record_event(db, event, body)
        if record is None:
            return {"code": "SUCCESS", "message": "成功"}
        resource = event["resource_plaintext"]
        event_type = str(event.get("event_type") or "")
        order_number = str(resource.get("out_trade_no") or "")
        record.order_number = order_number or None
        order = db.scalar(select(Order).where(Order.number == order_number).with_for_update())
        if not order:
            raise WechatPayError("通知中的订单不存在")
        settings = get_settings()
        if resource.get("mchid") and resource.get("mchid") != settings.wechat_pay_mch_id:
            raise WechatPayError("通知商户号不匹配")
        if resource.get("appid") and resource.get("appid") != settings.wechat_app_id:
            raise WechatPayError("通知应用编号不匹配")
        if event_type == "TRANSACTION.SUCCESS":
            total = int((resource.get("amount") or {}).get("total", -1))
            if resource.get("trade_state") != "SUCCESS" or total != order.total_fen:
                raise WechatPayError("支付状态或金额不匹配")
            if order.status == "pending":
                _settle_order_stock(db, order)
                order.status = "paid"
                order.paid_at = datetime.utcnow()
            elif order.status == "cancelled":
                order.status = "after_sale"
                order.paid_at = datetime.utcnow()
                order.refund_number = order.refund_number or _refund_number(order)
                # 取消与支付极端并发时，立即发起原路退款；若网关失败则返回失败让微信重试。
                create_refund(order.number, order.refund_number, order.total_fen, "订单取消后支付，自动退款")
            order.wx_transaction_id = str(resource.get("transaction_id") or "") or order.wx_transaction_id
        elif event_type == "REFUND.SUCCESS":
            if resource.get("refund_status") != "SUCCESS" or str(resource.get("out_refund_no") or "") != order.refund_number:
                raise WechatPayError("退款状态或退款单号不匹配")
            if order.status == "after_sale":
                # 过期取消后极少数迟到支付没有占用已售库存，退款时不能重复回补。
                if order.cancelled_at is None:
                    _restock_refund(db, order)
                order.status = "refunded"
                order.refunded_at = datetime.utcnow()
        record.processed_at = datetime.utcnow()
        db.commit()
        return {"code": "SUCCESS", "message": "成功"}
    except IntegrityError:
        db.rollback()
        return {"code": "SUCCESS", "message": "成功"}
    except WechatPayError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc


# 保留旧测试和调用方的导入路径。
__all__ = ["Order", "OrderOutput", "output", "router"]
