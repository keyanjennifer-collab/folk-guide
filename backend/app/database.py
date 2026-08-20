"""SQLAlchemy 数据库连接、模型基类和请求级会话。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    """全部 ORM 数据表的共同父类。"""
    pass


settings = get_settings()
# SQLite 只适合单机开发。TODO（上线前）：迁移 PostgreSQL，配置连接池、备份和恢复演练。
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """FastAPI 依赖：每个请求创建会话，请求结束后一定关闭连接。"""
    # Session 不是全局单例：每个请求独享一个会话，避免事务互相污染。
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
"""SQLAlchemy 数据库连接、模型基类和请求级会话。"""
