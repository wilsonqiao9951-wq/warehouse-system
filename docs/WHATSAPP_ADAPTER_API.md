# WhatsApp 个人身份与自动调用 API（待平台接入）

配套文件：[OpenAPI接口定义](WHATSAPP_ADAPTER_OPENAPI.json) · [验证结果与复现步骤](WHATSAPP_VALIDATION.md)。

状态：后端已准备，使用模拟签名消息测试；默认关闭，不接收真实 WhatsApp 消息、不自动发送消息、不产生外部服务费用。前端未修改，现有公开目录入口未增加私有接口。

## 手机号如何验证身份

管理员先将技师的 WhatsApp 号码登记到本组织已有的 ENGINEER 账户。号码格式为国家码加号码的数字串，不含加号、空格或括号。绑定邀请有效期10分钟，只能被同一预登记号码的可信签名事件兑换。单纯在聊天或JSON中填写电话号码不代表拥有该号码。

消息平台必须先验证真实WhatsApp来源，随后由平台服务端/受控连接器签名。签名密钥不能交给模型或普通聊天；user_text必须是原始技师消息，不能让模型伪造确认文字。收到的sender_id、recipient_id、chat_type、event_id必须来自平台事件，而非用户文本或模型生成。真实平台验证细节须等Muse提供能力说明后实现。

绑定后，后端按号码映射user_id、organization_id和专用渠道设备，每次重查账户、组织、角色与设备是否有效。手机号不能指定或切换组织；改号须撤销旧绑定、重新登记。离职需撤销绑定或停用账户；已停用账户立即拒绝后续调用。支持撤销后由同组织管理员重新绑定，旧事件不可用于新绑定。首版只允许一对一聊天。

## 接口与部署边界

这是独立适配器，不挂载到当前主服务或公开隧道。入口 `scripts.whatsapp_adapter:app`。未来在受控本机端口启动，例如：

```sh
../warehouse-system/.venv/bin/python -m uvicorn scripts.whatsapp_adapter:app --host 127.0.0.1 --port 8011 --no-access-log
```

默认 `WHATSAPP_ADAPTER_ENABLED` 不为 `true`，除health外所有请求返回503。启用还需通过服务端秘密配置提供至少32字符的随机 `WHATSAPP_ADAPTER_SIGNING_SECRET`，并固定 `WHATSAPP_ADAPTER_PROVIDER` 和 `WHATSAPP_ADAPTER_RECIPIENT`。本轮没有启动该服务或配置真实密钥。

绑定与管理员API只允许本机管理员调用；将来公开时仅暴露签名events路径，不公开绑定管理。生产接入前还需平台验签转换、发送结果处理、流量限制、密钥轮换和稳定运行方案。不能把当前模拟契约当作Meta原生Webhook。

| 方法/路径 | 用途 | 认证 |
|---|---|---|
| GET /health | 开关状态 | 无敏感数据 |
| POST /api/channels/whatsapp/bindings | 创建绑定邀请 | 管理员个人Bearer及现有设备认证 |
| DELETE /api/channels/whatsapp/bindings/{sender_id} | 撤销绑定与渠道设备 | 本组织管理员 |
| POST /api/channels/whatsapp/events | 绑定兑换、查询、领取、反馈草稿和确认 | 服务端消息签名 |
| GET /openapi.json | 接口结构 | 仅启用后可读 |

管理员创建绑定示例（数字为占位值，不可原样用于真实技师）：
```json
{"user_id":123,"sender_id":"15550000001"}
```
组织从管理员登录决定，不接受organization_id。响应含一次性binding_code、有效期和待绑定号码。此短期码只用于绑定，不是API密码；仅交付给目标技师。新邀请、激活、撤销记录审计。不会使用管理员身份执行技师业务。

## 签名契约 whatsapp-adapter 0.1

适配器使用自定义签名头（不是Meta的X-Hub-Signature-256）：

```text
X-Channel-Timestamp: <Unix秒时间戳>
X-Channel-Signature: sha256=<HMAC-SHA256十六进制>
签名原文 = 时间戳UTF-8字节 + 一个英文句点 + HTTP请求体原始字节
```

时间偏差最多5分钟。重试可刷新时间戳并重签，但保留相同事件ID、消息内容和参数。签名后不能重排或重新序列化body。适配器最多接受32KiB消息。

基础信封示例：
```json
{
  "provider_id":"simulation",
  "recipient_id":"simulation-line",
  "sender_id":"15550000001",
  "event_id":"unique-platform-message-id",
  "chat_type":"individual",
  "action":"query",
  "user_text":"查询我的工单",
  "arguments":{"query":{"resource":"work_orders","scope":"mine"}}
}
```

provider_id与recipient_id必须匹配服务端配置；实际接入应使用真实提供商实例及接收业务账号标识。拒绝群聊、未知字段、模型指定组织或任意URL调用。事件ID不能重复用于不同内容。读请求重试重新验证身份并查询当前权限范围，不复用旧私有结果。

## 动作流程

1. `bind`：arguments仅含binding_code，由预登记的真实发送者兑换。绑定成功后普通查询无需每次登录。
2. `query`：arguments仅含query。允许identity、work_orders、repair_guidance、symptoms、followups、followup_stats、repair_recurrences、repair_statistics。沿用Muse查询字段与来源；默认scope=mine。scope=all仍仅本组织及已有权限。
3. `claim`：arguments为work_order_id；user_text必须精确为`领取工单 123`（替换真实ID）。只在技师明确领取时调用，不因查询而自动领取。工单已被另一设备或技师领取时409，不自动接管。
4. `report_draft`：arguments含work_order_id、claim_version和report，生成不可变草稿，不提交报告。claim_version来自当前工单/领取响应。当前用户须为本设备领取人。草稿15分钟有效。
5. `report_confirm`：arguments仅含draft_id；user_text必须是技师原始回复，且与草稿返回的confirmation_text完全一致。确认仅对该用户/组织/草稿有效，内容变化须重新生成草稿并再次确认。

反馈草稿示例：
```json
{
  "work_order_id":123,
  "claim_version":1,
  "report":{
    "symptom_codes":["low_flow"],
    "steps":["技师实际执行的检查"],
    "outcome":"unresolved",
    "result_notes":"实际测量结果及尚待核验的信息"
  }
}
```

草稿返回report完整内容、draft_id、confirmation_text、expires_in、submitted=false。Muse必须先展示工单及报告内容再请求确认。报告支持既有repair_followup结构，包括复发、观察天数与明确实际用料；不自动补写未知事实。提交时复查原领取版本、机型/症状与零件归属，跨组织零件或前次报告被拒绝。

确认后的报告保持pending，人工审核后才影响建议。报告提交不自动出库、不自动完工、不认证适配。

## 去重与回复

事件按event_id去重且核对内容指纹、发送者与绑定代次。报告使用独立稳定键 `wa-draft-<draft_id>`；重复确认、不同事件ID的同草稿确认、并发确认及适配器在主库提交后崩溃的重试都不会重复建报告。账号/设备被停用后，即使重放成功事件也拒绝。

响应包含reply_to（可信发送者与私聊类型）、event_id、replayed、data、delivery_status=not_sent。这是供Muse平台发送的响应指令，不表示已发送WhatsApp消息。真实平台还需按event_id记录发送状态并去重，避免重复回复。不能把其他技师或群聊地址替换到reply_to。

绑定/事件/草稿使用本机独立SQLite状态库（默认artifacts/whatsapp/channel.sqlite3，0600），业务工单和报告仍使用现有主库。两个库不是同一事务；报告稳定幂等键覆盖主库提交后适配器中断的重复提交窗口。备份与恢复需同时保留渠道状态库，不能随意清空。绑定失败或崩溃可能留下未使用的渠道设备，后续须管理员核查，不影响已有工单设备。

401=签名错误或超时；403=未绑定/停用/渠道不匹配；404=权限范围内无该记录；409=事件内容冲突、领取版本变化或设备冲突；410=草稿过期；422=参数或确认文字错误；503=通道未启用。

## 当前验证与等待项

模拟HTTP API验证：管理员组织限制、真实预登记发送者匹配、一次性码、签名/时间窗口/目标账号、群聊拒绝、个人身份、本组织工单、跨组织指导/反馈拒绝、草稿所有者、反馈确认、重复/并发/重启/提交后崩溃重试、领取版本、撤销与停用、待审核证据不影响指导。

测试使用独立测试数据库，无真实WhatsApp消息、付费请求或真实客户数据。等Muse确认可信身份、服务端签名和自动回复能力后，才开发对应平台转换与发送接口。
