"""Track whether refunded goods have returned to sellable inventory."""

from alembic import op
import sqlalchemy as sa

revision = "0014_refund_restock"
down_revision = "0013_product_cost"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 旧版本退款全部自动回库；沿用历史事实，新退款由业务显式设置此标记。
    op.add_column("orders", sa.Column("refund_restock", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        batch.drop_column("refund_restock")
