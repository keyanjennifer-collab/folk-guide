"""Initial schema generated from the SQLAlchemy models."""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("openid", sa.String(length=128), nullable=False),
        sa.Column("phone_number", sa.String(length=32), nullable=True),
        sa.Column("phone_bound_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("openid"),
    )
    op.create_index("ix_users_openid", "users", ["openid"], unique=False)
    op.create_index("ix_users_phone_number", "users", ["phone_number"], unique=False)

    op.create_table(
        "birth_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("calendar_type", sa.String(length=16), nullable=False),
        sa.Column("is_leap_month", sa.Boolean(), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=False),
        sa.Column("time_known", sa.Boolean(), nullable=False),
        sa.Column("birth_time", sa.String(length=5), nullable=True),
        sa.Column("birth_city", sa.String(length=64), nullable=True),
        sa.Column("gender", sa.String(length=16), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("normalized_solar_date", sa.Date(), nullable=True),
        sa.Column("calendar_data_json", sa.Text(), nullable=True),
        sa.Column("calculation_version", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_birth_profiles_user_id", "birth_profiles", ["user_id"], unique=False)

    op.create_table(
        "daily_guidance",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("guidance_date", sa.Date(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "guidance_date"),
    )
    op.create_index("ix_daily_guidance_user_id", "daily_guidance", ["user_id"], unique=False)

    op.create_table(
        "public_color_caches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guide_date", sa.Date(), nullable=False),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        sa.Column("config_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guide_date"),
    )
    op.create_index("ix_public_color_caches_guide_date", "public_color_caches", ["guide_date"], unique=False)
    op.create_index("ix_public_color_caches_rule_version", "public_color_caches", ["rule_version"], unique=False)

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_messages_user_id", "chat_messages", ["user_id"], unique=False)

    op.create_table(
        "ai_service_grants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("grant_type", sa.String(length=32), nullable=False),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_service_grants_user_id", "ai_service_grants", ["user_id"], unique=False)
    op.create_index("ix_ai_service_grants_grant_type", "ai_service_grants", ["grant_type"], unique=False)
    op.create_index("ix_ai_service_grants_end_at", "ai_service_grants", ["end_at"], unique=False)

    op.create_table(
        "ai_conversation_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("references_json", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("safety_status", sa.String(length=32), nullable=False),
        sa.Column("feedback", sa.String(length=16), nullable=True),
        sa.Column("feedback_note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_conversation_messages_user_id", "ai_conversation_messages", ["user_id"], unique=False)
    op.create_index("ix_ai_conversation_messages_category", "ai_conversation_messages", ["category"], unique=False)
    op.create_index("ix_ai_conversation_messages_created_at", "ai_conversation_messages", ["created_at"], unique=False)

    op.create_table(
        "daily_cache_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("trigger", sa.String(length=24), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("public_days", sa.Integer(), nullable=False),
        sa.Column("eligible_users", sa.Integer(), nullable=False),
        sa.Column("personal_users", sa.Integer(), nullable=False),
        sa.Column("failed_users", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("worker_id", sa.String(length=160), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("target_date"),
    )
    op.create_index("ix_daily_cache_runs_target_date", "daily_cache_runs", ["target_date"], unique=False)
    op.create_index("ix_daily_cache_runs_status", "daily_cache_runs", ["status"], unique=False)
    op.create_index("ix_daily_cache_runs_lease_expires_at", "daily_cache_runs", ["lease_expires_at"], unique=False)

    op.create_table(
        "public_guides",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guide_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guide_date"),
    )
    op.create_index("ix_public_guides_guide_date", "public_guides", ["guide_date"], unique=False)
    op.create_index("ix_public_guides_status", "public_guides", ["status"], unique=False)

    op.create_table(
        "public_guide_audits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guide_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("operator", sa.String(length=128), nullable=False),
        sa.Column("before_status", sa.String(length=24), nullable=True),
        sa.Column("after_status", sa.String(length=24), nullable=True),
        sa.Column("detail_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["guide_id"], ["public_guides.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_public_guide_audits_guide_id", "public_guide_audits", ["guide_id"], unique=False)

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("author", sa.String(length=128), nullable=True),
        sa.Column("copyright_status", sa.String(length=32), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("extraction_method", sa.String(length=32), nullable=True),
        sa.Column("needs_ocr", sa.Boolean(), nullable=False),
        sa.Column("unreadable_pages_json", sa.Text(), nullable=True),
        sa.Column("parse_warning", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_hash"),
    )
    op.create_index("ix_knowledge_documents_file_hash", "knowledge_documents", ["file_hash"], unique=False)
    op.create_index("ix_knowledge_documents_status", "knowledge_documents", ["status"], unique=False)

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(length=500), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("extraction_method", sa.String(length=32), nullable=True),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("vector_id", sa.String(length=255), nullable=True),
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "chunk_index"),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"], unique=False)
    op.create_index("ix_knowledge_chunks_content_hash", "knowledge_chunks", ["content_hash"], unique=False)
    op.create_index("ix_knowledge_chunks_review_status", "knowledge_chunks", ["review_status"], unique=False)


def downgrade() -> None:
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
    op.drop_table("public_guide_audits")
    op.drop_table("public_guides")
    op.drop_table("daily_cache_runs")
    op.drop_table("ai_conversation_messages")
    op.drop_table("ai_service_grants")
    op.drop_table("chat_messages")
    op.drop_table("public_color_caches")
    op.drop_table("daily_guidance")
    op.drop_table("birth_profiles")
    op.drop_table("users")
