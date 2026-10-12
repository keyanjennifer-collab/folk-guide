"""Add cost_fen to products for profit calculation."""

from alembic import op
import sqlalchemy as sa


revision = "0013_product_cost"
down_revision = "0011_products"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("cost_fen", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("products", "cost_fen")
