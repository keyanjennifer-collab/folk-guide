"""仅在服务器终端运行的管理员账号管理命令。"""

import argparse
from datetime import datetime
from getpass import getpass

from sqlalchemy import delete, func, select

from .admin_auth import create_admin_user, hash_admin_password, validate_admin_password
from .admin_models import AdminSession, AdminUser
from .database import SessionLocal


def _new_password(username: str) -> str:
    password = getpass("输入管理员密码（至少12位）: ")
    confirmation = getpass("再次输入管理员密码: ")
    if password != confirmation:
        raise ValueError("两次输入的密码不一致")
    validate_admin_password(password, username)
    return password


def create_command(args: argparse.Namespace) -> None:
    password = _new_password(args.username)
    with SessionLocal() as db:
        user = create_admin_user(
            db,
            username=args.username,
            password=password,
            display_name=args.display_name,
            role=args.role,
        )
    print(f"已创建管理员：{user.username}（{user.display_name} / {user.role}）")


def reset_password_command(args: argparse.Namespace) -> None:
    password = _new_password(args.username)
    with SessionLocal() as db:
        user = db.scalar(select(AdminUser).where(AdminUser.username == args.username.lower()))
        if user is None:
            raise ValueError("管理员账号不存在")
        user.password_hash = hash_admin_password(password)
        user.failed_login_count = 0
        user.locked_until = None
        user.password_changed_at = datetime.utcnow()
        db.execute(delete(AdminSession).where(AdminSession.admin_user_id == user.id))
        db.commit()
    print(f"已重置管理员密码：{user.username}")


def disable_command(args: argparse.Namespace) -> None:
    with SessionLocal() as db:
        user = db.scalar(select(AdminUser).where(AdminUser.username == args.username.lower()))
        if user is None:
            raise ValueError("管理员账号不存在")
        if user.role == "superadmin" and user.active:
            active_superadmins = db.scalar(select(func.count()).select_from(AdminUser).where(
                AdminUser.role == "superadmin", AdminUser.active.is_(True)
            ))
            if active_superadmins <= 1:
                raise ValueError("不能停用最后一个超级管理员")
        user.active = False
        db.execute(delete(AdminSession).where(AdminSession.admin_user_id == user.id))
        db.commit()
    print(f"已停用管理员：{user.username}")


def enable_command(args: argparse.Namespace) -> None:
    with SessionLocal() as db:
        user = db.scalar(select(AdminUser).where(AdminUser.username == args.username.lower()))
        if user is None:
            raise ValueError("管理员账号不存在")
        user.active = True
        user.failed_login_count = 0
        user.locked_until = None
        db.commit()
    print(f"已启用管理员：{user.username}")


def list_command(_: argparse.Namespace) -> None:
    with SessionLocal() as db:
        users = db.scalars(select(AdminUser).order_by(AdminUser.id)).all()
        for user in users:
            status = "启用" if user.active else "停用"
            print(f"{user.username}\t{user.display_name}\t{user.role}\t{status}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="管理五色知时后台管理员账号")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="创建管理员")
    create.add_argument("--username", required=True)
    create.add_argument("--display-name", required=True)
    create.add_argument("--role", choices=("superadmin", "operator"), default="operator")
    create.set_defaults(handler=create_command)
    reset = subparsers.add_parser("reset-password", help="重置管理员密码")
    reset.add_argument("--username", required=True)
    reset.set_defaults(handler=reset_password_command)
    disable = subparsers.add_parser("disable", help="停用管理员")
    disable.add_argument("--username", required=True)
    disable.set_defaults(handler=disable_command)
    enable = subparsers.add_parser("enable", help="启用管理员")
    enable.add_argument("--username", required=True)
    enable.set_defaults(handler=enable_command)
    listing = subparsers.add_parser("list", help="列出管理员")
    listing.set_defaults(handler=list_command)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        args.handler(args)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
