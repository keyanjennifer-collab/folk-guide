"""集中读取环境变量和 .env 配置。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置模型；字段名可直接写成同名大写环境变量。"""
    app_name: str = "民俗生活助手 API"
    environment: str = "development"
    # 只由自动化测试进程开启，确保测试不会读取本机微信配置或访问真实微信接口。
    testing: bool = False
    database_url: str = "sqlite:///./folk_guide.db"
    # 生产环境由部署前的 Alembic 迁移建表；开发环境保留自动建表便于联调。
    auto_create_schema: bool = True
    # 浏览器预览/运营页面的明确来源，逗号分隔；小程序请求不依赖 CORS。
    cors_origins: str = ""
    # TODO（上线前）：必须使用高强度随机值覆盖默认值，并放进服务器密钥管理系统。
    jwt_secret: str = "development-only-secret"
    jwt_expire_minutes: int = 7 * 24 * 60
    wechat_app_id: str = ""
    wechat_app_secret: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    # OpenAI兼容接口的超时、重试和最大输出长度。不同供应商只需要更换上面三个字段。
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2
    llm_max_output_tokens: int = 1200
    # AI 输出在进入数据库和小程序前的第二道确定性安全复核；超长答案会截断。
    ai_max_output_chars: int = 6000
    # 进程内短窗口限流。多worker/多副本生产环境应迁移到Redis，数据库权益次数仍是最终上限。
    ai_rate_limit_enabled: bool = True
    ai_rate_limit_window_seconds: float = 60.0
    ai_rate_limit_max_requests: int = 6
    # 每日问答次数是单用户模型调用预算，避免单个账号持续消耗模型费用。
    ai_trial_normal_limit: int = 20
    ai_trial_comparison_limit: int = 2
    ai_paid_normal_limit: int = 50
    ai_paid_comparison_limit: int = 5
    # false：模型在强约束提示词下直接回答；true：必须先检索审核知识库。
    # 该开关只属于后端运行策略，不返回给小程序用户。
    ai_use_knowledge_base: bool = False
    # 可选网页搜索层：false时绝不请求搜索供应商；true时仍需配置搜索Key。
    ai_web_search_enabled: bool = False
    # false：只在问题包含“最新、实时、来源、查一下”等词时搜索；true：所有非高风险问题都搜索。
    ai_web_search_always: bool = False
    web_search_provider: str = "tavily"
    web_search_api_key: str = ""
    web_search_base_url: str = "https://api.tavily.com"
    web_search_timeout_seconds: float = 10.0
    web_search_max_results: int = 5
    # 每日缓存任务不依赖外部调度库：应用启动后先补跑一次，再按北京时间00:00运行。
    # 自动化测试通过TESTING=true关闭后台循环，由测试直接调用任务服务。
    daily_scheduler_enabled: bool = True
    daily_cache_batch_size: int = 100
    daily_cache_retry_attempts: int = 3
    daily_cache_retry_seconds: float = 10.0
    daily_cache_lease_minutes: int = 30
    # 留空时使用项目storage/knowledge；测试和生产可分别指向临时目录或挂载卷。
    knowledge_storage_root: str = ""
    # PDF本地提取与OCR后备。MinerU默认关闭，避免在未授权时把整本资料发送给第三方。
    pdf_max_pages: int = 1000
    pdf_min_text_chars_per_page: int = 20
    pdf_min_ocr_confidence: float = 0.80
    mineru_enabled: bool = False
    mineru_base_url: str = ""
    mineru_timeout_seconds: float = 1200.0
    # 共享 Key 只用于原型后台，不能作为正式运营人员权限系统。
    admin_api_key: str = "dev-admin-key"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """缓存配置对象，避免每个请求重复解析 .env 文件。"""
    return Settings()


def validate_runtime_settings(settings: Settings | None = None) -> None:
    """生产启动前拒绝开发默认值和不安全的关键配置。

    开发/测试环境仍允许使用 SQLite 和测试替身；生产环境如果配置不完整，
    应在进程启动时直接失败，而不是启动后才在真实请求中暴露问题。
    """
    runtime = settings or get_settings()
    if runtime.environment.lower() != "production":
        return

    errors: list[str] = []
    if runtime.testing:
        errors.append("TESTING 必须为 false")
    if runtime.auto_create_schema:
        errors.append("生产环境必须关闭 AUTO_CREATE_SCHEMA，并在启动前执行 Alembic")
    if runtime.database_url.lower().startswith("sqlite"):
        errors.append("DATABASE_URL 必须使用 PostgreSQL，不能使用 SQLite")
    if len(runtime.jwt_secret) < 32 or runtime.jwt_secret == "development-only-secret":
        errors.append("JWT_SECRET 必须是至少32位的随机密钥")
    if not runtime.wechat_app_id or not runtime.wechat_app_secret:
        errors.append("WECHAT_APP_ID 和 WECHAT_APP_SECRET 必须同时配置")
    if not runtime.admin_api_key or runtime.admin_api_key == "dev-admin-key" or len(runtime.admin_api_key) < 24:
        errors.append("ADMIN_API_KEY 必须是至少24位的随机密钥")
    if not runtime.cors_origins.strip():
        errors.append("CORS_ORIGINS 必须明确列出允许的来源")
    if errors:
        raise RuntimeError("生产配置校验失败：" + "；".join(errors))
"""集中读取环境变量和 .env 配置，业务代码不要直接读取系统环境变量。"""
