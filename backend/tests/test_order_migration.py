"""Run real migrations against an isolated database, never the developer DB."""
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, inspect, text


def test_order_migration_upgrade_and_rollback(tmp_path):
    root = Path(__file__).resolve().parents[2]
    database_url = "sqlite:///" + str(tmp_path / "migration.db")
    env = dict(os.environ, DATABASE_URL=database_url)

    def migrate(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args], cwd=root,
            env=env, check=True, text=True, capture_output=True,
        )

    migrate("upgrade", "head")
    engine = create_engine(database_url)
    assert "orders" in inspect(engine).get_table_names()
    assert {
        "id", "user_id", "number", "status", "total_fen", "items_json",
        "carrier", "tracking_number", "created_at", "idempotency_key", "subtotal_fen",
        "shipping_fee_fen", "receiver_name", "receiver_phone", "receiver_address",
        "expires_at", "paid_at", "shipped_at", "refunded_at",
    }.issubset({column["name"] for column in inspect(engine).get_columns("orders")})
    assert {"product_inventory", "shipping_addresses", "payment_events"}.issubset(
        inspect(engine).get_table_names()
    )
    assert {"nickname", "avatar_url"}.issubset(
        {column["name"] for column in inspect(engine).get_columns("users")}
    )
    assert {"ziwei_chart_records", "ziwei_compatibility_records"}.issubset(inspect(engine).get_table_names())
    assert {"admin_users", "admin_sessions", "admin_audit_logs"}.issubset(
        inspect(engine).get_table_names()
    )
    with engine.connect() as conn:
        assert conn.execute(text("select version_num from alembic_version")).scalar() == "0010_admin_accounts"
    engine.dispose()
    migrate("downgrade", "0001_initial_schema")
    engine = create_engine(database_url)
    assert "orders" not in inspect(engine).get_table_names()
    assert "ziwei_chart_records" not in inspect(engine).get_table_names()
    assert "users" in inspect(engine).get_table_names()
    engine.dispose()
    migrate("upgrade", "head")
