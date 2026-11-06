"""Separate Kuaidi Guanjia authorization and order channel from WeChat."""

from alembic import op
import sqlalchemy as sa

revision = "0016_kuaidi100_guanjia"
down_revision = "0015_wechat_express"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("wechat_express_orders", sa.Column("provider", sa.String(32), nullable=False, server_default="wechat"))
    op.create_table("kuaidi100_authorizations",
        sa.Column("app_key", sa.String(128), primary_key=True),
        sa.Column("access_token", sa.String(1024), nullable=False),
        sa.Column("refresh_token", sa.String(1024), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("oauth_state_hash", sa.String(64), nullable=False),
        sa.Column("oauth_state_expires_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_table("kuaidi100_authorizations")
    op.drop_column("wechat_express_orders", "provider")
