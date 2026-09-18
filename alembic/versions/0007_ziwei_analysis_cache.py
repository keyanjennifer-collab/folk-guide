"""Add versioned Ziwei interpretation cache."""

from alembic import op
import sqlalchemy as sa


revision = "0007_ziwei_analysis_cache"
down_revision = "0006_ziwei_calendar_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ziwei_analysis_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("chart_id", sa.Integer(), sa.ForeignKey("ziwei_chart_records.id"), nullable=True),
        sa.Column("compatibility_id", sa.Integer(), sa.ForeignKey("ziwei_compatibility_records.id"), nullable=True),
        sa.Column("period_type", sa.String(16), nullable=False, server_default="mingpan"),
        sa.Column("period_key", sa.String(64), nullable=True),
        sa.Column("topic", sa.String(32), nullable=False, server_default="overview"),
        sa.Column("palace_branch", sa.Integer(), nullable=True),
        sa.Column("question_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("knowledge_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "user_id", "chart_id", "compatibility_id", "period_type", "period_key",
            "topic", "palace_branch", "question_hash", name="uq_ziwei_analysis_cache_request",
        ),
    )
    op.create_index("ix_ziwei_analysis_cache_user_id", "ziwei_analysis_cache", ["user_id"])
    op.create_index("ix_ziwei_analysis_cache_chart_id", "ziwei_analysis_cache", ["chart_id"])
    op.create_index("ix_ziwei_analysis_cache_compatibility_id", "ziwei_analysis_cache", ["compatibility_id"])


def downgrade() -> None:
    op.drop_table("ziwei_analysis_cache")
