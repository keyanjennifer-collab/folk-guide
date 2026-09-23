"""验证管理员账号登录、权限、CSRF、锁定和审计。"""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.admin_auth import create_admin_user
from app.admin_models import AdminAuditLog, AdminUser
from app.config import get_settings
from app.database import SessionLocal
from app.main import app


ADMIN_PASSWORD = "Safe-Password-2026"


def make_admin(role: str = "superadmin") -> tuple[int, str]:
    username = f"admin-{uuid4().hex[:10]}"
    with SessionLocal() as db:
        user = create_admin_user(
            db,
            username=username,
            password=ADMIN_PASSWORD,
            display_name="测试管理员",
            role=role,
        )
        assert ADMIN_PASSWORD not in user.password_hash
        return user.id, user.username


def test_admin_login_protects_page_and_audits_inventory_change():
    with TestClient(app) as client:
        admin_id, username = make_admin()
        redirect = client.get("/admin/orders", follow_redirects=False)
        assert redirect.status_code == 303
        assert redirect.headers["location"] == "/admin/login"
        assert client.get("/api/admin/auth/me").status_code == 401

        logged_in = client.post("/api/admin/auth/login", json={
            "username": username, "password": ADMIN_PASSWORD,
        })
        assert logged_in.status_code == 200, logged_in.text
        csrf = logged_in.json()["csrf_token"]
        cookie = logged_in.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie
        assert client.get("/admin/orders", follow_redirects=False).status_code == 200

        # Cookie 能证明登录身份，但所有写操作仍必须带当前会话的 CSRF 令牌。
        payload = {"available": 7, "active": True}
        assert client.put("/api/admin/inventory/green", json=payload).status_code == 403
        updated = client.put(
            "/api/admin/inventory/green",
            headers={"X-CSRF-Token": csrf},
            json=payload,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["available"] == 7

        logged_out = client.post("/api/admin/auth/logout", headers={"X-CSRF-Token": csrf})
        assert logged_out.status_code == 204
        assert client.get("/api/admin/auth/me").status_code == 401

        with SessionLocal() as db:
            actions = db.scalars(select(AdminAuditLog.action).where(
                AdminAuditLog.admin_user_id == admin_id
            )).all()
            assert "login" in actions
            assert "inventory_update" in actions
            assert "logout" in actions


def test_operator_cannot_change_inventory_and_repeated_failures_lock_account():
    with TestClient(app) as client:
        admin_id, username = make_admin(role="operator")
        login = client.post("/api/admin/auth/login", json={
            "username": username, "password": ADMIN_PASSWORD,
        })
        csrf = login.json()["csrf_token"]
        forbidden = client.put(
            "/api/admin/inventory/gold",
            headers={"X-CSRF-Token": csrf},
            json={"available": 3, "active": True},
        )
        assert forbidden.status_code == 403

        client.post("/api/admin/auth/logout", headers={"X-CSRF-Token": csrf})
        with SessionLocal() as db:
            user = db.get(AdminUser, admin_id)
            user.failed_login_count = get_settings().admin_max_failed_logins - 1
            db.commit()

        failed = client.post("/api/admin/auth/login", json={
            "username": username, "password": "definitely-wrong-password",
        })
        assert failed.status_code == 401
        # 达到阈值后，即使随后提供正确密码，也要等锁定期结束或由服务器重置。
        assert client.post("/api/admin/auth/login", json={
            "username": username, "password": ADMIN_PASSWORD,
        }).status_code == 401
        with SessionLocal() as db:
            user = db.get(AdminUser, admin_id)
            assert user.locked_until is not None
