# 民俗生活助手

一个“极薄微信小程序前端 + Python FastAPI 后端”的可运行项目。每日五色由后端规则生成并按北京时间缓存，AI 国学问答支持模型自身知识；审核知识库和联网搜索都由后端开关控制。

## 本地启动后端

请先安装 Python 3.11 或 3.12，并确认 `python --version` 能正常输出版本号。

```powershell
cd D:\soft\folk-guide\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

打开 `http://127.0.0.1:8000/docs` 查看和调试接口，`http://127.0.0.1:8000/health` 用于健康检查。

开发环境没有填写微信 AppID 时，后端会根据前端传来的临时 code 创建开发用户。生产环境必须设置 `ENVIRONMENT=production`、随机的 `JWT_SECRET` 及真实微信凭据。

### AI 安全与费用边界

AI 问答有三层边界：问题关键词拦截、模型系统提示词约束、模型输出返回前的后端复核。后端还按用户执行短窗口限流，并用每日问答次数限制单个账号的模型调用预算。主要配置如下：

```dotenv
AI_MAX_OUTPUT_CHARS=6000
AI_RATE_LIMIT_ENABLED=true
AI_RATE_LIMIT_WINDOW_SECONDS=60
AI_RATE_LIMIT_MAX_REQUESTS=6
AI_TRIAL_NORMAL_LIMIT=20
AI_TRIAL_COMPARISON_LIMIT=2
AI_PAID_NORMAL_LIMIT=50
AI_PAID_COMPARISON_LIMIT=5
```

输出复核发现确定性医疗、死亡、收益保证或内部字段泄露时，会替换为安全提示；超长答案会截断。当前短窗口限流是单进程实现，多副本生产环境需要迁移到 Redis，不能把它当作分布式限流的最终方案。

### 可选联网搜索

联网搜索默认关闭。在 `backend/.env` 中配置下面的变量后重启后端即可启用：

```dotenv
AI_WEB_SEARCH_ENABLED=false
AI_WEB_SEARCH_ALWAYS=false
WEB_SEARCH_PROVIDER=tavily
WEB_SEARCH_API_KEY=
WEB_SEARCH_BASE_URL=https://api.tavily.com
WEB_SEARCH_TIMEOUT_SECONDS=10
WEB_SEARCH_MAX_RESULTS=5
```

开启时后端先调用 Tavily 获取网页摘要，再将摘要作为“未经人工审核的外部参考”传给模型。`AI_WEB_SEARCH_ENABLED=false` 时不会请求任何搜索服务；开启但未填写 Key 时会自动降级为模型自身知识。默认只对“最新、实时、来源、查一下”等问题搜索，若将 `AI_WEB_SEARCH_ALWAYS` 设为 `true` 则所有非高风险问题都会搜索。搜索 Key 始终只保存在后端 `.env`，不会下发到小程序。

## 打开小程序

1. 打开微信开发者工具，导入本目录 `D:\soft\folk-guide`。
2. 本地开发时勾选“不校验合法域名、web-view（业务域名）、TLS版本以及HTTPS证书”。
3. 确保 FastAPI 已在 `127.0.0.1:8000` 运行。
4. 真机或上线前，把 `miniprogram/services/api.ts` 中的地址换成已备案的 HTTPS API 域名，并在微信后台配置 request 合法域名。
5. 将 `project.config.json` 中的测试 AppID 换成自己的 AppID。

如需在命令行执行 TypeScript 类型检查，先在项目根目录运行 `npm install`，然后执行 `npx tsc --noEmit`。微信开发者工具自身也可以完成小程序 TypeScript 编译。

## 当前已具备

- 微信登录流程及本地开发替身
- JWT 登录态
- 生辰档案创建、读取、修改和删除
- 按用户和日期缓存每日生活灵感
- AI国学问答、次数权益和高风险问题拦截
- AI答案二次安全复核、超长截断和用户级短窗口限流
- 可选的 Tavily 联网搜索（默认关闭，失败自动降级）
- 账号注销及关联数据删除
- SQLite 数据库和自动建表
- FastAPI Swagger 文档
- 微信小程序首页、档案、问答和设置页
- Docker 后端镜像

## 下一步

1. 增加 `psycopg` 和 Alembic，把 SQLite 开发库迁移为 PostgreSQL 正式方案。
2. 申请域名并部署 HTTPS 后端，配置微信 `request` 合法域名和生产环境强配置校验。
3. 把共享管理员 Key 替换为管理员账号、角色权限、登录过期和操作审计。
4. 为多实例部署增加 Redis 限流、微信凭证缓存、日志、监控、告警和数据库备份。
5. 补齐隐私政策、用户协议、AI生成内容说明及小程序备案材料。
6. 完成五色规则专业样本复核、真实微信双账号测试、弱网测试和发布验收。

联网搜索、微信订阅消息、古籍向量知识库、支付订单和完整会员体系当前均按产品决定暂缓，代码中的关闭开关不要擅自打开。完整交接状态见 [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md)。

## 重要说明

不要将微信 AppSecret、模型 API Key 或数据库密码写进小程序代码或提交到 Git。前端只调用自己的 Python API，所有敏感凭据均保存在后端环境变量中。
