"""Add sale checkout, inventory, addresses and payment audit fields."""

from alembic import op
import sqlalchemy as sa


revision = "0009_commerce_sale"
down_revision = "0008_daily_guidance_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 商品资料随代码发布，数据库只保存会频繁变化的库存数量与上下架状态。
    op.create_table(
        "product_inventory",
        sa.Column("product_id", sa.String(length=64), nullable=False),
        sa.Column("available", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("product_id"),
    )
    op.create_index("ix_product_inventory_active", "product_inventory", ["active"])
    op.create_table(
        "shipping_addresses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("recipient_name", sa.String(length=64), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("province", sa.String(length=64), nullable=False),
        sa.Column("city", sa.String(length=64), nullable=False),
        sa.Column("district", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("detail", sa.String(length=255), nullable=False),
        sa.Column("postal_code", sa.String(length=16), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shipping_addresses_user_id", "shipping_addresses", ["user_id"])
    op.create_index("ix_shipping_addresses_is_default", "shipping_addresses", ["is_default"])

    # batch 模式同时兼容生产 PostgreSQL 与开发 SQLite 的表结构变更。
    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("subtotal_fen", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("shipping_fee_fen", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("receiver_name", sa.String(length=64), nullable=False, server_default=""))
        batch.add_column(sa.Column("receiver_phone", sa.String(length=32), nullable=False, server_default=""))
        batch.add_column(sa.Column("receiver_address", sa.String(length=512), nullable=False, server_default=""))
        batch.add_column(sa.Column("remark", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("wx_transaction_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("payment_prepay_id", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("refund_number", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("expires_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("paid_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("shipped_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("completed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("cancelled_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("refunded_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
        batch.create_unique_constraint("uq_orders_user_idempotency", ["user_id", "idempotency_key"])
        batch.create_unique_constraint("uq_orders_wx_transaction_id", ["wx_transaction_id"])
        batch.create_unique_constraint("uq_orders_refund_number", ["refund_number"])
        batch.create_index("ix_orders_expires_at", ["expires_at"])
    op.execute("UPDATE orders SET subtotal_fen = total_fen WHERE subtotal_fen = 0")

    op.create_table(
        "payment_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("order_number", sa.String(length=64), nullable=True),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index("ix_payment_events_event_id", "payment_events", ["event_id"])
    op.create_index("ix_payment_events_event_type", "payment_events", ["event_type"])
    op.create_index("ix_payment_events_order_number", "payment_events", ["order_number"])


def downgrade() -> None:
    op.drop_index("ix_payment_events_order_number", table_name="payment_events")
    op.drop_index("ix_payment_events_event_type", table_name="payment_events")
    op.drop_index("ix_payment_events_event_id", table_name="payment_events")
    op.drop_table("payment_events")
    with op.batch_alter_table("orders") as batch:
        batch.drop_index("ix_orders_expires_at")
        batch.drop_constraint("uq_orders_refund_number", type_="unique")
        batch.drop_constraint("uq_orders_wx_transaction_id", type_="unique")
        batch.drop_constraint("uq_orders_user_idempotency", type_="unique")
        for name in (
            "updated_at", "refunded_at", "cancelled_at", "completed_at", "shipped_at", "paid_at",
            "expires_at", "refund_number", "payment_prepay_id", "wx_transaction_id", "remark",
            "receiver_address", "receiver_phone", "receiver_name", "shipping_fee_fen", "subtotal_fen",
            "idempotency_key",
        ):
            batch.drop_column(name)
    op.drop_index("ix_shipping_addresses_is_default", table_name="shipping_addresses")
    op.drop_index("ix_shipping_addresses_user_id", table_name="shipping_addresses")
    op.drop_table("shipping_addresses")
    op.drop_index("ix_product_inventory_active", table_name="product_inventory")
    op.drop_table("product_inventory")
