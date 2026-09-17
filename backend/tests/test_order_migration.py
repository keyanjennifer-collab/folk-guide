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
    assert {column["name"] for column in inspect(engine).get_columns("orders")} == {
        "id", "user_id", "number", "status", "total_fen", "items_json",
        "carrier", "tracking_number", "created_at",
    }
    assert {"nickname", "avatar_url"}.issubset(
        {column["name"] for column in inspect(engine).get_columns("users")}
    )
    assert {"ziwei_chart_records", "ziwei_compatibility_records"}.issubset(inspect(engine).get_table_names())
    with engine.connect() as conn:
        assert conn.execute(text("select version_num from alembic_version")).scalar() == "0006_ziwei_calendar_type"
    engine.dispose()
    migrate("downgrade", "0001_initial_schema")
    engine = create_engine(database_url)
    assert "orders" not in inspect(engine).get_table_names()
    assert "ziwei_chart_records" not in inspect(engine).get_table_names()
    assert "users" in inspect(engine).get_table_names()
    engine.dispose()
    migrate("upgrade", "head")
