# WhatsApp worker、队列监控及状态库维护（模拟阶段）

本阶段准备了常驻循环和本机运维工具。CLI **只支持模拟启动**，不读取 Graph token、不创建公网入口、不启动真实通道、不修改前端，不产生平台费用。业务接口仍通过原签名适配器，模拟测试同时覆盖真实适配器与隔离组织数据。

## 生命周期和并发边界

代码：`app/integrations/meta_runtime.py`、`scripts/meta_worker.py`。

- worker 前台常驻轮询，一次处理一条 inbox，再检查停止请求，随后最多发送一条 outbox。
- 默认空闲轮询 1 秒；处理异常时最多退避 30 秒。只写错误计数，不记录可能含凭证或消息内容的异常正文。业务失败记录、sending、uncertain 不因 worker 重启自动重发。
- 支持本地停止请求和 SIGINT/SIGTERM：等待当前调用返回，退出前写 stopped。停止请求到达后不再开始下一次发送。遇到中断写 interrupted；SIGKILL 来不及写状态，监控以“running 但锁已释放”识别异常退出，下次启动补记 interrupted。
- 同一状态文件全程持有操作系统 flock。进程退出时 OS 释放锁，不根据 PID 或心跳过期抢锁。锁文件永不自动删除。符号链接归一到同一路径，拒绝硬链接状态文件。
- 第二个 worker、人工取消/重试、备份和清理必须取得同一把锁，否则立即拒绝。停止请求、监控及 webhook 持久接收仍可进行。
- 此方案仅适用于 **macOS/Linux 单机本地磁盘**。不是多服务器分布式锁；不支持共享网络磁盘、多副本部署或绕过 Worker 直接在另一进程调用 Bridge.send_one。未来多节点部署需另行设计。
- 心跳在处理循环间更新；超过 60 秒标记 stale。心跳不是强制中断机制，也不证明消息未发出。注入的实际 HTTP 客户端必须有有限超时。

## 可直接运行的安全模拟

使用独立 workspace 临时目录，不使用现有业务库或生产 .env。安装仓库 requirements.txt 后：

```bash
python -m scripts.meta_worker init --state ./worker-simulation.sqlite3 --simulation
python -m scripts.meta_worker start --state ./worker-simulation.sqlite3 --simulation
```

init 仅能创建全新的文件，内置一条合成身份查询；已存在文件拒绝覆盖。start 必须提供 --simulation 且数据库含专用模拟标记，只有合成 adapter/sender，无真实网络发送。该 CLI 的 adapter 是确定性演示替身，不表示实际业务身份已经验证；完整测试另用原适配器和隔离数据库验证业务链路。

在另一个终端检查或请求停止：

```bash
python -m scripts.meta_worker monitor --state ./worker-simulation.sqlite3
python -m scripts.meta_worker stop --state ./worker-simulation.sqlite3
```

也可在运行终端按 Ctrl+C。stop 返回的是请求已写入，不等于进程已经退出；再次 monitor 确认 state=stopped、lock_held=false。空闲时通常一个轮询周期响应；异常退避时最长等待退避结束，正在进行的调用须等待其返回。进程演示完成后不会自动重启。

有限循环演练：`start --state ./worker-simulation.sqlite3 --simulation --cycles 2`。省略 --simulation 会拒绝启动；没有生产启动参数、launchd/systemd 安装或付费服务配置。

## 队列监控

monitor 输出 inbox/outbox/attempt 状态计数、callback matched/unmatched/conflict 数量、最旧待处理/待发消息年龄、worker 心跳和错误次数、数据库大小、可用磁盘。最多列出 100 条 sending/uncertain/failed 消息 ID，不输出号码、消息正文或凭证。

告警是本机 JSON 指标，**不会向 WhatsApp 或外部监控发送通知**：

- 待处理/待发超过 100 条或最老超过 5 分钟：backlog。
- 有队列但无锁持有者：queue_without_worker。
- running 无锁或 interrupted：worker_interrupted；心跳超过 60 秒：heartbeat_stale。
- 连续处理错误：worker_errors；sending/uncertain/failed：delivery_attention。
- unmatched/conflict：callback_attention；可用空间少于 256 MiB：disk_low。

状态库及这些工具仅供受信任主机管理员使用，不是普通技师或 Muse 的跨组织查询接口。监控初次打开旧库会初始化运行元数据和既有兼容迁移，不改业务主库。

## 备份和恢复

先停 worker 并确认锁释放；此后 webhook 仍可接收，SQLite online backup 获得内部一致的时间点快照。备份范围仅为桥接状态库，不包含主业务数据库、适配器绑定库或凭证；正式恢复整套系统时还需要协调这些库，不能把单库回滚称为全系统恢复。

```bash
python -m scripts.meta_worker backup --state ./worker-simulation.sqlite3 \
  --destination ./worker-backup.sqlite3 --operator simulation-admin
```

目标必须不存在，权限 0600，输出 SHA256、大小和 integrity=ok；请保存这些结果。原库记录 backup 审计（在快照完成后写入，故本次 backup 审计不在该快照中）。

```bash
python -m scripts.meta_worker restore --state ./worker-restored.sqlite3 \
  --backup ./worker-backup.sqlite3 --sha256 '<备份输出的SHA256>'
```

恢复只允许全新目标，先核对 hash 和源库完整性，再验证恢复库完整性；不覆盖旧库、不切换现有服务、不自动启动 worker。恢复后的 sending/uncertain 继续等待对账/人工核查；去重指纹、发送尝试与审计保留。回滚到较旧备份会丢失快照之后的事件记录，可能重复处理快照后已发送的消息，因此不能直接切换生产库重放；需停通道并与后续事件及平台记录核对。

## 清理与保留策略

默认保留正文 30 天，最短允许 7 天。**先预览，再明确应用，应用前必先备份。**

```bash
python -m scripts.meta_worker cleanup --state ./worker-simulation.sqlite3 --retention-days 30
```

返回候选消息 ID、摘要与 confirmation。仅针对超过期限、已结束的消息：无回复，或回复为 delivered/read/cancelled/expired；pending、failed、accepted、sent、sending、uncertain 以及含未解决尝试的记录保留。

```bash
python -m scripts.meta_worker cleanup --state ./worker-simulation.sqlite3 \
  --retention-days 30 --apply --confirmation '<预览返回的confirmation>' \
  --backup ./before-cleanup.sqlite3 --operator simulation-admin
```

取得锁、成功备份、重新核对候选后，在单个事务中清空 inbox.text 与 outbox.text.body。候选变化或备份失败不改正文。仅逻辑移除正文：保留 message ID、原始去重指纹、发送目标与必要关联、全部 attempts、callbacks、绑定草稿关联、delivery_audit、worker_audit、maintenance_audit，因此旧消息重放仍去重，迟到回调仍可核对。操作系统密钥、业务库、原适配器库不在该清理范围。

元数据和审计目前不自动删除，备份也不自动删除。SQLite 文件不一定变小，旧页面及备份可能仍含正文；这不是安全擦除，也不是磁盘容量回收工具。生产阶段需根据业务保留要求另行确定加密备份、离机保管、备份生命周期和容量扩展；当前以监控提醒增长，不冒险删除去重证据。没有新增自动化定时任务。

## Muse 独立验收

完整仓库、Python 3.12、隔离 venv，设置独立 DATABASE_URL 后：

```bash
export DATABASE_URL="sqlite:///./simulation-bootstrap.db"
export WHATSAPP_ADAPTER_ENABLED=false
python -m scripts.install_catalog_bundle
python -m pytest tests/test_meta_runtime.py tests/test_meta_delivery.py tests/test_meta_whatsapp.py tests/test_whatsapp_adapter.py tests/test_whatsapp_simulation_kit.py -v --disable-warnings --tb=short
python -m pytest -q --disable-warnings --tb=short
```

测试包含真实子进程启动/互斥/SIGKILL/重启/SIGTERM、本地 stop、适配器暂时失败、已发中断不重发、备份恢复、清理后的重复事件与迟到状态、过期保留规则、陈旧预览拒绝、别名锁。所有子进程在测试结束时退出；全部使用模拟发送器，无真实 Meta 调用。
