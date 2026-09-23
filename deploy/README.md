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

> 注意：服务器当前使用 `docker-compose` 1.x。它不会自动读取 `.env.production`，
> 因此下面每条 Compose 命令都要显式加上 `--env-file .env.production`。

至少替换以下值（如果暂时不开放微信登录，可先把 API 保持在预发布状态，不要提交审核）：

- `POSTGRES_PASSWORD`：随机、较长、建议只使用字母数字，避免 URL 特殊字符；
- `JWT_SECRET`：至少 32 位随机值；
- `ADMIN_API_KEY`：至少 24 位随机值，仅供服务器内部脚本和旧运维接口使用；
- `WECHAT_APP_ID` / `WECHAT_APP_SECRET`：微信后台真实凭据；生产配置校验要求二者同时填写；
- `SITE_DOMAIN` / `API_DOMAIN`：本项目使用 `wusezhishi.com` 和 `api.wusezhishi.com`；
- `CORS_ORIGINS`：实际网站来源，逗号分隔。

### 开启商城与微信支付

代码默认保持 `COMMERCE_ENABLED=false`，避免支付资料尚未配置时误收款。正式开售前：

1. 在微信支付商户平台开通小程序支付，将小程序 AppID 与商户号绑定；
2. 把商户 API 私钥 `apiclient_key.pem` 保存为 `deploy/secrets/wechat_pay_private_key.pem`；
3. 从微信商户平台下载微信支付平台公钥，保存为 `deploy/secrets/wechat_pay_public_key.pem`；
4. 在 `.env.production` 填写商户号、`apiclient_cert.pem` 对应的商户证书序列号、微信支付公钥 ID、APIv3 密钥和两个 HTTPS 通知地址；
5. 完成数据库迁移并通过测试后，最后把 `COMMERCE_ENABLED` 改为 `true`。

`deploy/secrets/` 已只读挂载到 API 容器的 `/run/secrets/`。私钥、公钥、证书以及
`.env.production` 都被 Git 忽略，不能上传到 GitHub。开售后订单后台地址为
`https://api.wusezhishi.com/admin/orders`，未登录访问会跳转到管理员登录页。

截图中的 `apiclient_key.pem` 是商户 API 私钥，当前代码会使用它签名请求；`apiclient_cert.pem`
是商户证书，主要用于确认 `WECHAT_PAY_CERT_SERIAL`；`apiclient_cert.p12` 是同一套商户证书的
打包备份，当前代码不直接读取它。三个文件都只放在服务器密钥目录，不能放进小程序、不能提交 Git，
也不要把文件内容发到聊天中。当前代码还需要你在商户平台另外下载微信支付平台公钥，并填写
`WECHAT_PAY_PUBLIC_KEY_ID`、`WECHAT_PAY_PUBLIC_KEY_PATH` 和 `WECHAT_PAY_API_V3_KEY`；这三个不是截图中的商户证书文件。

在服务器上可用下面的命令读取商户证书序列号（只复制命令输出，不要上传证书）：

```bash
openssl x509 -in deploy/secrets/apiclient_cert.pem -noout -serial
```

把 `serial=` 后面的值填入 `WECHAT_PAY_CERT_SERIAL`。APIv3 密钥是在商户平台设置的
32 字节密钥，不是 `apiclient_key.pem` 的内容，也不是 `.p12` 文件密码。

生成随机值可在服务器执行（只显示在你的终端，不要发到聊天）：

```bash
openssl rand -hex 32   # JWT_SECRET
openssl rand -hex 24   # ADMIN_API_KEY
openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 24  # PostgreSQL密码
```

先启动数据库并执行一次迁移，再启动 API 和 Caddy：

```bash
docker-compose --env-file .env.production up -d db
docker-compose --env-file .env.production run --rm migrate
docker-compose --env-file .env.production run --rm api python -m app.admin_cli create --username owner --display-name "店铺管理员" --role superadmin
docker-compose --env-file .env.production up -d api caddy
docker-compose --env-file .env.production ps
```

首次构建镜像时，服务器需要能访问 Docker 镜像仓库和 PyPI；如果下载超时，先配置
Docker 镜像加速或使用腾讯云网络后重试。`migrate` 必须显示成功后再启动 `api`。

检查日志和接口：

```bash
docker-compose --env-file .env.production logs --tail=100 migrate
docker-compose --env-file .env.production logs --tail=100 api
curl -fsS https://api.wusezhishi.com/health
curl -fsS https://api.wusezhishi.com/api/catalog
```

创建管理员时命令行会要求输入两次密码，密码不会出现在命令历史或 `.env.production`。
账号不开放网页注册。日常订单后台使用管理员账号登录；共享 `ADMIN_API_KEY` 不应提供给
运营人员。以后需要增加发货人员时，可以把上面命令的角色改成 `operator`，该角色能查看
订单并录入运单，但不能修改商品库存。重置密码、停用账号和查看账号可分别执行：

```bash
docker-compose --env-file .env.production run --rm api python -m app.admin_cli reset-password --username owner
docker-compose --env-file .env.production run --rm api python -m app.admin_cli disable --username some-operator
docker-compose --env-file .env.production run --rm api python -m app.admin_cli enable --username some-operator
docker-compose --env-file .env.production run --rm api python -m app.admin_cli list
```

小程序字体由同一 API 域名提供。部署后应确认下面两个地址返回 `200` 且响应类型为 `font/woff2`，否则 iOS 微信无法加载品牌字体：

```bash
curl -fsSI https://api.wusezhishi.com/font-assets/wuse-sans.woff2
curl -fsSI https://api.wusezhishi.com/font-assets/wuse-serif.woff2
```

同时在微信公众平台“开发管理 -> 开发设置”中将 `api.wusezhishi.com` 配置为小程序的请求/下载合法域名。字体资源随 `backend/app/static/fonts/` 部署，授权文本为 `OFL-1.1.txt`，可用于商业产品。

迁移完成后先在订单后台为 6 款商品设置真实可售库存。新商品默认库存为 0，不会在未盘点时被下单。

应返回 `{"status":"ok"}`。Caddy 会在 80/443 可访问且 DNS 已生效时自动申请并续期证书。

## 更新代码

```bash
cd ~/folk-guide
git pull --ff-only
cd deploy
docker-compose --env-file .env.production down --remove-orphans
docker-compose --env-file .env.production build api migrate
docker-compose --env-file .env.production up -d db
docker-compose --env-file .env.production run --rm migrate
docker-compose --env-file .env.production up -d api caddy
```

如果迁移失败，不要删除 PostgreSQL 数据卷；先查看迁移日志并修复后再重试。

## 回滚和备份

发布前保留上一稳定 Git 提交。数据库至少每天备份，并定期在独立环境恢复验证。生产
数据库和 8000 端口不对公网开放，只有 Caddy 暴露 80/443。

## 当前边界

`preview/` 仍含原型页面，包含演示 AI、订单和权益。正式审核前应清理或改用独立的真实
官网目录；本 Compose 配置将其作为暂时的预览站点，不代表这些业务已经可上线。
