# WhatsApp 部署接线与回滚演练

本阶段准备生产部署结构，真实通道保持关闭。`scripts.meta_deployment` 仅接受
`disabled` 和 `simulation`；不提供生产启用开关、不读取 Meta 生产凭证、不调用 Graph。
即使误设旧的 enable 环境变量也会拒绝启动。账号和密钥占位不能直接转成上线配置。

## 服务与路由

| 组件 | 入口 | 数据与职责 | 外部可见性 |
| --- | --- | --- | --- |
| 原业务 API | api:8000 | PostgreSQL、用户/组织/库存/工单 | 原 API 域名，沿用认证 |
| webhook | webhook:8012 | 验签、队列入库、状态回调对账 | 独立域名仅 `/webhooks/meta/whatsapp` |
| 适配器 | adapter:8011 | 个人绑定、签名业务请求、组织隔离 | 不映射主机端口；管理员从受控内网操作 |
| worker | 无 HTTP 端口 | 拉取入站、调用适配器、发送账本 | 私有常驻进程；本版默认立即安全退出 |
| Caddy | 80/443 | HTTPS 终结与路由 | webhook 域名其他路径一律 404 |

Compose 覆盖文件 `docker-compose.whatsapp.yml` 沿用原业务 API、PostgreSQL 和证书卷，
新增独立 adapter 状态卷及 webhook/worker 共用的 bridge 状态卷。卷只作单机本地磁盘使用，
不要在 NFS 或多副本上运行。默认关闭时不打开通道状态数据库、不执行迁移或清理。
原业务 API 的启动仍执行已有 Alembic 迁移，因此现在不要对现有服务运行 `up`。

HTTPS 配置 `deploy/Caddyfile.whatsapp` 保持原业务域名路由，阻断该域名的通道路径；
独立 WhatsApp 域名仅透传原始 webhook 请求（包含平台签名头），限制请求体 256KB。
无公开绑定、worker、恢复或监控接口，不启用访问日志以避免记录验证 token。

## 配置交接

将 `deploy/production.env.example` 与 `deploy/whatsapp.env.example` 的变量整理到仓库外的
0600 私有配置文件；不要把真实密码写回 example，也不要发给 Muse 或提交 Git。

- 仍需提供：批准的主机和两个域名、Meta WABA ID、业务号码 ID/号码授权、受支持 Graph 版本。
- 仍需安全注入：App Secret、webhook verify token、system user access token、独立适配器签名密钥；
  模板列出的 `*_FILE` 是未来接线清单，本版不读取这些文件。
- 业务适配器必须复用业务库及 JWT 配置，不能另建组织目录；worker 只通过内网 HTTP 调用适配器。
- 本版 Compose 将通道模式固定为 disabled；不能通过环境文件开启真实发送。
- 后续经批准的生产实现须把 bridge 状态定位 `/state/bridge.sqlite3`、绑定状态定位
  `/adapter-state/channel.sqlite3`，加载只读 secret 文件并校验所有占位已替换，再进行官方沙箱验收。
  本版这些生产状态路径和凭证为预留接口，尚未实现 live factory。

只检查配置，不启动、不申请证书：

```sh
docker compose --env-file /secure/warehouse.env \
  -f docker-compose.production.yml -f docker-compose.whatsapp.yml config --quiet
```

不得将公开测试密钥用作生产凭证；也不得把 simulation 模式挂在真实域名、真实数据库或真实技师上。

## 隔离模拟验证

```sh
DATABASE_URL=sqlite:///./simulation-bootstrap.db python -m pytest -q \
  tests/test_meta_deployment.py tests/test_meta_runtime.py tests/test_meta_delivery.py \
  tests/test_meta_whatsapp.py tests/test_whatsapp_adapter.py tests/test_whatsapp_simulation_kit.py
```

部署测试自行创建临时目录、`.simulation-only` 标记、独立业务/适配器/bridge SQLite 库和合成用户。
启动两个真正的 loopback uvicorn 进程及独立 worker，经 HTTP 管理员邀请、Meta 原始体签名绑定、
查询身份，发送器仅 SyntheticSender。模拟工厂要求 APP_ENV=test、业务库准确位于该目录，
拒绝公网适配器 URL、代理继承、URL 内嵌凭证及 live 标志。此保护不将模拟账号变为生产身份。

覆盖：默认 503/worker 不处理队列，错误配置拒绝、webhook challenge、真实 HTTP 绑定、
第二 worker 被文件锁拒绝、SIGTERM 正常停止、备份完整性、回滚 disabled 后 webhook 503、
恢复 simulation 后旧事件不重复产生发送尝试、新消息正常处理、停机审计保留。
已有专项测试继续覆盖组织隔离、反馈确认、发送不确定、回调乱序和人工恢复。

`.github/workflows/whatsapp-deployment.yml` 在一次性 CI 容器中校验 Compose 和 Caddy，
以 `http://*.localhost` 避免 DNS/ACME/证书申请；实际验证代理到关闭 webhook 返回 503、
私有路径返回 404，并停止服务。CI 最后的 `down -v` **仅用于 CI 临时资源，不适用于部署主机**。
此测试不是公网 TLS 证书验收，也不代表 Meta 已接通。

## 启停与回滚操作顺序（正式上线前仍须批准）

1. 记录精确提交、镜像摘要、私有配置版本和数据库迁移版本。先停止新入站流量，再停止 worker；
   为 HTTP 调用和 SQLite 等待保留 90 秒优雅退出窗口，检查 worker 审计和文件锁释放。
2. 停止 adapter 与 webhook 写入；协同备份业务 PostgreSQL、adapter SQLite、bridge SQLite、uploads。
   bridge 使用 `scripts.meta_worker backup`，校验 SHA256，恢复仅写新文件；其他库按各自原生方式备份。
3. 更新镜像/配置前确认持久卷名字不变。启动顺序：数据库/业务迁移 → API → adapter/webhook → worker。
   本版 worker 默认退出为 0 是“禁用”，不是运行就绪；health enabled=false 也不代表真实可用。
4. 发现验签、组织隔离、重复发送或迁移异常时，停止 worker 和入站写入，保留所有卷与日志。
   先回退至本版 disabled 配置，验证 webhook 503，队列没有新发送尝试。
5. 仅在旧版本兼容现有 schema 时替换镜像；不盲目执行 downgrade，不用旧备份覆盖实时状态。
   已对外发送后的库回退可能抹去去重记录。sending/uncertain 必须保留，人工核查后按原恢复流程处理。
6. 演练恢复用新文件验证后再决定切换；生产切换需同时核对业务提交、绑定代次、发送账本和回调。
   不删除 worker 锁文件，不清空事件/发送尝试/审计，不通过重启自动重发不确定消息。

模拟测试验证的是配置回滚与保留状态重启，不声称验证任意历史版本的 schema 降级。
生产镜像固定摘要、secret 文件加载、真实常驻服务/监控告警及官方沙箱均属于下一阶段上线门槛。
本阶段不修改前端，不购买主机/域名，不启用任何 Meta 付费发送。

参考：[Compose 合并规则](https://docs.docker.com/reference/compose-file/merge/)、
[Caddy 请求体限制](https://caddyserver.com/docs/caddyfile/directives/request_body)。
