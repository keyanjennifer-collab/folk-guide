# 民俗生活助手

一个“极薄微信小程序前端 + Python FastAPI 后端”的可运行骨架。当前每日内容为安全的本地示例，AI和真实八字排盘预留在服务层，尚未接入。

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
- AI问答占位和高风险词基础拦截
- 账号注销及关联数据删除
- SQLite 数据库和自动建表
- FastAPI Swagger 文档
- 微信小程序首页、档案、问答和设置页
- Docker 后端镜像

## 下一步

1. 为数据库加入 Alembic 迁移。
2. 选择并验证历法库，编写节气、时区、子时等边界测试。
3. 整理有版权来源记录的审核知识库。
4. 接入合规大模型，并实现输入、检索、输出三层安全检查。
5. 把 SQLite 换为 PostgreSQL，增加限流、日志和监控。
6. 补齐隐私政策、用户协议、AI生成标识及小程序备案材料。

## 重要说明

不要将微信 AppSecret、模型 API Key 或数据库密码写进小程序代码或提交到 Git。前端只调用自己的 Python API，所有敏感凭据均保存在后端环境变量中。
