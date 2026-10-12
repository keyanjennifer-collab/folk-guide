"""商品主数据管理后台：商品编辑、图片上传与上下架。

所有写操作都需要管理员会话（带 CSRF 令牌）与 superadmin 角色，并写入审计日志。
图片上传后返回 ``/product-assets/<文件名>`` 相对路径，客户端拼上 API 域名即可访问。
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_auth import AdminIdentity, audit_admin_action, ensure_admin_role, require_admin_identity, require_admin_write
from .commerce_catalog import load_products
from .commerce_models import Product
from .config import get_settings
from .database import get_db

router = APIRouter(tags=["商品管理后台"])

# 允许的图片扩展名与大小上限（5MB）。
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _assets_dir() -> Path:
    configured = get_settings().product_assets_dir
    if configured:
        return Path(configured)
    return Path(__file__).with_name("static") / "products"


class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    price_fen: int = Field(ge=0, le=100_000_000)
    cost_fen: int = Field(default=0, ge=0, le=100_000_000)
    category: str = Field(pattern="^(set|single)$")
    length_cm: float = Field(ge=0, le=10000)
    weight_grams: int = Field(ge=0, le=1_000_000)
    sort_order: int = Field(ge=0, le=10000)
    active: bool = True
    color: str = Field(default="", max_length=32)
    element: str = Field(default="", max_length=32)
    beast: str = Field(default="", max_length=64)
    mood: str = Field(default="", max_length=128)
    scent: str = Field(default="", max_length=255)
    story: str = Field(default="", max_length=2000)
    meaning: str = Field(default="", max_length=2000)
    image: str = Field(default="", max_length=512)
    emblem: str = Field(default="", max_length=512)
    gallery: list[str] = Field(default_factory=list, max_length=30)
    swatches: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("name", "color", "element", "beast", "mood", "scent", "story", "meaning")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class ProductCostUpdate(BaseModel):
    cost_fen: int = Field(ge=0, le=100_000_000, description="成本价（分）")


class ProductOutput(BaseModel):
    id: str
    name: str
    price_fen: int
    cost_fen: int
    category: str
    length_cm: float
    weight_grams: int
    sort_order: int
    active: bool
    color: str
    element: str
    beast: str
    mood: str
    scent: str
    story: str
    meaning: str
    image: str
    emblem: str
    gallery: list[str]
    swatches: list[str]
    detail: dict
    created_at: datetime
    updated_at: datetime


def _product_output(product: Product) -> ProductOutput:
    return ProductOutput(
        id=product.id, name=product.name, price_fen=product.price_fen,
        cost_fen=product.cost_fen,
        category=product.category, length_cm=product.length_cm,
        weight_grams=product.weight_grams, sort_order=product.sort_order,
        active=product.active, color=product.color, element=product.element,
        beast=product.beast, mood=product.mood, scent=product.scent,
        story=product.story, meaning=product.meaning, image=product.image,
        emblem=product.emblem,
        gallery=_json_list(product.gallery_json), swatches=_json_list(product.swatches_json),
        detail=_json_object(product.detail_json),
        created_at=product.created_at, updated_at=product.updated_at,
    )


def _json_list(raw: str | None) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def _json_object(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _get_product_or_404(db: Session, product_id: str) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "商品不存在")
    return product


def _validate_upload(file: UploadFile) -> tuple[bytes, str]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, "仅支持 jpg、png、webp 格式图片")
    content = file.file.read()
    if not content:
        raise HTTPException(400, "上传内容为空")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(400, "图片不能超过 5MB")
    return content, suffix


def _save_image(content: bytes, suffix: str) -> str:
    assets_dir = _assets_dir()
    assets_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{secrets.token_hex(16)}{suffix}"
    (assets_dir / filename).write_bytes(content)
    return filename


@router.get("/api/admin/products", response_model=list[ProductOutput], summary="查询全部商品")
def list_products(_: AdminIdentity = Depends(require_admin_identity), db: Session = Depends(get_db)):
    return [_product_output(row) for row in db.scalars(select(Product).order_by(Product.sort_order, Product.id)).all()]


@router.put("/api/admin/products/{product_id}", response_model=ProductOutput, summary="修改商品信息")
def update_product(
    product_id: str,
    data: ProductUpdate,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    ensure_admin_role(identity, "superadmin")
    product = _get_product_or_404(db, product_id)
    before = {"name": product.name, "price_fen": product.price_fen, "active": product.active}
    for key, value in data.model_dump(exclude={"gallery", "swatches"}).items():
        setattr(product, key, value)
    product.gallery_json = json.dumps(data.gallery, ensure_ascii=False)
    product.swatches_json = json.dumps(data.swatches, ensure_ascii=False)
    product.updated_at = datetime.utcnow()
    audit_admin_action(
        db, identity, action="product_update", target_type="product", target_id=product_id,
        detail={"before": before, "after": {"name": data.name, "price_fen": data.price_fen, "active": data.active}},
        request=request,
    )
    db.commit()
    db.refresh(product)
    return _product_output(product)


@router.put("/api/admin/products/{product_id}/cost", response_model=ProductOutput, summary="只修改商品成本价")
def update_product_cost(
    product_id: str,
    data: ProductCostUpdate,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """财务页快捷入口：只改成本价，不影响商品其他信息。"""
    ensure_admin_role(identity, "superadmin")
    product = _get_product_or_404(db, product_id)
    before = product.cost_fen
    product.cost_fen = data.cost_fen
    product.updated_at = datetime.utcnow()
    audit_admin_action(
        db, identity, action="product_cost_update", target_type="product", target_id=product_id,
        detail={"before": before, "after": data.cost_fen}, request=request,
    )
    db.commit()
    db.refresh(product)
    return _product_output(product)


@router.post("/api/admin/products/{product_id}/image", response_model=ProductOutput, summary="上传商品主图")
def upload_product_image(
    product_id: str,
    file: UploadFile,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    ensure_admin_role(identity, "superadmin")
    product = _get_product_or_404(db, product_id)
    content, suffix = _validate_upload(file)
    filename = _save_image(content, suffix)
    old_image = product.image
    product.image = filename
    product.updated_at = datetime.utcnow()
    audit_admin_action(
        db, identity, action="product_image_upload", target_type="product", target_id=product_id,
        detail={"field": "image", "before": old_image, "after": filename}, request=request,
    )
    db.commit()
    db.refresh(product)
    return _product_output(product)


@router.post("/api/admin/products/{product_id}/gallery", response_model=ProductOutput, summary="新增详情图")
def upload_gallery_image(
    product_id: str,
    file: UploadFile,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    ensure_admin_role(identity, "superadmin")
    product = _get_product_or_404(db, product_id)
    content, suffix = _validate_upload(file)
    filename = _save_image(content, suffix)
    gallery = _json_list(product.gallery_json)
    if len(gallery) >= 30:
        raise HTTPException(400, "详情图最多 30 张")
    gallery.append(filename)
    product.gallery_json = json.dumps(gallery, ensure_ascii=False)
    product.updated_at = datetime.utcnow()
    audit_admin_action(
        db, identity, action="product_gallery_add", target_type="product", target_id=product_id,
        detail={"field": "gallery", "added": filename}, request=request,
    )
    db.commit()
    db.refresh(product)
    return _product_output(product)


@router.delete("/api/admin/products/{product_id}/gallery/{filename}", response_model=ProductOutput, summary="删除详情图")
def remove_gallery_image(
    product_id: str,
    filename: str,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    ensure_admin_role(identity, "superadmin")
    product = _get_product_or_404(db, product_id)
    gallery = _json_list(product.gallery_json)
    if filename not in gallery:
        raise HTTPException(404, "该详情图不存在")
    gallery.remove(filename)
    product.gallery_json = json.dumps(gallery, ensure_ascii=False)
    product.updated_at = datetime.utcnow()
    audit_admin_action(
        db, identity, action="product_gallery_remove", target_type="product", target_id=product_id,
        detail={"field": "gallery", "removed": filename}, request=request,
    )
    db.commit()
    db.refresh(product)
    return _product_output(product)
