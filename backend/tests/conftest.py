"""测试环境的强制隔离配置。

该文件会在导入 app.main 之前由 pytest 加载。它用进程环境变量覆盖本机 .env，
从而保证自动测试：

1. 不调用真实微信接口，也不消耗真实服务配额；
2. 不读取或打印真实 AppSecret、JWT密钥和管理员Key；
3. 只写 test_folk_guide.db，不污染日常开发数据库 folk_guide.db；
4. 无论开发者本机如何配置 .env，测试结果都保持可重复。

这些环境变量只对当前pytest进程有效，不会修改磁盘上的.env文件。
"""

import os
import tempfile
from pathlib import Path


TEST_RUNTIME_ROOT = Path(tempfile.gettempdir()) / f"folk-guide-pytest-{os.getpid()}"
TEST_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
os.environ["ENVIRONMENT"] = "development"
os.environ["TESTING"] = "true"
os.environ["DATABASE_URL"] = f"sqlite:///{(TEST_RUNTIME_ROOT / 'test_folk_guide.db').as_posix()}"
os.environ["JWT_SECRET"] = "pytest-only-jwt-secret-not-for-production"
os.environ["ADMIN_API_KEY"] = "dev-admin-key"
os.environ["WECHAT_APP_ID"] = ""
os.environ["WECHAT_APP_SECRET"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_MODEL"] = ""
os.environ["LLM_TIMEOUT_SECONDS"] = "5"
os.environ["LLM_MAX_RETRIES"] = "0"
os.environ["LLM_MAX_OUTPUT_TOKENS"] = "500"
os.environ["AI_MAX_OUTPUT_CHARS"] = "6000"
os.environ["AI_RATE_LIMIT_ENABLED"] = "false"
os.environ["AI_RATE_LIMIT_WINDOW_SECONDS"] = "60"
os.environ["AI_RATE_LIMIT_MAX_REQUESTS"] = "1000"
os.environ["AI_TRIAL_NORMAL_LIMIT"] = "20"
os.environ["AI_TRIAL_COMPARISON_LIMIT"] = "2"
os.environ["AI_PAID_NORMAL_LIMIT"] = "50"
os.environ["AI_PAID_COMPARISON_LIMIT"] = "5"
os.environ["AI_USE_KNOWLEDGE_BASE"] = "false"
os.environ["AI_WEB_SEARCH_ENABLED"] = "false"
os.environ["AI_WEB_SEARCH_ALWAYS"] = "false"
os.environ["WEB_SEARCH_API_KEY"] = ""
os.environ["KNOWLEDGE_STORAGE_ROOT"] = str(TEST_RUNTIME_ROOT / "knowledge")
