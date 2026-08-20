"""SQLite 原型库兼容迁移；正式部署应使用 Alembic。"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


SQLITE_PROFILE_COLUMNS = {
    "is_leap_month": "BOOLEAN NOT NULL DEFAULT 0",
    "time_known": "BOOLEAN NOT NULL DEFAULT 0",
    "timezone": "VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai'",
    "profile_version": "INTEGER NOT NULL DEFAULT 1",
    "normalized_solar_date": "DATE",
    "calendar_data_json": "TEXT",
    "calculation_version": "VARCHAR(32)",
}

# 已经存在的开发数据库不会被 create_all 自动增加字段，因此启动时做小型兼容迁移。
SQLITE_USER_COLUMNS = {
    "phone_number": "VARCHAR(32)",
    "phone_bound_at": "DATETIME",
}

SQLITE_KNOWLEDGE_DOCUMENT_COLUMNS = {
    "page_count": "INTEGER",
    "extraction_method": "VARCHAR(32)",
    "needs_ocr": "BOOLEAN NOT NULL DEFAULT 0",
    "unreadable_pages_json": "TEXT",
    "parse_warning": "TEXT",
}

SQLITE_KNOWLEDGE_CHUNK_COLUMNS = {
    "page_start": "INTEGER",
    "page_end": "INTEGER",
    "extraction_method": "VARCHAR(32)",
    "ocr_confidence": "FLOAT",
}


def migrate_development_schema(engine: Engine) -> None:
    """兼容已经存在的 SQLite 原型数据库。

    create_all只会创建缺失表，不会给旧表自动加列，所以这里用ALTER TABLE补字段。
    TODO（上线前）：迁移PostgreSQL并使用Alembic版本化迁移，支持升级、审查和回滚。
    """
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    with engine.begin() as connection:
        if "birth_profiles" in tables:
            existing = {column["name"] for column in inspector.get_columns("birth_profiles")}
            for name, definition in SQLITE_PROFILE_COLUMNS.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE birth_profiles ADD COLUMN {name} {definition}"))
        if "users" in tables:
            existing = {column["name"] for column in inspector.get_columns("users")}
            for name, definition in SQLITE_USER_COLUMNS.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE users ADD COLUMN {name} {definition}"))
        if "knowledge_documents" in tables:
            existing = {column["name"] for column in inspector.get_columns("knowledge_documents")}
            for name, definition in SQLITE_KNOWLEDGE_DOCUMENT_COLUMNS.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE knowledge_documents ADD COLUMN {name} {definition}"))
        if "knowledge_chunks" in tables:
            existing = {column["name"] for column in inspector.get_columns("knowledge_chunks")}
            for name, definition in SQLITE_KNOWLEDGE_CHUNK_COLUMNS.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE knowledge_chunks ADD COLUMN {name} {definition}"))
"""SQLite 原型库的小型兼容迁移；正式部署应改用 Alembic。"""
