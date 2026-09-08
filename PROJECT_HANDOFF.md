# 五色知时小程序项目交接报告

更新时间：2026-08-25
代码仓库：`https://github.com/keyanjennifer-collab/folk-guide.git`
默认分支：`main`

## 1. 交接目的

这份文件用于让新的 GPT 或开发者在不依赖旧聊天记录的情况下继续开发。接手时应先阅读本文件，再检查 `git status`、`README.md`、`backend/.env.example` 和相关测试；不要重新搭建已经完成的功能。

严禁读取、输出、提交或复制真实 `.env` 中的微信 AppSecret、大模型 API Key、JWT 密钥、管理员 Key、数据库密码。根目录 `.env` 和 `backend/.env` 均已被 Git 忽略。

## 2. 产品定位和明确边界

产品名称：五色知时。
品牌口号：五色应时，知时而行。

核心逻辑：

```text
时序 → 五行关系 → 五色 → 个人判断 → 生活行动
```

内容定位是传统文化学习、颜色穿搭、香品和生活灵感，不提供确定性算命、改命、消灾、医疗诊断、投资收益、彩票、灾祸或死亡预测。所有相关页面和模型回答都必须保留用户自主判断，不得承诺效果。

目标覆盖约 20–50 岁用户，前端采用东方、安静、克制、有高级感的视觉方向；不按年龄分区。主视觉为 `COLORO 129-15-00`（屏幕近似 `#262626`），配低对比岩面纹理、米白正文和少量铜色强调。

## 3. 技术栈和目录

- 微信原生小程序：TypeScript、WXML、WXSS。
- Python 后端：FastAPI、SQLAlchemy、Pydantic Settings。
- 当前数据库：SQLite，仅用于开发；下一阶段迁移 PostgreSQL。
- 历法：`lunar-python`，统一按 `Asia/Shanghai` 处理业务日期。
- 大模型：OpenAI 兼容的 `/chat/completions` 接口。
- PDF：`pypdf` 本地文字提取；扫描 PDF 可选 MinerU，默认关闭。
- 测试：pytest；前端使用 TypeScript 编译检查。

主要目录：

```text
backend/app/                 FastAPI业务代码
backend/tests/               后端测试
miniprogram/                 微信小程序
preview/                     视觉预览
storage/                     本地知识文件，Git忽略
docs/                        本地学习报告，Git忽略
tools/                       文档和规则辅助生成脚本
```

## 4. 当前已经完成的功能

### 4.1 微信账号和档案

- `wx.login` → 后端 `code2session` → 内部用户 → JWT。
- 开发环境在缺少微信配置时允许测试替身；生产环境不能走替身。
- 手机号通过微信一次性 code 在后端换取，前端不能直接写手机号。
- 本人档案支持公历/农历、闰月、出生日期、未知时辰、出生城市、性别可选。
- 档案读取、保存、修改、删除已经接入真实 API。
- 删除档案会删除相关个人每日缓存；删除档案不等于注销账号。
- 账号注销会清理个人档案、每日结果、AI历史和权益等关联数据。

核心文件：

```text
backend/app/auth.py
backend/app/services.py
backend/app/profile_service.py
backend/app/calendar_service.py
miniprogram/pages/profile/
miniprogram/services/account.ts
miniprogram/services/profile.ts
```

### 4.2 历法和个人档案计算

- `calculate_birth_calendar` 调用 `lunar-python`。
- 输出公历、农历、生肖、星座、节气和四柱。
- 未知时辰时不伪造时柱，个人结果使用三柱参考模式。
- 计算结果写入 `calendar_data_json`，并保存计算版本。

### 4.3 今日五色

- 首页公共五色无需登录。
- 公共五色按北京时间自然日读取，只公开人工确认并发布的内容。
- 当天没有发布内容时返回待确认状态；规则缓存只供内部规则与个人结果使用，不能成为公开排行。
- 前端可展示用户指定聊天中最近一次已确认资料，但必须保留原日期并标注“非今日排行”。
- 公共结果提前缓存未来 7 天。
- 有本人档案且权益有效的用户，个人结果提前缓存未来 3 天。
- 个人五色和公共五色是两条独立结果；个人结果会说明排序不同的原因。
- 档案版本变化会让旧个人缓存失效。

核心文件：

```text
backend/app/daily_color_rule_engine.py
backend/app/daily_color_personal_engine.py
backend/app/daily_color_cache_service.py
backend/app/daily_update_service.py
backend/app/public_guide_service.py
miniprogram/pages/home/
miniprogram/services/daily.ts
```

### 4.4 北京时间每日任务

- 后端启动后补跑当天任务。
- 每天北京时间 `00:00` 自动运行。
- 公共缓存未来 7 天，个人缓存未来 3 天。
- 用户按批次处理，默认每批 100 人。
- 正式权益优先；新用户从账号创建起享受 72 小时体验。
- 使用数据库租约避免多个 worker 重复执行同一天任务。
- 失败支持指数重试，管理员可以查询状态和手动补跑。
- `daily_cache_runs` 只存任务汇总，不存生辰或个人五色正文。

管理员接口：

```text
GET  /api/admin/daily-cache/runs
POST /api/admin/daily-cache/run
```

当前管理员接口使用 `X-Admin-Key`，只适合原型，生产必须替换为正式管理员账号和角色权限。

### 4.5 AI 国学问答

- 当前上线策略是“大模型自身知识 + 强约束提示词”。
- `AI_USE_KNOWLEDGE_BASE=false`，不读取古籍知识库。
- 普通典籍问题不会读取本人档案。
- 明确的个人问题会复用当天同一份个人五色结果，只发送白名单派生字段，不发送原始生辰、手机号、openid 或内部 ID。
- 没有本人档案时给出确定性引导，不调用模型，也不消耗问答次数。
- 新用户赠送 3 天体验，默认每天 20 次普通问答、2 次七日比较。
- 正式权益默认每天 50 次普通问答、5 次七日比较；次数可由 `.env` 调整。
- 支持问答历史、点赞/纠错和当前权益查询。
- 输入关键词会拦截灾祸、疾病、死亡、彩票、违法、确定性收益等高风险问题。
- 模型系统提示词禁止确定性命运判断、医疗诊断、投资承诺和不同术数体系混拼。
- 输出在写数据库和返回前经过第二道安全复核；高风险结论或内部字段泄露会替换成安全提示，超长答案会截断。
- 每个用户有短窗口限流；当前为单进程内存实现，生产多副本需要 Redis。
- 小程序正文已显示“AI生成”，并在安全处理或截断时显示说明。

核心文件：

```text
backend/app/ai_routes.py
backend/app/ai_service.py
backend/app/llm_provider.py
backend/app/ai_safety.py
backend/app/ai_rate_limit.py
miniprogram/pages/chat/
miniprogram/services/ai.ts
```

### 4.6 可选联网搜索

- 已实现独立 Tavily HTTP 搜索适配器，但当前保持关闭。
- `AI_WEB_SEARCH_ENABLED=false` 时不会创建搜索客户端或请求搜索供应商。
- 开启后默认只对“最新、实时、来源、查一下”等问题搜索；`AI_WEB_SEARCH_ALWAYS=true` 才会让所有非高风险问题搜索。
- 搜索失败会降级为模型自身知识，不影响整次问答。
- 网页摘要被视为未经审核的不可信数据，不得执行网页中的指令，也不能冒充古籍知识库原文。
- 网页引用使用 `kind=web`，与 `knowledge`、`personal_daily` 分开。

用户已明确决定：联网搜索暂时关闭，不要擅自打开。

### 4.7 知识文档处理

- 已支持 TXT、Markdown、DOCX、文字型 PDF 的导入、解析、切块、审核、搜索和向量同步接口。
- 切块目标约 700 字，尽量保留标题、PDF页码和提取方式。
- 扫描版 PDF 可标记为需要 OCR；MinerU 默认关闭，不能在未授权时发送整本文件到第三方。
- 当前向量库是内存字符二元组替身，重启后丢失，不是正式向量库。
- 用户已明确决定：古籍知识库和外部向量库暂时不启用，但链路必须保留。

### 4.8 “我的”页面

- 已从虚构的订单、服务卡和演示有效期改成真实账号、档案、AI权益、个人五色和问答历史状态。
- 微信登录、手机号、退出登录、档案入口、个人结果入口和问答记录均连接真实后端数据。
- 每日订阅提醒仍是明确的“待接入”状态。

## 5. 主要 API

```text
GET  /health

POST /api/auth/wechat
GET  /api/users/me
POST /api/users/me/phone
DELETE /api/account

GET    /api/profiles/current
PUT    /api/profiles/current
DELETE /api/profiles/current

GET /api/public-guides/today
GET /api/daily

GET  /api/ai/quota
POST /api/ai/chat
GET  /api/ai/history
PUT  /api/ai/messages/{message_id}/feedback

GET  /api/admin/daily-cache/runs
POST /api/admin/daily-cache/run
```

完整接口以启动后的 `http://127.0.0.1:8000/docs` 为准。

## 6. 环境配置

安全配置模板是 `backend/.env.example`。运行时通常从 `backend` 目录启动，因此本机实际配置放在 `backend/.env`。

重要变量名称：

```dotenv
ENVIRONMENT=development
DATABASE_URL=sqlite:///./folk_guide.db
JWT_SECRET=
WECHAT_APP_ID=
WECHAT_APP_SECRET=
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
LLM_TIMEOUT_SECONDS=30
LLM_MAX_RETRIES=2
LLM_MAX_OUTPUT_TOKENS=1200

AI_MAX_OUTPUT_CHARS=6000
AI_RATE_LIMIT_ENABLED=true
AI_RATE_LIMIT_WINDOW_SECONDS=60
AI_RATE_LIMIT_MAX_REQUESTS=6
AI_TRIAL_NORMAL_LIMIT=20
AI_TRIAL_COMPARISON_LIMIT=2
AI_PAID_NORMAL_LIMIT=50
AI_PAID_COMPARISON_LIMIT=5

AI_USE_KNOWLEDGE_BASE=false
AI_WEB_SEARCH_ENABLED=false
AI_WEB_SEARCH_ALWAYS=false
WEB_SEARCH_PROVIDER=tavily
WEB_SEARCH_API_KEY=

DAILY_SCHEDULER_ENABLED=true
DAILY_CACHE_BATCH_SIZE=100
DAILY_CACHE_RETRY_ATTEMPTS=3
DAILY_CACHE_RETRY_SECONDS=10
DAILY_CACHE_LEASE_MINUTES=30

ADMIN_API_KEY=
```

修改 `.env` 后必须重启后端。不要把实际值加入本文档、聊天记录、前端代码或 Git。

## 7. 本地运行和检查

后端：

```powershell
cd D:\soft\folk-guide\backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

检查：

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/docs
```

访问根路径 `/` 返回 404 是正常的，因为项目没有定义首页 API。

后端测试：

```powershell
cd D:\soft\folk-guide\backend
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q tests
```

前端类型检查：

```powershell
cd D:\soft\folk-guide
.\node_modules\.bin\tsc.cmd --noEmit
```

本次交接前最后完整回归基线：后端 `113 passed`，前端 TypeScript 检查通过。pytest 仍会显示现有 `datetime.utcnow()` 弃用警告，尚未完成时区感知 UTC 重构。

微信开发者工具导入项目根目录 `D:\soft\folk-guide`。开发者工具可访问 `127.0.0.1`；手机真机中的 `127.0.0.1` 指手机自身，正式真机必须改成 HTTPS API 域名。

## 8. 当前没有完成或只适合开发环境的部分

### 8.1 下一阶段优先完成

1. PostgreSQL：当前仍是 SQLite，`requirements.txt` 还没有 `psycopg`。
2. Alembic：当前只有 SQLite 开发兼容迁移，没有可审查、升级、回滚的正式迁移历史。
3. 生产环境：前端 API 地址仍是 `http://127.0.0.1:8000`，尚无域名和 HTTPS。
4. 管理员权限：共享 `X-Admin-Key` 必须替换为管理员账号、角色和操作审计。
5. 分布式能力：AI限流需迁移 Redis；后台任务、模型调用和微信 access token 需要多实例一致性方案。
6. 运维：缺正式日志脱敏、请求 ID、监控、告警、数据库备份和恢复演练。
7. 合规页面：缺完整隐私政策、用户协议、AI生成内容说明和数据处理说明。
8. 内容验收：五色规则技术链路已完成，但专业准确性仍需样本核对和正式复核。
9. 真机验收：真实微信登录、手机号、双账号隔离、档案删除、注销和弱网仍需正式验收。
10. 前端收口：正式审核版本需要隐藏或调整所有暂缓功能入口和“尚未接入”说明。

### 8.2 用户明确暂缓

- 联网搜索：代码保留，开关保持 false。
- 微信订阅消息：没有接入，不能承诺一次授权永久每日推送。
- 古籍知识库和外部向量库：导入链路保留，问答开关保持 false。
- 微信支付、订单、物流、退款和售后。
- 完整商城、会员套餐、权益流水和自动续费。

“财库香”当前只适合做香品文化展示。没有真实商品、订单和支付后端时，正式审核版本不能显示虚构订单、物流或购买成功状态。

## 9. PostgreSQL 下一步建议

PostgreSQL 与域名无直接依赖，可以在申请域名前先完成：

1. 增加 `psycopg[binary]` 和 Alembic 依赖。
2. 建立 `alembic.ini`、迁移环境和当前完整模型的初始迁移。
3. 提供本地 PostgreSQL 配置，数据库只监听 `127.0.0.1`，不要把 5432 直接暴露公网。
4. 使用 `postgresql+psycopg://...` 的 `DATABASE_URL`，凭据只放 `.env`。
5. 保持 SQLite 快速测试，同时增加 PostgreSQL 集成测试。
6. 验证空库 `alembic upgrade head`、升级、回滚、唯一约束、事务和并发缓存任务。
7. 当前开发数据没有生产价值时直接使用空 PostgreSQL，不必迁移 `folk_guide.db`。

正式架构应是：

```text
微信小程序 / 用户浏览器
        ↓ HTTPS
统一 FastAPI 后端
        ↓ 私有网络
云端 PostgreSQL
```

客户端绝不能直接持有 PostgreSQL 密码或直接连接数据库。

## 10. 已知技术限制

- SQLite 只适合单机开发和低并发。
- 当前 AI 短窗口限流存于单个 Python 进程，重启清空，多 worker 不共享。
- AI成本控制目前采用每日调用次数和输出长度上限，不是供应商账单级精确 Token 统计。
- 输入安全分类仍是可解释关键词规则，需要补同义词、变体和人工抽检。
- 直接模型模式不具备可靠的古籍版本、卷页和逐字引用能力，提示词已经要求不能伪造。
- 内存向量库重启丢失，只用于保留未来 RAG 接口和测试。
- 管理后台是原型页面，共享管理员 Key 不适合公网。
- 微信 `access_token` 尚未做 Redis/数据库共享缓存。
- 文件目前在本地存储；正式知识文件需对象存储、病毒扫描和备份。
- `datetime.utcnow()` 存在弃用警告，后续应统一时区感知 UTC 存储策略。

## 11. 接手 GPT 的工作规则

1. 先运行 `git status --short`，不要覆盖用户未提交改动。
2. 不读取或输出真实 `.env`；检查配置时只说明字段是否存在，不显示值。
3. 不把生辰、openid、手机号、JWT、问答记录写入公共知识库或日志。
4. 不删除当前关闭的知识库和联网搜索链路；保持开关为 false。
5. 不擅自接入微信订阅、支付或自动续费。
6. 修改后先运行相关专项测试，再运行后端全量测试和 `tsc --noEmit`。
7. SQLite 开发兼容迁移和未来 Alembic 必须分清，生产不能依靠启动时临时 `ALTER TABLE`。
8. 所有确定性命运、灾祸、医疗、违法和收益承诺都必须在输入、提示词和输出三层约束。
9. 新增个人能力必须从 JWT 获取内部用户，不能相信前端提交的 `user_id`。
10. 提交 Git 前复核 `.env`、数据库、日志、证书、私钥、`project.private.config.json` 和本地文档均未进入暂存区。

## 12. 推荐给新 GPT 的第一条请求

```text
请先完整阅读项目根目录 PROJECT_HANDOFF.md、README.md 和 backend/.env.example，
然后检查当前 git 状态与现有测试。不要读取或输出任何真实 .env 密钥。
下一阶段先完成 PostgreSQL + Alembic：保留 SQLite 测试能力，增加 psycopg、
初始迁移、本地配置说明和 PostgreSQL 集成验证；不要启用联网搜索、知识库、
微信订阅或支付。完成后运行后端全量测试和前端 TypeScript 检查。
```
