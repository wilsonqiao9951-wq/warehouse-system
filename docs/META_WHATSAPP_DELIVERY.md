# Graph API 发送、状态对账与人工恢复（模拟验收）

> 新增：[worker、监控、备份与保留策略](META_WHATSAPP_WORKER.md)。仅提供模拟 CLI 启动，真实通道仍关闭。
本阶段已准备发送器代码和运维工具，真实通道仍关闭；没有创建账号、购买服务、启动 worker 或发出 Meta 网络请求。测试使用 httpx.MockTransport/FakeSender、隔离数据库和合成号码。不能把测试通过称为真实手机收发成功。

## 发送边界

`app/integrations/meta_delivery.py::GraphSender` 默认 `enabled=False`；不读取环境变量，也没有生产启动脚本。显式配置 numeric phone_number_id、api_version、独立 token，未来才可以接入真实传输。`v25.0` 只是测试路径样例，不表示已核实上线时应该选择该版本。

请求固定为 `https://graph.facebook.com/{api_version}/{phone_number_id}/messages`；Bearer token 仅放请求头。连接超时 3 秒、读写等阶段超时 10 秒，不跟随重定向、不自动重试，不记录 token/完整平台错误正文。没有模板发送、主动群发或自动收费重试。

每次实际发送尝试先持久化唯一 attempt ID，再发请求；以 `biz_opaque_callback_data` 携带随机 attempt ID，不携带手机号、组织或工单内容。它是回调关联值，不是平台幂等键。POST 成功且返回唯一有效 message ID，才记 accepted；这不等于 delivered。

| 结果 | 本地处理 |
| --- | --- |
| 禁用或缺 token | failed，无网络调用 |
| HTTP 4xx，包括 429 | failed，不自动重试，保留操作人员核查入口 |
| 网络超时、5xx、重定向、无有效成功回执 | uncertain，不自动重试 |
| 进程在发送中中断 | sending，待对账/人工核查 |
| 有效成功回执 | accepted，保存平台 message ID |

## 回调对账

继续使用 `POST /webhooks/meta/whatsapp`，先对原始请求体验证 Meta 签名，再校验 WABA 和 phone_number_id。一个批次的消息和状态全部校验后原子入库。状态支持 sent/delivered/read/failed，其余类型忽略。返回 `status_events` 是本次解析数量，不是新增去重记录数。

- 状态按规范化指纹去重，完整历史保留；失败只保留数字 error code，避免把平台错误文本写入共享日志。
- 优先按 provider message ID 匹配；响应丢失时用 callback attempt ID 关联。收件号码必须与保存的回复目标一致，两个关联键不能互相冲突。
- 未匹配回调保留为 unmatched；HTTP 回执到达后再次对账。号码/关联键冲突标记 conflict，不修改发送状态。
- 回调先于 HTTP 回执、或回调送达后 HTTP 超时，均不会退回 accepted/uncertain。
- 已读不会退回已送达/已发送；已送达不会被迟到 failed 覆盖。failed 后的迟到 sent 不会自动恢复成功；delivered/read 可用更强的送达证据更新它。
- 人工重试产生新 attempt，旧 attempt 的失败不会覆盖新 attempt。任意一次尝试确认 delivered/read，整条回复体现该结果，尚未发出的人工重试被取消。
- 如果新尝试已进入外部网络调用，再到达旧尝试的送达回执，无法撤回已发请求；不能保证外部 exactly-once。每次尝试的历史均保留用于核查。
- 旧版 outbox 自动补入 legacy attempt，不清空旧数据库。旧版不带 callback 的不确定发送，若无法按已知 message ID 匹配，继续保留人工核查。

参考：[Meta 消息 API](https://www.postman.com/meta/whatsapp-business-platform/folder/13382743-ba8d099d-007e-4b52-b9f2-3cf3c60e4fbc)、[Meta 状态字段](https://www.postman.com/meta/whatsapp-business-platform/folder/fuaee8l/statuses-object)。本轮 Meta developer 消息参考页访问受限（429）；callback 回传已模拟，真实接入时仍须以选定版本进行官方沙箱验收，不能据此声称真实回调已验证。

## 本机人工恢复

工具是服务器本地运维入口，不是供技师或 Muse 调用的 HTTP API。访问该私有 SQLite 文件即具有跨组织运维权限，应仅限受信任主机管理员。operator 是审计标签，不替代主机登录身份；不要把数据库或权限给普通技师。CLI 不输出手机号、回复正文或凭证。

先检查现有私有状态文件（路径由运维指定，不自动扫描）：

```bash
python -m scripts.meta_delivery_recovery --state /private/path/meta.sqlite3
python -m scripts.meta_delivery_recovery --state /private/path/meta.sqlite3 --id '<入站消息ID>'
python -m scripts.meta_delivery_recovery --state /private/path/meta.sqlite3 --events
```

单条检查返回 message、各 attempts 与 confirmation 哈希。只有 failed/uncertain/sending 可以操作；必须提供操作人员、至少 10 字符的证据/理由和当前哈希。状态变化后旧哈希失效，必须重查。

```bash
python -m scripts.meta_delivery_recovery --state /private/path/meta.sqlite3 \
  --id '<入站消息ID>' --action cancel --operator '<主机管理员>' \
  --reason '<核查结论与证据，勿写凭证>' --confirmation '<当前哈希>'
```

重试用 `--action retry`；uncertain/sending 还需 `--accept-duplicate-risk`，表示已核查但仍可能重复。sending 在 5 分钟内禁止人工操作；操作前必须停止相关 worker，确认没有正在进行的请求。此时间限制不是分布式锁或“未送达”的证明。

重试仅把记录放回 pending，不在 CLI 内联网发送；过期消息不能重试。worker 下一次发送仍重新检查时效、身份和绑定代次。取消、重试及其原状态、理由、时间写入 delivery_audit。已取消记录仍可接收迟到的真实送达证据，但不会自动重新发送。

## 独立复现

从本次提交下载完整仓库，在 Python 3.12 的全新 venv 中安装 requirements.txt。设置独立 DATABASE_URL，不使用生产 .env：

```bash
export DATABASE_URL="sqlite:///./simulation-bootstrap.db"
export WHATSAPP_ADAPTER_ENABLED=false
python -m scripts.install_catalog_bundle
python -m pytest tests/test_meta_delivery.py tests/test_meta_whatsapp.py tests/test_whatsapp_adapter.py tests/test_whatsapp_simulation_kit.py -v --disable-warnings --tb=short
python -m pytest -q --disable-warnings --tb=short
```

新增覆盖 MockTransport 请求/错误分类、回调重复和乱序、提前回调、超时对账、跨收件人冲突、重试与迟到旧回执、状态快照竞态、过期/撤销、旧状态升级和 CLI 审计。无需真实 token、Meta 账号或公网服务。

尚未完成真实部署、Meta 账号/号码授权、生产密钥注入、常驻 worker 与监控、队列容量/保留策略及官方沙箱联调。费用在明确启用前另行核实。本阶段不改前端，不开通任何付费服务。
