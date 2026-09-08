"""项目 ORM 数据模型：区分用户隐私、运营内容和公共知识库。"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    """微信用户映射；业务表只引用内部 id，不直接使用 openid。"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    openid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    # 手机号来自微信 getPhoneNumber 临时 code 的服务端换取结果，前端不能直接传明文覆盖。
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    phone_bound_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # 档案已配置ORM级联；其他历史表仍由注销服务显式删除，便于审计清理范围。
    profile: Mapped["BirthProfile | None"] = relationship(back_populates="user", cascade="all, delete-orphan")


class BirthProfile(Base):
    """每个用户最多一份生辰档案及其历法计算缓存。"""
    __tablename__ = "birth_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    calendar_type: Mapped[str] = mapped_column(String(16), default="solar")
    is_leap_month: Mapped[bool] = mapped_column(Boolean, default=False)
    birth_date: Mapped[date] = mapped_column(Date)
    time_known: Mapped[bool] = mapped_column(Boolean, default=False)
    birth_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    birth_city: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gender: Mapped[str] = mapped_column(String(16), default="unspecified")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    profile_version: Mapped[int] = mapped_column(Integer, default=1)
    normalized_solar_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    calendar_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    calculation_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user: Mapped[User] = relationship(back_populates="profile")


class DailyGuidance(Base):
    """个人每日五色缓存，同一用户同一天只有一条。

    payload_json 内含规则版本、配置指纹、档案版本和精度模式；读取时必须核对这些
    元数据。是否允许返回个人结果由AI国学权益实时判断，缓存本身不代表当前有权访问。
    """
    __tablename__ = "daily_guidance"
    __table_args__ = (UniqueConstraint("user_id", "guidance_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    guidance_date: Mapped[date] = mapped_column(Date)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PublicColorCache(Base):
    """公开接口使用的每日五色规则缓存。

    结果来自确定性历法规则；相同日期、规则版本和配置指纹会稳定复用。
    """
    __tablename__ = "public_color_caches"

    id: Mapped[int] = mapped_column(primary_key=True)
    guide_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    rule_version: Mapped[str] = mapped_column(String(64), index=True)
    config_fingerprint: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChatMessage(Base):
    """用户问答历史；不能混入公共知识库。"""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AIServiceGrant(Base):
    """AI 服务权益。

    新客赠送权益可直接按 User.created_at 计算；购买30天服务后，再在本表写入
    start_at/end_at。单独建表便于以后连接订单，又不会把支付状态塞进用户表。
    """
    __tablename__ = "ai_service_grants"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # grant_type 当前支持 new_user_3_days / paid_30_days 的业务概念，未来应改成权益产品表。
    grant_type: Mapped[str] = mapped_column(String(32), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime)
    end_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AIConversationMessage(Base):
    """正式 AI 国学问答记录。

    只保存用户自己的提问、回答和引用 JSON，不把聊天内容写入公共知识库。
    category 用于分别统计普通问答和七日比较次数。
    """
    __tablename__ = "ai_conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(64), index=True)
    # SQLite 原型用JSON字符串；迁移PostgreSQL后建议使用JSONB并建立必要索引。
    references_json: Mapped[str] = mapped_column(Text, default="[]")
    model_name: Mapped[str] = mapped_column(String(128))
    safety_status: Mapped[str] = mapped_column(String(32), default="safe")
    feedback: Mapped[str | None] = mapped_column(String(16), nullable=True)
    feedback_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class DailyCacheRun(Base):
    """每日缓存批处理的运行记录和数据库级执行租约。

    ``target_date`` 按北京时间自然日唯一。若部署时误启动多个 Uvicorn worker，
    第一个 worker 会取得运行租约，其余 worker 看到未过期租约后跳过，避免同时为
    全部用户重复计算。租约过期后允许其他 worker 接管未完成任务。

    本表只记录任务状态和数量，不保存生辰、openid、手机号或个人五色正文。
    """
    __tablename__ = "daily_cache_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="running", index=True)
    trigger: Mapped[str] = mapped_column(String(24), default="scheduler")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    public_days: Mapped[int] = mapped_column(Integer, default=0)
    eligible_users: Mapped[int] = mapped_column(Integer, default=0)
    personal_users: Mapped[int] = mapped_column(Integer, default=0)
    failed_users: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    worker_id: Mapped[str] = mapped_column(String(160))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PublicGuide(Base):
    """今日五色公共内容，一天一个版本化内容包。"""
    __tablename__ = "public_guides"

    id: Mapped[int] = mapped_column(primary_key=True)
    guide_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    # 每日内容结构变化较快，原型先整体存JSON；生产环境需按查询和统计需求决定是否拆表。
    payload_json: Mapped[str] = mapped_column(Text)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PublicGuideAudit(Base):
    """公共内容的创建、审核、发布、撤回审计记录。"""
    __tablename__ = "public_guide_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    guide_id: Mapped[int] = mapped_column(ForeignKey("public_guides.id"), index=True)
    action: Mapped[str] = mapped_column(String(32))
    operator: Mapped[str] = mapped_column(String(128))
    before_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    after_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KnowledgeDocument(Base):
    """知识来源及其审核状态；一份文档可以被拆成多个 KnowledgeChunk。"""
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    source_name: Mapped[str] = mapped_column(String(255))
    author: Mapped[str | None] = mapped_column(String(128), nullable=True)
    copyright_status: Mapped[str] = mapped_column(String(32))
    original_filename: Mapped[str] = mapped_column(String(255))
    # 当前指向本机文件。TODO（上线前）：迁移对象存储并做病毒扫描、备份和访问权限控制。
    storage_key: Mapped[str] = mapped_column(String(512))
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    file_size: Mapped[int] = mapped_column(Integer)
    mime_type: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="uploaded", index=True)
    # PDF解析质量元数据；非PDF文档page_count为空，needs_ocr固定为False。
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extraction_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    needs_ocr: Mapped[bool] = mapped_column(Boolean, default=False)
    unreadable_pages_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class KnowledgeChunk(Base):
    """问答检索的最小资料单元；仅 approved 片段允许进入向量库。"""
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    character_count: Mapped[int] = mapped_column(Integer)
    review_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    # PDF切片可以精确回到物理页；跨页片段同时记录起止页。
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extraction_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # OCR供应商不返回置信度时保持为空，不能伪造为100%。
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 外部向量库返回的主键。为空表示尚未同步或内容修改后需要重建。
    vector_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
"""项目 ORM 数据模型。隐私数据、运营内容和公共知识库使用不同的数据表。"""
