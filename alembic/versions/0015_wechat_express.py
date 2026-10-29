"""Persist WeChat waybill jobs, credentials and logistics query cache."""

from alembic import op
import sqlalchemy as sa

revision = "0015_wechat_express"
down_revision = "0014_refund_restock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("logistics_query_cache",
        sa.Column("cache_key", sa.String(64), primary_key=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("tracking_status", sa.String(32), nullable=False),
        sa.Column("tracking_message", sa.String(255), nullable=False),
        sa.Column("events_json", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.Column("next_query_at", sa.DateTime(), nullable=False))
    op.create_table("wechat_access_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("access_token", sa.String(512), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table("wechat_express_orders",
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("remote_order_id", sa.String(96), nullable=False),
        sa.Column("waybill_id", sa.String(64), nullable=False),
        sa.Column("delivery_id", sa.String(64), nullable=False),
        sa.Column("carrier_name", sa.String(64), nullable=False),
        sa.Column("package_json", sa.Text(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("next_action", sa.String(16), nullable=False),
        sa.Column("message", sa.String(255), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("attempt_round", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("lease_token", sa.String(64), nullable=False),
        sa.Column("lease_until", sa.DateTime(), nullable=True))
    for column in ("remote_order_id", "waybill_id", "status", "next_action", "next_attempt_at"):
        op.create_index("ix_wechat_express_orders_" + column, "wechat_express_orders", [column])


def downgrade() -> None:
    op.drop_table("wechat_express_orders")
    op.drop_table("wechat_access_tokens")
    op.drop_table("logistics_query_cache")
