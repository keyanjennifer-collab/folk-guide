"""Add product master data table for admin-managed catalog."""

from alembic import op
import sqlalchemy as sa


revision = "0011_products"
down_revision = "0010_admin_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("price_fen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("category", sa.String(length=16), nullable=False, server_default="single"),
        sa.Column("length_cm", sa.Float(), nullable=False, server_default="0"),
        sa.Column("weight_grams", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("color", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("element", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("beast", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("mood", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("scent", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("story", sa.Text(), nullable=False, server_default=""),
        sa.Column("meaning", sa.Text(), nullable=False, server_default=""),
        sa.Column("image", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("emblem", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("gallery_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("swatches_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_category", "products", ["category"])
    op.create_index("ix_products_active", "products", ["active"])


def downgrade() -> None:
    op.drop_index("ix_products_active", table_name="products")
    op.drop_index("ix_products_category", table_name="products")
    op.drop_table("products")
