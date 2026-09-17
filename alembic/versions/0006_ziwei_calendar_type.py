"""Store the original solar or lunar calendar selection for Ziwei charts."""

from alembic import op
import sqlalchemy as sa


revision = "0006_ziwei_calendar_type"
down_revision = "0005_ziwei_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ziwei_chart_records", sa.Column("calendar_type", sa.String(16), nullable=False, server_default="solar"))
    op.add_column("ziwei_chart_records", sa.Column("is_leap_month", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("ziwei_chart_records", "is_leap_month")
    op.drop_column("ziwei_chart_records", "calendar_type")
