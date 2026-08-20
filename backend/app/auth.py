"""小程序用户 JWT 的签发和校验；业务接口统一使用内部 user_id。"""

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import User


bearer = HTTPBearer()


def create_token(user_id: int) -> str:
    """把内部 user_id 写入有有效期的 JWT，不在令牌中存放生辰等隐私数据。"""
    settings = get_settings()
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    # sub 是JWT标准“主体”字段。本项目只写内部编号，不写openid、手机号或生辰资料。
    # TODO（上线前）：增加 jti/令牌版本与撤销表，支持改密、注销和风控时立即失效。
    return jwt.encode({"sub": str(user_id), "exp": expires}, settings.jwt_secret, algorithm="HS256")


def current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    """解析 Bearer Token，并从数据库加载当前用户；失败统一返回 401。"""
    try:
        # algorithms 固定为 HS256，不能相信令牌Header自行声明的任意算法。
        payload = jwt.decode(credentials.credentials, get_settings().jwt_secret, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="登录状态无效") from exc
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user
"""小程序用户 JWT 的签发和校验。微信 openid 不直接暴露给业务接口。"""
