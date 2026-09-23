"""管理员密码、会话、权限和操作审计的公共能力。"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_models import AdminAuditLog, AdminSession, AdminUser
from .config import get_settings
from .database import get_db


USERNAME_PATTERN = re.compile(r"^[a-z0-9_.-]{3,64}$")
PASSWORD_SCHEME = "scrypt"
PASSWORD_N = 2**14
PASSWORD_R = 8
PASSWORD_P = 1
PASSWORD_DKLEN = 32


@dataclass(frozen=True)
class AdminIdentity:
    """一次已认证后台请求中的管理员身份。"""

    id: int | None
    username: str
    display_name: str
    role: str
    auth_method: Literal["session", "api_key"]
    csrf_token: str | None = None


def normalize_admin_username(username: str) -> str:
    return username.strip().lower()


def validate_admin_username(username: str) -> str:
    normalized = normalize_admin_username(username)
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError("账号只能包含小写字母、数字、点、下划线或连字符，长度为3至64位")
    return normalized


def validate_admin_password(password: str, username: str = "") -> None:
    if len(password) < 12 or len(password) > 128:
        raise ValueError("管理员密码长度必须为12至128位")
    normalized_username = normalize_admin_username(username)
    if normalized_username and normalized_username in password.lower():
        raise ValueError("管理员密码不能包含账号名")
    groups = (
        any(char.isalpha() for char in password),
        any(char.isdigit() for char in password),
        any(not char.isalnum() for char in password),
    )
    if sum(groups) < 2:
        raise ValueError("管理员密码至少应包含字母、数字、符号中的两类")


def _derive_password(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=PASSWORD_DKLEN
    )


def hash_admin_password(password: str) -> str:
    """使用带随机盐的 scrypt 保存密码，数据库中永不出现明文密码。"""
    salt = secrets.token_bytes(16)
    digest = _derive_password(password, salt, PASSWORD_N, PASSWORD_R, PASSWORD_P)
    return "$".join(
        (PASSWORD_SCHEME, str(PASSWORD_N), str(PASSWORD_R), str(PASSWORD_P), salt.hex(), digest.hex())
    )


_DUMMY_PASSWORD_HASH = hash_admin_password("not-a-real-administrator-password")


def verify_admin_password(password: str, encoded: str) -> bool:
    """校验密码；格式异常时仍执行一次等成本计算，避免明显的账号枚举时序差。"""
    try:
        scheme, raw_n, raw_r, raw_p, raw_salt, raw_digest = encoded.split("$", 5)
        if scheme != PASSWORD_SCHEME:
            raise ValueError("unsupported password scheme")
        n, r, p = int(raw_n), int(raw_r), int(raw_p)
        if (n, r, p) != (PASSWORD_N, PASSWORD_R, PASSWORD_P):
            raise ValueError("unexpected password cost")
        salt = bytes.fromhex(raw_salt)
        expected = bytes.fromhex(raw_digest)
    except (TypeError, ValueError):
        _, raw_n, raw_r, raw_p, raw_salt, raw_digest = _DUMMY_PASSWORD_HASH.split("$", 5)
        n, r, p = int(raw_n), int(raw_r), int(raw_p)
        salt, expected = bytes.fromhex(raw_salt), bytes.fromhex(raw_digest)
        _derive_password(password, salt, n, r, p)
        return False
    actual = _derive_password(password, salt, n, r, p)
    return secrets.compare_digest(actual, expected)


def create_admin_user(
    db: Session,
    *,
    username: str,
    password: str,
    display_name: str,
    role: str = "operator",
) -> AdminUser:
    """供服务器管理命令和测试创建账号；应用没有公开注册接口。"""
    normalized = validate_admin_username(username)
    validate_admin_password(password, normalized)
    if role not in {"superadmin", "operator"}:
        raise ValueError("管理员角色只能是 superadmin 或 operator")
    cleaned_name = display_name.strip()
    if not cleaned_name or len(cleaned_name) > 64:
        raise ValueError("管理员显示名称长度必须为1至64位")
    if db.scalar(select(AdminUser).where(AdminUser.username == normalized)):
        raise ValueError("管理员账号已存在")
    user = AdminUser(
        username=normalized,
        password_hash=hash_admin_password(password),
        display_name=cleaned_name,
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def admin_session_cookie_name() -> str:
    return "wuse_admin_session"


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def resolve_admin_session(request: Request, db: Session, *, touch: bool = False) -> AdminIdentity | None:
    """从 HttpOnly Cookie 恢复会话；过期、停用或已撤销会话一律视为未登录。"""
    raw_token = request.cookies.get(admin_session_cookie_name(), "")
    if not raw_token:
        return None
    now = datetime.utcnow()
    session = db.scalar(
        select(AdminSession).where(
            AdminSession.token_hash == hash_session_token(raw_token),
            AdminSession.revoked_at.is_(None),
            AdminSession.expires_at > now,
        )
    )
    if session is None:
        return None
    user = db.get(AdminUser, session.admin_user_id)
    if user is None or not user.active:
        return None
    if touch and session.last_seen_at < now - timedelta(minutes=5):
        session.last_seen_at = now
        db.commit()
    return AdminIdentity(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        auth_method="session",
        csrf_token=session.csrf_token,
    )


def require_admin_session(request: Request, db: Session = Depends(get_db)) -> AdminIdentity:
    identity = resolve_admin_session(request, db, touch=True)
    if identity is None:
        raise HTTPException(status_code=401, detail="管理员登录已失效")
    return identity


def require_admin_identity(
    request: Request,
    db: Session = Depends(get_db),
    x_admin_key: str = Header(default="", alias="X-Admin-Key"),
    x_admin_name: str = Header(default="admin", alias="X-Admin-Name"),
) -> AdminIdentity:
    """后台页面优先使用账号会话；共享 Key 仅保留给内部脚本和旧运维接口。"""
    identity = resolve_admin_session(request, db, touch=True)
    if identity is not None:
        return identity
    expected = get_settings().admin_api_key
    if expected and secrets.compare_digest(x_admin_key, expected):
        operator = x_admin_name.strip()[:128] or "api-key"
        return AdminIdentity(None, operator, operator, "superadmin", "api_key")
    raise HTTPException(status_code=401, detail="需要管理员登录")


def require_admin_write(
    identity: AdminIdentity = Depends(require_admin_identity),
    x_csrf_token: str = Header(default="", alias="X-CSRF-Token"),
) -> AdminIdentity:
    """Cookie 会话的写请求必须额外提供 CSRF 令牌；内部 Key 请求保持兼容。"""
    if identity.auth_method == "session" and not secrets.compare_digest(
        x_csrf_token, identity.csrf_token or ""
    ):
        raise HTTPException(status_code=403, detail="页面安全令牌无效，请刷新后重试")
    return identity


def require_admin_session_write(
    identity: AdminIdentity = Depends(require_admin_session),
    x_csrf_token: str = Header(default="", alias="X-CSRF-Token"),
) -> AdminIdentity:
    if not secrets.compare_digest(x_csrf_token, identity.csrf_token or ""):
        raise HTTPException(status_code=403, detail="页面安全令牌无效，请刷新后重试")
    return identity


def require_admin(
    request: Request,
    db: Session = Depends(get_db),
    x_admin_key: str = Header(default="", alias="X-Admin-Key"),
    x_admin_name: str = Header(default="admin", alias="X-Admin-Name"),
) -> str:
    """兼容现有知识库和运维路由，并保持旧接口未授权时的 403 语义。"""
    identity = resolve_admin_session(request, db, touch=True)
    if identity is not None:
        # 旧运维接口包含知识库审核和批处理触发，不属于订单运营角色的权限范围。
        ensure_admin_role(identity, "superadmin")
        return identity.display_name
    expected = get_settings().admin_api_key
    if expected and secrets.compare_digest(x_admin_key, expected):
        return x_admin_name.strip()[:128] or "api-key"
    raise HTTPException(status_code=403, detail="管理员凭证无效")


def ensure_admin_role(identity: AdminIdentity, *roles: str) -> None:
    if identity.role not in roles:
        raise HTTPException(status_code=403, detail="当前管理员没有执行此操作的权限")


def audit_admin_action(
    db: Session,
    identity: AdminIdentity,
    *,
    action: str,
    target_type: str,
    target_id: str | int | None = None,
    detail: dict | None = None,
    request: Request | None = None,
) -> None:
    """把审计记录加入当前事务，让业务修改和审计日志同时成功或回滚。"""
    ip_address = request.client.host[:64] if request and request.client else None
    db.add(AdminAuditLog(
        admin_user_id=identity.id,
        operator_username=identity.username,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        detail_json=json.dumps(detail, ensure_ascii=False, separators=(",", ":")) if detail else None,
        ip_address=ip_address,
    ))
