"""Add user-owned AI conversations and attach future messages to them."""

from alembic import op
import sqlalchemy as sa

revision = "0003_ai_conversations"
down_revision = "0002_account_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_conversations_user_id", "ai_conversations", ["user_id"])
    op.create_index("ix_ai_conversations_updated_at", "ai_conversations", ["updated_at"])
    with op.batch_alter_table("ai_conversation_messages") as batch:
        batch.add_column(sa.Column("conversation_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("favorite", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_index("ix_ai_conversation_messages_conversation_id", ["conversation_id"])
        batch.create_foreign_key("fk_ai_conversation_messages_conversation_id", "ai_conversations", ["conversation_id"], ["id"])
    op.create_table(
        "ai_deleted_usage", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ai_deleted_usage_user_id", "ai_deleted_usage", ["user_id"])
    op.create_index("ix_ai_deleted_usage_created_at", "ai_deleted_usage", ["created_at"])
    # 冻结迁移中的表定义，旧历史每个用户归入独立会话，不改问答正文。
    conn = op.get_bind()
    metadata = sa.MetaData()
    messages = sa.Table("ai_conversation_messages", metadata, autoload_with=conn)
    conversations = sa.Table("ai_conversations", metadata, autoload_with=conn)
    groups = conn.execute(sa.select(messages.c.user_id, sa.func.min(messages.c.created_at),
                                   sa.func.max(messages.c.created_at)).where(
        messages.c.conversation_id.is_(None)).group_by(messages.c.user_id)).all()
    for user_id, first, last in groups:
        inserted = conn.execute(conversations.insert().values(
            user_id=user_id, title="历史问答", created_at=first, updated_at=last, archived=False))
        conn.execute(messages.update().where(messages.c.user_id == user_id,
                                            messages.c.conversation_id.is_(None)).values(
            conversation_id=inserted.inserted_primary_key[0]))


def downgrade() -> None:
    op.drop_table("ai_deleted_usage")
    with op.batch_alter_table("ai_conversation_messages") as batch:
        batch.drop_constraint("fk_ai_conversation_messages_conversation_id", type_="foreignkey")
        batch.drop_index("ix_ai_conversation_messages_conversation_id")
        batch.drop_column("favorite")
        batch.drop_column("conversation_id")
    op.drop_index("ix_ai_conversations_updated_at", table_name="ai_conversations")
    op.drop_index("ix_ai_conversations_user_id", table_name="ai_conversations")
    op.drop_table("ai_conversations")
