"""开发阶段后台接口的管理员身份校验。

当前用一个共享 Admin Key 保护运营接口，适合本机原型和小团队联调。
TODO（上线前）：替换为独立管理员账号、角色权限、登录过期与操作审计。
"""

import secrets

from fastapi import Header, HTTPException

from .config import get_settings


def require_admin(
    x_admin_key: str = Header(default=""),
    x_admin_name: str = Header(default="admin"),
) -> str:
    """校验请求头 X-Admin-Key，返回操作者名称供审计日志记录。"""
    # compare_digest 使用近似恒定时间比较，减少普通字符串比较带来的时序侧信道。
    expected = get_settings().admin_api_key
    if not expected or not secrets.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=403, detail="管理员凭证无效")
    return x_admin_name[:128] or "admin"
"""开发阶段后台接口的管理员身份校验。生产环境应替换为管理员账号与权限系统。"""
