"""Add saved Ziwei charts and compatibility records.

Revision ID: 0005_ziwei_records
Revises: 0004_user_display_profile
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_ziwei_records"
down_revision = "0004_user_display_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ziwei_chart_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("name", sa.String(64), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=False),
        sa.Column("birth_time", sa.String(5), nullable=False),
        sa.Column("gender", sa.String(16), nullable=False),
        sa.Column("birth_location", sa.String(128), nullable=True),
        sa.Column("chart_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ziwei_chart_records_user_id", "ziwei_chart_records", ["user_id"])
    op.create_index("ix_ziwei_chart_records_updated_at", "ziwei_chart_records", ["updated_at"])
    op.create_table(
        "ziwei_compatibility_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("relation_type", sa.String(16), nullable=False),
        sa.Column("person_a_json", sa.Text(), nullable=False),
        sa.Column("person_b_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ziwei_compatibility_records_user_id", "ziwei_compatibility_records", ["user_id"])
    op.create_index("ix_ziwei_compatibility_records_relation_type", "ziwei_compatibility_records", ["relation_type"])
    op.create_index("ix_ziwei_compatibility_records_created_at", "ziwei_compatibility_records", ["created_at"])


def downgrade() -> None:
    op.drop_table("ziwei_compatibility_records")
    op.drop_table("ziwei_chart_records")
