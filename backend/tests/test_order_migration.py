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
        "expires_at", "paid_at", "shipped_at", "refunded_at", "refund_restock",
    }.issubset({column["name"] for column in inspect(engine).get_columns("orders")})
    assert {"product_inventory", "shipping_addresses", "payment_events", "products", "logistics_query_cache"}.issubset(
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
        assert conn.execute(text("select version_num from alembic_version")).scalar() == "0016_kuaidi100_guanjia"
    assert {"wechat_access_tokens", "wechat_express_orders", "kuaidi100_authorizations"}.issubset(inspect(engine).get_table_names())
    assert "provider" in {column["name"] for column in inspect(engine).get_columns("wechat_express_orders")}
    engine.dispose()
    migrate("downgrade", "0001_initial_schema")
    engine = create_engine(database_url)
    assert "orders" not in inspect(engine).get_table_names()
    assert "ziwei_chart_records" not in inspect(engine).get_table_names()
    assert "users" in inspect(engine).get_table_names()
    engine.dispose()
    migrate("upgrade", "head")


def test_guanjia_migration_preserves_existing_waybill_and_wechat_channel(tmp_path):
    root = Path(__file__).resolve().parents[2]
    database_url = "sqlite:///" + str(tmp_path / "existing-waybill.db")
    env = dict(os.environ, DATABASE_URL=database_url)

    def migrate(*args):
        subprocess.run([sys.executable, "-m", "alembic", *args], cwd=root,
                       env=env, check=True, text=True, capture_output=True)

    migrate("upgrade", "0015_wechat_express")
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO wechat_express_orders
            (order_id,remote_order_id,waybill_id,delivery_id,carrier_name,package_json,
             cancel_requested,status,next_action,message,attempts,attempt_round,
             next_attempt_at,lease_token,lease_until)
            VALUES (1,'existing-order','73123456789012','ZTO','中通快递','{}',
                    0,'ordered','none','existing message',1,1,CURRENT_TIMESTAMP,'',NULL)"""))
    engine.dispose()
    migrate("upgrade", "head")
    engine = create_engine(database_url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT provider,waybill_id,status FROM wechat_express_orders WHERE order_id=1")).one() == (
            "wechat", "73123456789012", "ordered")
    engine.dispose()
    migrate("downgrade", "0015_wechat_express")
    engine = create_engine(database_url)
    from app.migrations import migrate_development_schema
    migrate_development_schema(engine)
    migrate_development_schema(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT provider,waybill_id FROM wechat_express_orders WHERE order_id=1")).one() == (
            "wechat", "73123456789012")
    engine.dispose()
