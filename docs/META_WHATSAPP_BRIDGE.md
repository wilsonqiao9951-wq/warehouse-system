# Meta WhatsApp 转换层：模拟接入与验收

状态：仅完成代码准备和隔离模拟；真实通道关闭，无 Graph API 网络发送实现、无部署、无付费服务。前端和原有业务接口不变。

## 流程与职责

Meta 原始 webhook → 平台 HMAC 验签 → 校验 WABA / phone_number_id → 持久化 inbox → HTTP 200 → 独立 worker 转换指令 → HMAC 调用原 WhatsApp 适配器 → 持久化 outbox → 发送前复核绑定 → 注入的模拟发送器。

- `app/integrations/meta_whatsapp.py`：独立 FastAPI 工厂 `create_app()`，默认关闭；`Bridge.process_one()` 与 `Bridge.send_one()` 是显式 worker 单步接口，未挂入现有主服务、公开零件网关或后台定时任务。
- `tests/test_meta_whatsapp.py`：用 FastAPI TestClient、真实业务适配器、隔离组织与数据库、FakeSender 执行链路，不访问 Meta。
- 身份来源只有验签成功消息的 `messages[].from`；消息 ID 取 `messages[].id`；原文取 `text.body`。联系人昵称、contacts.wa_id、正文中的号码或组织不能替代可信身份。
- 继续用原适配器管理员个人 Bearer 邀请绑定。转换层不持有管理员令牌，不签发用户身份，不创建组织。
- 确认文字由后端生成，按发送者保存 draft_id 对应关系；必须收到技师完全一致的原文才提交。报告仍为 pending，审核前不能影响建议，不扣库存、不自动完工、不认定适配。

## 入口和签名

`GET /webhooks/meta/whatsapp`：要求 `hub.mode=subscribe`、正确的 `hub.verify_token`，原样返回 `hub.challenge`（text/plain）；不正确为 403。

`POST /webhooks/meta/whatsapp`：`X-Hub-Signature-256: sha256=<hex>`，hex 为 `HMAC-SHA256(Meta app secret, 原始请求字节)`。先验签，后解析 JSON；不是对 JSON 重排之后的内容验签。

Meta app secret、订阅 verify token、内部适配器 channel secret 是三种独立配置，不可复用测试常量。内部协议仍是 `X-Channel-Timestamp` 加 `X-Channel-Signature`，签名输入为 `timestamp + '.' + body`。桥接双方 provider_id / recipient_id 必须一致。

平台请求最大 256 KiB；正文最多 5000 字；整个批次先校验再原子持久化。错误签名 401；错误 WABA/业务号码 403；无效结构 422；超限 413；同一消息 ID 更换内容 409；关闭时 503。状态通知和不支持的媒体类型返回 200，但不会执行业务或回复。

成功 webhook 返回 `{"accepted":true,"text_messages":1}` 仅代表持久接收。业务 403/404/422 等结果保存在 inbox.http_status，不会改变已确认的 webhook HTTP 200，也不会把私有错误详情发送给未授权号码。

Meta 平台签名没有本协议的 timestamp 头，不能虚构该头。桥接使用平台消息 timestamp：超过 24 小时的消息标记 expired，不执行；超过当前时间 5 分钟的消息拒绝。待发送回复也在原消息的 24 小时边界失效，不自动发送模板或收费消息。

参考 Meta 官方资料：[签名和订阅验证](https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/webhooks/start/)、[Cloud API webhook payload reference](https://www.postman.com/meta/whatsapp-business-platform/folder/tduohwq/webhook-payload-reference)。这里只实现与资料对应的消息封装及验签；模拟成功不等于已通过 Meta 实际接入验收。

## 模拟指令

| 技师原文 | 内部动作 |
| --- | --- |
| `绑定 <管理员产生的一次性码>` | bind，仅登记号码可兑换 |
| `我的身份` | query identity |
| `本组织工单` | query work_orders，scope=all 仍只限本组织 |
| `查询 {"resource":"repair_guidance","work_order_id":1}` | query，原接口严格校验资源与字段 |
| `领取工单 1` | claim，保留原文确认 |
| `反馈 {"work_order_id":1,"claim_version":1,"report":{"symptom_codes":["low_flow"],"steps":["Synthetic check"],"outcome":"resolved","result_notes":"Synthetic only"}}` | report_draft，返回完整草稿和 confirmation_text |
| 后端给出的 `确认提交 <随机串>` | report_confirm，仅对应发送者的草稿 |

以上 ID 仅为示例；测试使用实时创建的合成 ID。当前是确定性指令协议，不包含 Muse 模型调用或自然语言意图解析。不会让模型产生手机号、消息 ID 或替用户确认。

回复沿用后端 JSON 数据以保留来源和证据字段；超过 4000 字则提示缩小查询范围，不截断后伪装成完整结果。不支持的指令被记录为 rejected/422，本阶段不发送帮助回复。

## 持久化与重复发送

SQLite 状态文件权限 0600，父目录新建时为 0700；文件包含手机号、绑定指令和私有回复，应保留在私有状态目录，不上传 GitHub。生产部署前还需要确定数据保留/清理策略、磁盘加密、备份和容量监控。

- inbox 按 Meta 消息 ID 和规范化内容指纹去重；重复 webhook 不重复执行业务或建立 outbox；同 ID 换内容拒绝。数据库写锁串行化并发 worker。
- 业务调用后桥接崩溃：inbox 事务回滚，重试仍使用相同 event_id，由原适配器保证写入幂等。
- outbox 每个入站消息 ID 最多一条。发送前重新查询 identity，沿用固定事件 ID 检查绑定代次；撤销、停用或重新绑定后取消旧回复。
- 发送前持久写入 sending；发送器返回消息 ID 后记录 accepted。accepted 只代表发送器受理，不代表 delivered/read。
- 超时等不确定结果记录 uncertain；进程在发送中崩溃留下 sending。两种状态都不自动重发，须未来运维核对。这优先避免重复，但可能漏发；不能宣称外部网络发送 exactly-once。
- FakeSender 接收 `send(payload, key=入站消息ID)`；key 是本地关联标识，不宣称 Meta Graph API 支持该幂等键。
- 新的入站消息 ID 确认同一草稿：反馈仍只有一份，但可回复该新消息。这与重复平台投递不同。
- 本版状态回调仅确认接收，不更新 delivered/read，也不处理发送对账。真实发送器、状态对账和人工恢复工具属于上线前后续工作。

## Muse 独立复现

使用当前 GitHub 提交的**完整仓库**，在独立 workspace 临时目录解压，避免空间太小的 /tmp。使用 Python 3.12；无需真实号码、真实令牌、Meta 账号或公网服务。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export DATABASE_URL="sqlite:///./simulation-bootstrap.db"
export WHATSAPP_ADAPTER_ENABLED=false
python -m scripts.install_catalog_bundle
python -m pytest tests/test_meta_whatsapp.py tests/test_whatsapp_adapter.py tests/test_whatsapp_simulation_kit.py -v --disable-warnings --tb=short --junitxml=meta-simulation-results.xml
```

执行器通过依赖注入启用临时测试应用，不启动监听端口；关闭的生产适配器不受影响。XML 在执行者本地生成，仅包含合成测试结果，不要上传实际生产日志。

应回传：提交 SHA、Python 版本、测试输出、失败项，以及 webhook HTTP 和 inbox.http_status 的区别。旧联调仍是一个测试执行 18 步；不要把 pytest 测试数量当作 webhook 步数。

## 真实接入前仍缺什么

需要另外准备 Meta 业务账号和号码、所需授权、独立秘密配置、受控 HTTPS 入口、常驻 worker、有限超时/重试/监控、Graph API 发送实现、状态回调对账及运维恢复。当前没有生产启动脚本，设置环境变量不能直接开启真实发送。后续明确启用时再核实平台费用和部署费用，本次不注册、不购买、不启用。
