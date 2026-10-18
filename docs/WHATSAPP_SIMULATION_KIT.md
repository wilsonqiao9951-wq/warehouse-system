# 发给 Muse：WhatsApp 模拟联调包

目的：验收手机号绑定、本组织工单、反馈确认及重复消息处理。仅使用隔离测试库和合成号码，不启用真实WhatsApp、不发送消息、不配置付费服务、不修改前端。当前公网目录地址不能调用这些私有API。

- [机器可读请求与预期结果（18步）](../tests/fixtures/whatsapp_simulation.json)
- [直接执行这份清单的测试](../tests/test_whatsapp_simulation_kit.py)
- [模拟数据与签名发送助手](../tests/test_whatsapp_adapter.py)
- [API协议](WHATSAPP_ADAPTER_API.md)
- [OpenAPI](WHATSAPP_ADAPTER_OPENAPI.json)

## 运行方式与测试身份

本包通过FastAPI TestClient在进程内执行HTTP请求，没有对外监听端口，也不调用Meta/Muse的真实API。`test_whatsapp_adapter.py`的setup创建两个组织、组织A管理员/技师、组织B技师以及各组织一张合成工单。每次运行自动创建和清理测试数据库，绑定/草稿状态也使用临时目录。

合成发送者号码：15550000001；错误发送者：15550000002。只用于模拟，不能向号码发送真实消息。

测试初始化后取得：
- `$tech_id`：组织A的技师ID；组织A的ID在此测试中固定为1。
- `$own_order_id`：组织A工单ID。
- `$foreign_order_id`：组织B工单ID。
- 管理员令牌：测试内生成，仅用于绑定邀请，不交给普通消息接口。

后续提取变量：binding_code、claim_version、draft_id、confirmation_text、report_id。不要把这些变量写死。JSON清单中的 `$变量` 必须替换为对应值；整数ID保持整数类型。

在独立开发环境安装项目依赖后运行：
```sh
python -m scripts.install_catalog_bundle
python -m pytest tests/test_whatsapp_simulation_kit.py tests/test_whatsapp_adapter.py -q
```

结果：本次本机运行 **10 passed**，其中1项执行完整18步清单，另9项覆盖并发、崩溃重试、撤销和到期等边界。此结果不表示Muse/WhatsApp真实连接成功。

没有代码执行环境的Muse，可以先做协议审核，逐项标记“文档符合／需适配／无法确认”，不能把阅读清单当作执行通过。不要要求启用真实通道来运行这套测试。

## 请求组装和签名

清单是测试用例格式，不可把整个case对象直接POST。带admin_invite的步骤只向 `/api/channels/whatsapp/bindings` 发送admin_invite内容，使用合成管理员Bearer身份。

其余步骤向 `/api/channels/whatsapp/events` 发送以下结构，以清单的action、arguments、event_id和text替换：
```json
{
  "provider_id":"simulation",
  "recipient_id":"simulation-line",
  "sender_id":"15550000001",
  "event_id":"simulation-example-001",
  "chat_type":"individual",
  "action":"query",
  "user_text":"查询我的工单",
  "arguments":{"query":{"resource":"work_orders","scope":"mine"}}
}
```

phone覆盖sender_id；text对应user_text，未提供时是空字符串。event_id至少8字符。失败/重试步骤也必须按清单原文构造，不擅自改action或user_text。

签名助手的模拟密钥为测试代码中的 `SECRET`，它是公开的测试常量，不是部署凭证，严禁用于真实服务。

```python
raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
stamp = str(int(time.time()))
signature = "sha256=" + hmac.new(
    simulation_secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256
).hexdigest()
# Content-Type: application/json
# X-Channel-Timestamp: stamp
# X-Channel-Signature: signature
# 必须发送相同raw字节，不能签名后重新序列化JSON。
```

签名有效时间窗口5分钟。重试可更换时间戳及签名，但必须保留原消息内容和event_id。整个流程应在绑定码10分钟、反馈草稿15分钟有效期内完成。

## 顺序请求及预期结果

| 步骤 | 请求/操作 | HTTP与关键断言 |
|---|---|---|
| 01 | 未绑定号码query identity | 403 |
| 02 | 管理员邀请本组织tech_id和15550000001 | 200；提取binding_code；expires_in=600 |
| 03 | 15550000002用上述码bind | 403；不会消耗正确号码的绑定 |
| 04 | 正确号码bind | 200；data.bound=true、个人user_id、本组织organization_id=1 |
| 05 | 新事件ID再次用同一码bind | 403；一次性码已消耗 |
| 06 | query identity | 200；个人身份正确；reply_to为15550000001 |
| 07 | query work_orders，scope=all | 200；data仅1条，id=own_order_id；无组织B工单 |
| 08 | 查询foreign_order_id的repair_guidance | 404；不返回外组织工单详情 |
| 09 | query里伪造organization_id=2 | 422；不能用参数切换组织 |
| 10 | claim own_order_id | 200；原始user_text必须为“领取工单 实际ID”；提取claim_version |
| 11 | report_draft | 200；submitted=false；confirmation_required=true；提取draft_id及confirmation_text；报告数仍0 |
| 12 | report_confirm，但user_text仅为“确认” | 422；报告数仍0 |
| 13 | report_confirm，user_text精确等于返回值 | 200；report_id生成、review_status=pending、guidance_eligible=false；报告数1 |
| 14 | 完全重发13的事件ID、文字和参数 | 200；相同report_id；外层replayed=true；data.replayed=true；报告数1 |
| 15 | 新事件ID确认同一草稿，文字不变 | 200；相同report_id；外层replayed=false、data.replayed=true；报告数仍1 |
| 16 | 使用13的event_id，改成query identity | 409；同一ID不能换内容；报告数仍1 |
| 17 | 查询本工单维修指导 | 200；data.reviewed_guidance.reviewed_resolved_case_count=0；pending报告不进入已审核指导 |
| 18 | 错误密钥签名query identity | 401 |

清单中的expect使用点路径断言字段（如data.0.id），extract用于保存变量，list_length用于列表长度，reports_count由测试数据库核实。不要把这些测试控制字段发送给API。

## 反馈请求示例

步骤11的arguments：
```json
{
  "work_order_id":"$own_order_id",
  "claim_version":"$claim_version",
  "report":{
    "symptom_codes":["low_flow"],
    "steps":["合成联调：未执行真实维修"],
    "outcome":"resolved",
    "result_notes":"仅验证接口，不作为已审核维修证据"
  }
}
```
占位ID和版本替换后必须是整数。这里resolved只是合成测试数据，不表示发生了真实维修。

步骤13的关键字段：
```json
{
  "event_id":"simulation-confirm-001",
  "action":"report_confirm",
  "user_text":"$confirmation_text",
  "arguments":{"draft_id":"$draft_id"}
}
```
仍需加完整公共信封字段并签名。步骤14完全复用这个body，不能连user_text都改成“再次确认”。步骤15只替换event_id。

每次成功消息响应包含reply_to、event_id、replayed、data、delivery_status=not_sent。外层replayed表示这个消息事件是否重复；data.replayed表示底层报告是否已存在，二者不同。not_sent表示没有自动发送WhatsApp消息。

最终数据库断言：RepairCaseReport总数1，submit_repair_case审计总数1。报告未审核，不扣库存、不完工、不认证适配。

## 请 Muse 回传

```text
执行方式：仅文档审核／隔离环境实际执行
使用的代码提交：
签名工具位置及是否支持原始body：
步骤01–18：预期HTTP／实际HTTP／关键字段／通过或差异
最终报告数与提交审计数：
是否只回复模拟原发送者：
仍缺的适配、权限或配置：
可能的额外费用及依据：
```

没有执行就标记未执行；不要伪造实际状态码、用户确认或消息送达。等待确认能力后才讨论真实平台接入，本次不启动任何真实通道或付费服务。
