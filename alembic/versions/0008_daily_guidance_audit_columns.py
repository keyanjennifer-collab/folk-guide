"""Add audit fields used by the versioned personal color cache."""

from alembic import op
import sqlalchemy as sa


revision = "0008_daily_guidance_audit"
down_revision = "0007_ziwei_analysis_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "daily_guidance",
        sa.Column("algorithm_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "daily_guidance",
        sa.Column("final_scores_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "daily_guidance",
        sa.Column("ranking_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "daily_guidance",
        sa.Column("factors_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "daily_guidance",
        sa.Column("public_ranking_snapshot_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "daily_guidance",
        sa.Column("calculation_version", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_daily_guidance_algorithm_version",
        "daily_guidance",
        ["algorithm_version"],
    )


def downgrade() -> None:
    op.drop_index("ix_daily_guidance_algorithm_version", table_name="daily_guidance")
    op.drop_column("daily_guidance", "calculation_version")
    op.drop_column("daily_guidance", "public_ranking_snapshot_json")
    op.drop_column("daily_guidance", "factors_json")
    op.drop_column("daily_guidance", "ranking_json")
    op.drop_column("daily_guidance", "final_scores_json")
    op.drop_column("daily_guidance", "algorithm_version")
