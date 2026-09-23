"""管理员登录页面与会话接口。"""

from datetime import datetime, timedelta
from pathlib import Path
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from .admin_auth import (
    AdminIdentity,
    admin_session_cookie_name,
    audit_admin_action,
    hash_session_token,
    require_admin_session,
    require_admin_session_write,
    resolve_admin_session,
    validate_admin_username,
    verify_admin_password,
)
from .admin_models import AdminAuditLog, AdminSession, AdminUser
from .config import get_settings
from .database import get_db


router = APIRouter(tags=["管理员登录"])
ADMIN_LOGIN_PAGE = Path(__file__).with_name("static") / "admin_login.html"


class AdminLoginInput(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def clean_username(cls, value: str) -> str:
        return validate_admin_username(value)


class AdminMeOutput(BaseModel):
    username: str
    display_name: str
    role: str
    csrf_token: str


def admin_page_response(path: Path) -> FileResponse:
    """后台 HTML 不缓存、不嵌入第三方页面，并只加载同源资源。"""
    response = FileResponse(path)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; form-action 'self'; "
        "frame-ancestors 'none'; base-uri 'none'"
    )
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _output(identity: AdminIdentity) -> AdminMeOutput:
    return AdminMeOutput(
        username=identity.username,
        display_name=identity.display_name,
        role=identity.role,
        csrf_token=identity.csrf_token or "",
    )


@router.get("/admin/login", include_in_schema=False)
def admin_login_page(request: Request, db: Session = Depends(get_db)):
    if resolve_admin_session(request, db) is not None:
        return RedirectResponse("/admin/orders", status_code=303)
    return admin_page_response(ADMIN_LOGIN_PAGE)


@router.post("/api/admin/auth/login", response_model=AdminMeOutput, summary="管理员登录")
def admin_login(data: AdminLoginInput, request: Request, response: Response, db: Session = Depends(get_db)):
    settings = get_settings()
    now = datetime.utcnow()
    # 锁住账号行，避免并发错误密码请求互相覆盖失败次数。
    user = db.scalar(
        select(AdminUser).where(AdminUser.username == data.username).with_for_update()
    )
    # 不存在的账号也执行完整密码计算，降低通过响应时间枚举管理员账号的风险。
    password_hash = user.password_hash if user else "invalid-password-hash"
    password_ok = verify_admin_password(data.password, password_hash)
    unlocked = bool(user and (user.locked_until is None or user.locked_until <= now))
    if user is None or not user.active or not unlocked or not password_ok:
        if user is not None and user.active and unlocked:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.admin_max_failed_logins:
                user.locked_until = now + timedelta(minutes=settings.admin_lock_minutes)
        db.add(AdminAuditLog(
            admin_user_id=user.id if user else None,
            operator_username=data.username,
            action="login_failed",
            target_type="admin_session",
            ip_address=request.client.host[:64] if request.client else None,
        ))
        db.commit()
        raise HTTPException(status_code=401, detail="账号或密码错误，或账号暂时锁定")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    db.execute(delete(AdminSession).where(or_(
        AdminSession.expires_at <= now,
        AdminSession.revoked_at.is_not(None),
    )))
    raw_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    session = AdminSession(
        admin_user_id=user.id,
        token_hash=hash_session_token(raw_token),
        csrf_token=csrf_token,
        expires_at=now + timedelta(hours=settings.admin_session_hours),
        last_seen_at=now,
    )
    db.add(session)
    identity = AdminIdentity(
        user.id, user.username, user.display_name, user.role, "session", csrf_token
    )
    audit_admin_action(
        db, identity, action="login", target_type="admin_session", request=request
    )
    db.commit()
    response.set_cookie(
        admin_session_cookie_name(),
        raw_token,
        max_age=settings.admin_session_hours * 3600,
        httponly=True,
        secure=settings.environment.lower() == "production",
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return _output(identity)


@router.get("/api/admin/auth/me", response_model=AdminMeOutput, summary="读取当前管理员")
def admin_me(identity: AdminIdentity = Depends(require_admin_session)) -> AdminMeOutput:
    return _output(identity)


@router.post("/api/admin/auth/logout", status_code=204, summary="管理员退出登录")
def admin_logout(
    request: Request,
    identity: AdminIdentity = Depends(require_admin_session_write),
    db: Session = Depends(get_db),
):
    raw_token = request.cookies.get(admin_session_cookie_name(), "")
    if raw_token:
        session = db.scalar(
            select(AdminSession).where(AdminSession.token_hash == hash_session_token(raw_token))
        )
        if session is not None:
            session.revoked_at = datetime.utcnow()
    audit_admin_action(
        db, identity, action="logout", target_type="admin_session", request=request
    )
    db.commit()
    response = Response(status_code=204)
    response.delete_cookie(
        admin_session_cookie_name(),
        path="/",
        secure=get_settings().environment.lower() == "production",
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return response
