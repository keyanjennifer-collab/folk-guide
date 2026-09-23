"""第一期开售后台：库存、订单查询和人工发货。"""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_auth import (
    AdminIdentity,
    audit_admin_action,
    ensure_admin_role,
    require_admin_identity,
    require_admin_write,
    resolve_admin_session,
)
from .admin_auth_routes import admin_page_response
from .commerce_catalog import PRODUCTS, product_or_none
from .commerce_models import Order, ProductInventory
from .database import get_db
from .order_routes import OrderOutput, ensure_inventory_rows, expire_pending_orders, output


router = APIRouter(tags=["商城运营后台"])
ADMIN_PAGE = Path(__file__).with_name("static") / "admin_orders.html"


class InventoryOutput(BaseModel):
    product_id: str
    name: str
    price_fen: int
    available: int
    reserved: int
    sold: int
    active: bool


class InventoryUpdate(BaseModel):
    available: int = Field(ge=0, le=1_000_000)
    active: bool = True


class ShipmentInput(BaseModel):
    carrier: str = Field(min_length=2, max_length=64)
    tracking_number: str = Field(min_length=5, max_length=128)

    @field_validator("carrier", "tracking_number")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


@router.get("/admin/orders", include_in_schema=False)
def admin_orders_page(request: Request, db: Session = Depends(get_db)):
    # 页面本身也要求有效会话，避免只依赖前端脚本隐藏订单后台。
    if resolve_admin_session(request, db) is None:
        return RedirectResponse("/admin/login", status_code=303)
    return admin_page_response(ADMIN_PAGE)


@router.get("/api/admin/inventory", response_model=list[InventoryOutput], summary="查询商品库存")
def list_inventory(_: AdminIdentity = Depends(require_admin_identity), db: Session = Depends(get_db)):
    ensure_inventory_rows(db)
    rows = {row.product_id: row for row in db.scalars(select(ProductInventory)).all()}
    return [InventoryOutput(
        product_id=product.id, name=product.name, price_fen=product.price_fen,
        available=rows[product.id].available, reserved=rows[product.id].reserved,
        sold=rows[product.id].sold, active=rows[product.id].active,
    ) for product in PRODUCTS]


@router.put("/api/admin/inventory/{product_id}", response_model=InventoryOutput, summary="设置可售库存和上下架状态")
def update_inventory(
    product_id: str,
    data: InventoryUpdate,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """运营人员设置净可售数量；不会覆盖已经锁定或已售出的数量。"""
    ensure_admin_role(identity, "superadmin")
    product = product_or_none(product_id)
    if not product:
        raise HTTPException(404, "商品不存在")
    ensure_inventory_rows(db)
    inventory = db.get(ProductInventory, product_id)
    if not inventory:
        raise HTTPException(404, "库存记录不存在")
    before = {"available": inventory.available, "active": inventory.active}
    inventory.available = data.available
    inventory.active = data.active
    inventory.updated_at = datetime.utcnow()
    audit_admin_action(
        db,
        identity,
        action="inventory_update",
        target_type="product",
        target_id=product_id,
        detail={"before": before, "after": {"available": data.available, "active": data.active}},
        request=request,
    )
    db.commit()
    return InventoryOutput(
        product_id=product.id, name=product.name, price_fen=product.price_fen,
        available=inventory.available, reserved=inventory.reserved, sold=inventory.sold, active=inventory.active,
    )


@router.get("/api/admin/orders", response_model=list[OrderOutput], summary="查询订单")
def list_admin_orders(
    status: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=500),
    _: AdminIdentity = Depends(require_admin_identity), db: Session = Depends(get_db),
):
    expire_pending_orders(db)
    query = select(Order).order_by(Order.created_at.desc(), Order.id.desc()).limit(limit)
    if status:
        query = query.where(Order.status == status)
    return [output(order) for order in db.scalars(query).all()]


@router.post("/api/admin/orders/{order_id}/ship", response_model=OrderOutput, summary="录入运单并确认发货")
def ship_order(
    order_id: int,
    data: ShipmentInput,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """锁定订单行后发货，避免与用户刚发起的退款同时改写状态。"""
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order:
        raise HTTPException(404, "订单不存在")
    if order.status != "paid":
        raise HTTPException(409, "只有待发货订单可以确认发货")
    order.carrier = data.carrier
    order.tracking_number = data.tracking_number
    order.status = "shipped"
    order.shipped_at = datetime.utcnow()
    audit_admin_action(
        db,
        identity,
        action="order_ship",
        target_type="order",
        target_id=order.id,
        detail={
            "order_number": order.number,
            "carrier": data.carrier,
            "tracking_number": data.tracking_number,
        },
        request=request,
    )
    db.commit()
    return output(order)
