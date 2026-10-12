"""管理员账号管理后台：子账号创建、角色、启停用与改密。仅超级管理员可用。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .admin_auth import (
    AdminIdentity,
    audit_admin_action,
    ensure_admin_role,
    hash_admin_password,
    require_admin_identity,
    require_admin_write,
    validate_admin_password,
)
from .admin_models import AdminSession, AdminUser
from .database import get_db

router = APIRouter(tags=["管理员账号管理"])


class AdminUserOutput(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    active: bool
    last_login_at: datetime | None
    created_at: datetime


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="operator", pattern="^(superadmin|operator)$")

    @field_validator("username", "display_name")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class AdminUserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=64)
    role: str | None = Field(default=None, pattern="^(superadmin|operator)$")
    active: bool | None = None

    @field_validator("display_name")
    @classmethod
    def strip_display(cls, value: str | None) -> str | None:
        return value.strip() if value else value


class AdminPasswordChange(BaseModel):
    password: str = Field(min_length=8, max_length=128)


def _output(user: AdminUser) -> AdminUserOutput:
    return AdminUserOutput(
        id=user.id, username=user.username, display_name=user.display_name,
        role=user.role, active=user.active, last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


@router.get("/api/admin/users", response_model=list[AdminUserOutput], summary="列出管理员账号")
def list_admin_users(_: AdminIdentity = Depends(require_admin_identity), db: Session = Depends(get_db)):
    ensure_admin_role(_, "superadmin")
    return [_output(u) for u in db.scalars(select(AdminUser).order_by(AdminUser.id)).all()]


@router.post("/api/admin/users", response_model=AdminUserOutput, status_code=201, summary="创建子账号")
def create_admin(
    data: AdminUserCreate,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    ensure_admin_role(identity, "superadmin")
    normalized = data.username.strip().lower()
    if db.scalar(select(AdminUser).where(AdminUser.username == normalized)):
        raise HTTPException(409, "账号已存在")
    try:
        validate_admin_password(data.password, normalized)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    user = AdminUser(
        username=normalized,
        password_hash=hash_admin_password(data.password),
        display_name=data.display_name.strip(),
        role=data.role,
    )
    db.add(user)
    db.flush()
    audit_admin_action(db, identity, action="admin_create", target_type="admin_user", target_id=user.id,
                       detail={"username": normalized, "role": data.role}, request=request)
    db.commit()
    db.refresh(user)
    return _output(user)


@router.put("/api/admin/users/{user_id}", response_model=AdminUserOutput, summary="修改子账号角色/显示名/状态")
def update_admin(
    user_id: int,
    data: AdminUserUpdate,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    ensure_admin_role(identity, "superadmin")
    user = db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(404, "账号不存在")
    if user.id == identity.id:
        # 超管不能停用自己或降级自己。
        if data.active is False:
            raise HTTPException(400, "不能停用当前登录账号")
        if data.role and data.role != "superadmin":
            raise HTTPException(400, "不能降级自己的超管角色")
    before = {"display_name": user.display_name, "role": user.role, "active": user.active}
    if data.display_name is not None and data.display_name.strip():
        user.display_name = data.display_name.strip()
    if data.role is not None:
        user.role = data.role
    if data.active is not None:
        user.active = data.active
        if not data.active:
            # 停用账号时撤销其所有会话。
            db.execute(delete(AdminSession).where(AdminSession.admin_user_id == user.id))
    user.updated_at = datetime.utcnow()
    audit_admin_action(db, identity, action="admin_update", target_type="admin_user", target_id=user.id,
                       detail={"before": before, "after": {"display_name": user.display_name, "role": user.role, "active": user.active}},
                       request=request)
    db.commit()
    db.refresh(user)
    return _output(user)


@router.put("/api/admin/users/{user_id}/password", status_code=204, summary="重置子账号密码")
def reset_admin_password(
    user_id: int,
    data: AdminPasswordChange,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    ensure_admin_role(identity, "superadmin")
    user = db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(404, "账号不存在")
    try:
        validate_admin_password(data.password, user.username)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    user.password_hash = hash_admin_password(data.password)
    user.failed_login_count = 0
    user.locked_until = None
    user.password_changed_at = datetime.utcnow()
    # 改密后撤销该账号所有既有会话。
    db.execute(delete(AdminSession).where(AdminSession.admin_user_id == user.id))
    audit_admin_action(db, identity, action="admin_password_reset", target_type="admin_user", target_id=user.id,
                       detail={"username": user.username}, request=request)
    db.commit()


@router.put("/api/admin/me/password", status_code=204, summary="修改本人密码")
def change_my_password(
    data: AdminPasswordChange,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_write),
    db: Session = Depends(get_db),
):
    """当前登录管理员修改自己的密码，不要求超管角色。"""
    if identity.id is None:
        raise HTTPException(400, "当前账号不支持修改密码")
    user = db.get(AdminUser, identity.id)
    if not user:
        raise HTTPException(404, "账号不存在")
    try:
        validate_admin_password(data.password, user.username)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    user.password_hash = hash_admin_password(data.password)
    user.password_changed_at = datetime.utcnow()
    audit_admin_action(db, identity, action="admin_self_password_change", target_type="admin_user", target_id=user.id,
                       detail={"username": user.username}, request=request)
    db.commit()
