"""Add optional nickname and avatar to existing accounts."""

from alembic import op
import sqlalchemy as sa

revision = "0004_user_display_profile"
down_revision = "0003_ai_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("nickname", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("avatar_url", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "nickname")
