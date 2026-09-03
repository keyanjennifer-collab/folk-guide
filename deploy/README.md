# 生产部署说明

本目录提供一套单机预发布/小规模生产骨架：PostgreSQL + FastAPI + Caddy。生产密钥
只写入服务器上的 `deploy/.env.production`，不要提交到 GitHub。

服务器当前使用 `docker-compose` 1.x，因此以下命令统一写成带连字符的形式；不要改成
`docker compose`，除非以后另行安装 Compose v2 插件。

## 首次部署

在服务器上进入项目根目录后：

```bash
cd ~/folk-guide/deploy
cp .env.production.example .env.production
nano .env.production
```

至少替换以下值（如果暂时不开放微信登录，可先把 API 保持在预发布状态，不要提交审核）：

- `POSTGRES_PASSWORD`：随机、较长、建议只使用字母数字，避免 URL 特殊字符；
- `JWT_SECRET`：至少 32 位随机值；
- `ADMIN_API_KEY`：至少 24 位随机值；
- `WECHAT_APP_ID` / `WECHAT_APP_SECRET`：微信后台真实凭据；生产配置校验要求二者同时填写；
- `SITE_DOMAIN` / `API_DOMAIN`：本项目使用 `wusezhishi.com` 和 `api.wusezhishi.com`；
- `CORS_ORIGINS`：实际网站来源，逗号分隔。

生成随机值可在服务器执行（只显示在你的终端，不要发到聊天）：

```bash
openssl rand -hex 32   # JWT_SECRET
openssl rand -hex 24   # ADMIN_API_KEY
openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 24  # PostgreSQL密码
```

先启动数据库并执行一次迁移，再启动 API 和 Caddy：

```bash
docker-compose up -d db
docker-compose run --rm migrate
docker-compose up -d api caddy
docker-compose ps
```

首次构建镜像时，服务器需要能访问 Docker 镜像仓库和 PyPI；如果下载超时，先配置
Docker 镜像加速或使用腾讯云网络后重试。`migrate` 必须显示成功后再启动 `api`。

检查日志和接口：

```bash
docker-compose logs --tail=100 migrate
docker-compose logs --tail=100 api
curl -fsS https://api.wusezhishi.com/health
```

应返回 `{"status":"ok"}`。Caddy 会在 80/443 可访问且 DNS 已生效时自动申请并续期证书。

## 更新代码

```bash
cd ~/folk-guide
git pull --ff-only
cd deploy
docker-compose down --remove-orphans
docker-compose build api migrate
docker-compose up -d db
docker-compose run --rm migrate
docker-compose up -d api caddy
```

如果迁移失败，不要删除 PostgreSQL 数据卷；先查看迁移日志并修复后再重试。

## 回滚和备份

发布前保留上一稳定 Git 提交。数据库至少每天备份，并定期在独立环境恢复验证。生产
数据库和 8000 端口不对公网开放，只有 Caddy 暴露 80/443。

## 当前边界

`preview/` 仍含原型页面，包含演示 AI、订单和权益。正式审核前应清理或改用独立的真实
官网目录；本 Compose 配置将其作为暂时的预览站点，不代表这些业务已经可上线。
