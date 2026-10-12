"""商城运营后台：经营看板、订单导出、批量发货与售后。"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from .admin_auth import (
    AdminIdentity,
    audit_admin_action,
    ensure_admin_role,
    require_admin_identity,
    require_admin_write,
)
from .commerce_models import Order, ProductInventory
from .database import get_db
from .order_routes import ensure_inventory_rows, expire_pending_orders, output
from .commerce_catalog import load_products
from .wechat_pay import WechatPayError, create_refund


router = APIRouter(tags=["商城运营后台"])

ORDER_STATUSES = ("pending", "paid", "shipped", "completed", "after_sale", "refunded", "cancelled")


# ---------------------------------------------------------------------------
# 经营看板
# ---------------------------------------------------------------------------

class DashboardOutput(BaseModel):
    today_order_count: int
    today_sales_fen: int
    pending_ship_count: int
    after_sale_count: int
    status_counts: dict[str, int]
    total_sales_fen: int
    total_cost_fen: int
    total_profit_fen: int
    profit_rate: float
    low_stock: list[dict[str, Any]]
    top_products: list[dict[str, Any]]


def _beijing_today_range() -> tuple[datetime, datetime]:
    """返回北京时间的今天 [00:00, 24:00)，用于“今日”统计。"""
    now = datetime.utcnow() + timedelta(hours=8)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)
    return start, start + timedelta(hours=24)


def _order_cost_fen(order: Order, cost_map: dict[str, int]) -> int:
    """按订单商品快照与商品成本价计算订单总成本（分）。"""
    import json
    try:
        items = json.loads(order.items_json or "[]")
    except (TypeError, ValueError):
        return 0
    total = 0
    for item in items:
        pid = item.get("product_id", "")
        qty = int(item.get("quantity", 0))
        total += cost_map.get(pid, 0) * qty
    return total


def _order_item_rows(order: Order) -> list[dict[str, Any]]:
    """解析订单商品快照。"""
    import json
    try:
        items = json.loads(order.items_json or "[]")
    except (TypeError, ValueError):
        return []
    return items


# ---------------------------------------------------------------------------
# 财务模型
# ---------------------------------------------------------------------------

class ProductFinance(BaseModel):
    product_id: str
    name: str
    sold_qty: int
    sales_fen: int
    cost_fen: int
    profit_fen: int
    profit_rate: float


class FinanceOutput(BaseModel):
    # 营收维度
    gross_sales_fen: int          # 已付款订单销售总额（含已退款订单）
    refund_fen: int               # 已退款订单金额
    net_sales_fen: int            # 净营收 = 销售 − 退款
    shipping_income_fen: int      # 已收运费
    # 成本与利润
    total_cost_fen: int           # 商品总成本
    gross_profit_fen: int         # 毛利 = 净营收 − 成本
    gross_profit_rate: float      # 毛利率
    net_profit_fen: int           # 净利 = 毛利（本模型运费计入收入，未再扣除其它费用）
    # 订单维度
    paid_order_count: int         # 已付款订单数（含退款）
    refunded_order_count: int     # 退款订单数
    # 商品维度明细
    products: list[ProductFinance]


@router.get("/api/admin/finance", response_model=FinanceOutput, summary="财务模型")
def finance(_: AdminIdentity = Depends(require_admin_identity), db: Session = Depends(get_db)):
    ensure_inventory_rows(db)
    expire_pending_orders(db)

    # 所有已产生资金往来的订单：已付款、发货、完成、售后、退款。
    settled_statuses = ("paid", "shipped", "completed", "after_sale", "refunded")
    orders = db.scalars(select(Order).where(Order.status.in_(settled_statuses))).all()
    cost_map = {p.id: p.cost_fen for p in load_products(db)}
    product_map = {p.id: p for p in load_products(db)}

    gross_sales = 0
    refund = 0
    shipping_income = 0
    total_cost = 0
    paid_count = 0
    refunded_count = 0

    # 按商品聚合。
    agg: dict[str, dict[str, Any]] = {}

    for order in orders:
        paid_count += 1
        if order.status == "refunded":
            refunded_count += 1
            refund += order.total_fen
            # 退款订单不计入净销售与成本。
            continue
        gross_sales += order.total_fen
        shipping_income += order.shipping_fee_fen
        cost = _order_cost_fen(order, cost_map)
        total_cost += cost
        for item in _order_item_rows(order):
            pid = item.get("product_id", "")
            qty = int(item.get("quantity", 0))
            unit_price = int(item.get("unit_price_fen", 0))
            unit_cost = cost_map.get(pid, 0)
            bucket = agg.setdefault(pid, {"sold_qty": 0, "sales_fen": 0, "cost_fen": 0})
            bucket["sold_qty"] += qty
            bucket["sales_fen"] += unit_price * qty
            bucket["cost_fen"] += unit_cost * qty

    net_sales = gross_sales - refund
    gross_profit = net_sales - total_cost
    gross_profit_rate = round(gross_profit / net_sales * 100, 2) if net_sales > 0 else 0.0

    products = []
    for pid, bucket in agg.items():
        name = product_map[pid].name if pid in product_map else pid
        profit = bucket["sales_fen"] - bucket["cost_fen"]
        rate = round(profit / bucket["sales_fen"] * 100, 2) if bucket["sales_fen"] > 0 else 0.0
        products.append(ProductFinance(
            product_id=pid, name=name, sold_qty=bucket["sold_qty"],
            sales_fen=bucket["sales_fen"], cost_fen=bucket["cost_fen"],
            profit_fen=profit, profit_rate=rate,
        ))
    products.sort(key=lambda x: x.profit_fen, reverse=True)

    return FinanceOutput(
        gross_sales_fen=gross_sales,
        refund_fen=refund,
        net_sales_fen=net_sales,
        shipping_income_fen=shipping_income,
        total_cost_fen=total_cost,
        gross_profit_fen=gross_profit,
        gross_profit_rate=gross_profit_rate,
        net_profit_fen=gross_profit,
        paid_order_count=paid_count,
        refunded_order_count=refunded_count,
        products=products,
    )


@router.get("/api/admin/dashboard", response_model=DashboardOutput, summary="经营数据看板")
def dashboard(_: AdminIdentity = Depends(require_admin_identity), db: Session = Depends(get_db)):
    ensure_inventory_rows(db)
    expire_pending_orders(db)

    start, end = _beijing_today_range()
    today_orders = db.scalars(select(Order).where(Order.created_at >= start, Order.created_at < end)).all()
    paid_orders = [o for o in today_orders if o.status in ("paid", "shipped", "completed", "after_sale", "refunded")]
    today_sales = sum(o.total_fen for o in paid_orders)

    status_counts: dict[str, int] = {name: 0 for name in ORDER_STATUSES}
    status_counts.update(dict(db.execute(
        select(Order.status, func.count(Order.id)).group_by(Order.status)
    ).all()))

    pending_ship = status_counts.get("paid", 0)
    after_sale = status_counts.get("after_sale", 0)

    # 累计销售额与成本（只统计已付款且未退款的订单）。
    settled_statuses = ("paid", "shipped", "completed", "after_sale")
    settled_orders = db.scalars(select(Order).where(Order.status.in_(settled_statuses))).all()
    total_sales = sum(o.total_fen for o in settled_orders)
    cost_map = {p.id: p.cost_fen for p in load_products(db)}
    total_cost = sum(_order_cost_fen(o, cost_map) for o in settled_orders)
    total_profit = total_sales - total_cost
    profit_rate = round(total_profit / total_sales * 100, 2) if total_sales > 0 else 0.0

    # 低库存：可售数量 <= 20 的商品（只统计已上架的）。
    inventory = {row.product_id: row for row in db.scalars(select(ProductInventory)).all()}
    products = {p.id: p for p in load_products(db)}
    low_stock = [
        {"product_id": pid, "name": products[pid].name, "available": inv.available}
        for pid, inv in inventory.items()
        if pid in products and inv.active and inv.available <= 20
    ]
    low_stock.sort(key=lambda x: x["available"])

    # 商品销量 Top（按库存表已售数量），附带成本与毛利。
    top_products = sorted(
        (
            {"product_id": pid, "name": products[pid].name, "sold": inv.sold,
             "price_fen": products[pid].price_fen, "cost_fen": products[pid].cost_fen}
            for pid, inv in inventory.items() if pid in products
        ),
        key=lambda x: x["sold"], reverse=True,
    )[:5]

    return DashboardOutput(
        today_order_count=len(today_orders),
        today_sales_fen=today_sales,
        pending_ship_count=pending_ship,
        after_sale_count=after_sale,
        status_counts=status_counts,
        total_sales_fen=total_sales,
        total_cost_fen=total_cost,
        total_profit_fen=total_profit,
        profit_rate=profit_rate,
        low_stock=low_stock,
        top_products=top_products,
    )


# ---------------------------------------------------------------------------
# 订单导出 CSV
# ---------------------------------------------------------------------------

STATUS_TEXT = {"pending": "待付款", "paid": "待发货", "shipped": "已发货", "completed": "已完成",
               "after_sale": "售后中", "refunded": "已退款", "cancelled": "已取消"}


@router.get("/api/admin/orders/export.csv", summary="导出订单 CSV")
def export_orders_csv(
    status: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=64),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    _: AdminIdentity = Depends(require_admin_identity),
    db: Session = Depends(get_db),
):
    expire_pending_orders(db)
    query = select(Order).order_by(Order.created_at.desc(), Order.id.desc())
    if status:
        query = query.where(Order.status == status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.where(or_(
            Order.number.ilike(like), Order.receiver_name.ilike(like),
            Order.receiver_phone.ilike(like), Order.receiver_address.ilike(like),
            Order.tracking_number.ilike(like), Order.wx_transaction_id.ilike(like),
            Order.refund_number.ilike(like), Order.remark.ilike(like),
        ))
    if date_from:
        try:
            query = query.where(Order.created_at >= datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            raise HTTPException(400, "date_from 格式应为 YYYY-MM-DD")
    if date_to:
        try:
            end = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except ValueError:
            raise HTTPException(400, "date_to 格式应为 YYYY-MM-DD")
        query = query.where(Order.created_at <= end)
    orders = db.scalars(query).all()
    cost_map = {p.id: p.cost_fen for p in load_products(db)}

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "订单号", "状态", "下单时间", "支付时间", "发货时间", "商品", "数量",
        "商品金额", "运费", "订单总额", "成本", "毛利", "收件人", "电话", "地址", "备注",
        "快递公司", "运单号", "微信交易号",
    ])
    for order in orders:
        items = order.items_json and __import__("json").loads(order.items_json) or []
        item_names = "、".join(f"{it.get('name', '')}" for it in items)
        item_qty = "、".join(str(it.get("quantity", "")) for it in items)
        cost = _order_cost_fen(order, cost_map)
        profit = order.total_fen - cost
        writer.writerow([
            order.number, STATUS_TEXT.get(order.status, order.status),
            order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "",
            order.paid_at.strftime("%Y-%m-%d %H:%M") if order.paid_at else "",
            order.shipped_at.strftime("%Y-%m-%d %H:%M") if order.shipped_at else "",
            item_names, item_qty,
            f"{order.subtotal_fen / 100:.2f}", f"{order.shipping_fee_fen / 100:.2f}",
            f"{order.total_fen / 100:.2f}",
            f"{cost / 100:.2f}", f"{profit / 100:.2f}",
            order.receiver_name, order.receiver_phone, order.receiver_address, order.remark or "",
            order.carrier or "", order.tracking_number or "", order.wx_transaction_id or "",
        ])
    csv_bytes = buffer.getvalue().encode("utf-8-sig")
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="orders.csv"'},
    )


# ---------------------------------------------------------------------------
# 批量发货
# ---------------------------------------------------------------------------

class BatchShipItem(BaseModel):
    order_id: int
    carrier: str = Field(min_length=2, max_length=64)
    tracking_number: str = Field(min_length=5, max_length=128)

    @field_validator("carrier", "tracking_number")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class BatchShipInput(BaseModel):
    items: list[BatchShipItem] = Field(min_length=1, max_length=200)


class BatchShipResult(BaseModel):
    shipped: int
    failed: list[dict[str, Any]]


@router.post("/api/admin/orders/batch-ship", response_model=BatchShipResult, summary="批量发货")
def batch_ship(
    data: BatchShipInput,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """一次录入多笔运单；单笔失败不影响其它订单。"""
    ensure_admin_role(identity, "superadmin")
    shipped = 0
    failed: list[dict[str, Any]] = []
    for item in data.items:
        order = db.scalar(select(Order).where(Order.id == item.order_id).with_for_update())
        if not order:
            failed.append({"order_id": item.order_id, "reason": "订单不存在"})
            continue
        if order.status != "paid":
            failed.append({"order_id": item.order_id, "reason": "非待发货状态"})
            continue
        order.carrier = item.carrier
        order.tracking_number = item.tracking_number
        order.status = "shipped"
        order.shipped_at = datetime.utcnow()
        audit_admin_action(
            db, identity, action="order_ship", target_type="order", target_id=order.id,
            detail={"order_number": order.number, "carrier": item.carrier, "tracking_number": item.tracking_number, "batch": True},
            request=request,
        )
        shipped += 1
    db.commit()
    return BatchShipResult(shipped=shipped, failed=failed)


# ---------------------------------------------------------------------------
# 售后退款（管理端）
# ---------------------------------------------------------------------------

class AdminRefundInput(BaseModel):
    reason: str = Field(default="商家同意退款", min_length=2, max_length=80)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return value.strip()


@router.post("/api/admin/orders/{order_id}/refund", summary="管理端发起原路退款")
def admin_refund(
    order_id: int,
    data: AdminRefundInput,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """对已付款订单发起整单原路退款；发货后订单进入人工售后时也可使用。"""
    ensure_admin_role(identity, "superadmin")
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order:
        raise HTTPException(404, "订单不存在")
    if order.status not in ("paid", "after_sale"):
        raise HTTPException(409, "只有已付款或售后中的订单可以退款")
    if order.refunded_at:
        raise HTTPException(409, "订单已退款")
    refund_number = order.refund_number or f"RF{order.number[2:]}"[:64]
    try:
        result = create_refund(order.number, refund_number, order.total_fen, data.reason)
    except WechatPayError as exc:
        db.rollback()
        raise HTTPException(502, str(exc)) from exc
    order.refund_number = refund_number
    if result.get("mock") and result.get("status") == "SUCCESS":
        # 回补已售库存（与用户自助退款逻辑一致，依赖库存表 sold 计数）。
        from .order_routes import _restock_refund
        _restock_refund(db, order)
        order.status = "refunded"
        order.refunded_at = datetime.utcnow()
    else:
        order.status = "after_sale"
    audit_admin_action(
        db, identity, action="order_refund", target_type="order", target_id=order.id,
        detail={"order_number": order.number, "refund_number": refund_number, "reason": data.reason},
        request=request,
    )
    db.commit()
    return output(order)


# ---------------------------------------------------------------------------
# 审计日志
# ---------------------------------------------------------------------------

from .admin_models import AdminAuditLog


class AuditLogOutput(BaseModel):
    id: int
    operator: str
    action: str
    target_type: str
    target_id: str | None
    detail: dict | None
    ip_address: str | None
    created_at: datetime


@router.get("/api/admin/audit-logs", response_model=list[AuditLogOutput], summary="查询操作审计日志")
def list_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    operator: str | None = Query(default=None),
    _: AdminIdentity = Depends(require_admin_identity),
    db: Session = Depends(get_db),
):
    ensure_admin_role(_, "superadmin")
    query = select(AdminAuditLog).order_by(AdminAuditLog.id.desc()).limit(limit)
    if operator:
        query = query.where(AdminAuditLog.operator_username == operator)
    rows = db.scalars(query).all()
    import json
    return [AuditLogOutput(
        id=row.id, operator=row.operator_username, action=row.action,
        target_type=row.target_type, target_id=row.target_id,
        detail=json.loads(row.detail_json) if row.detail_json else None,
        ip_address=row.ip_address, created_at=row.created_at,
    ) for row in rows]
