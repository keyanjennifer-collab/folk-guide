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
"""集中读取环境变量和 .env 配置，业务代码不要直接读取系统环境变量。"""
