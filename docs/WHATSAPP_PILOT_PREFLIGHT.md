# 试点白名单与上线预检

生产 adapter factory 强制 `pilot_required=True`。原模拟适配器默认不要求白名单，以兼容旧联调包；
这不能用于绕过生产门禁。现有生产接收/发送开关继续关闭，未启动真实通道。

## 个人试点资格

在私有适配器接口使用本组织管理员个人 Bearer：

- `PUT /api/channels/whatsapp/pilots`，JSON 为 `user_id`、`sender_id`、`reason`、可选 `expires_in`。
  user须为本组织活跃ENGINEER；号码格式沿用绑定接口；reason 10–500字符；有效期60秒至30天，默认7天。
  示例仅使用合成号码：`{"user_id":2,"sender_id":"15550000001","reason":"Approved for isolated pilot","expires_in":604800}`。
- `DELETE /api/channels/whatsapp/pilots/{sender_id}?reason=...`，reason须10–500字符；只能撤销本组织资格。
- 批准后仍需原管理员绑定邀请及由平台签名号码兑换。批准不等于身份已验证。

资格精确绑定组织、用户和号码，不接受客户端指定organization_id。其他组织或用户不能占用已有号码。
授权有效时可续期；到期后重新批准、撤销后重新批准，都必须重新邀请绑定。此次不提供跨组织号码迁移工具。
每次绑定邀请/兑换、查询、领取、反馈草稿及确认都检查资格；在读取事件缓存前检查，防止重放绕过。

撤销事务同时写入 pilot_audit 并撤销旧绑定。旧草稿不能确认；发送前身份复核会取消旧排队回复。
重新绑定产生新渠道设备代次，旧回复即使在重新绑定后才处理也不会恢复。
已进入外部发送请求的消息无法撤回，检查与网络发送之间不承诺原子撤销或外部 exactly-once。
资格到期也阻断请求，监控/人工恢复/去重和发送审计继续保留。

pilot_members/pilot_audit 位于私有 adapter 状态库，无公开名单接口。只读查询工单时仍采用原有组织权限；
白名单是附加限制，不替代登录、平台验签或组织隔离。撤销原因会出现在管理请求URL中，请勿填写秘密；
默认代理不开放这些路由且适配器访问日志关闭。

## 离线上线预检

`python -m scripts.meta_preflight` 只输出脱敏JSON，失败退出码1；全通过退出0，但
`production_activation_authorized` 永远为false。必须使用production配置、关闭所有开关。

检查内容：

- 原生产 configuration(check)：文件秘密、账户字段、固定内网地址和私有状态目录；不创建队列。
- `META_IMAGE_REF` 必须形如 `registry.example/backend@sha256:<64位小写hex>`；仅检查固定摘要格式，不访问仓库。
- adapter状态库以SQLite只读模式打开，必须存在至少一条未到期试点资格；不查询生产用户目录。
- `META_BACKUP_MANIFEST` 指向绝对路径JSON清单，created_at为24小时内Unix时间，files恰好包含business、adapter、bridge、uploads四种文件。
  每项为kind/path/sha256；文件须不同、绝对非符号链接、常规非空文件、无组/其他用户权限；逐个验证SHA256。
  清单只描述已完成的备份，不会执行备份、不删除或恢复文件。清单时间为运维声明，不独立证明实际备份时间。

示例结构（不可直接用于生产）：

```json
{"created_at":0,"files":[
 {"kind":"business","path":"/secure/business.dump","sha256":"填写校验值"},
 {"kind":"adapter","path":"/secure/adapter.sqlite3","sha256":"填写校验值"},
 {"kind":"bridge","path":"/secure/bridge.sqlite3","sha256":"填写校验值"},
 {"kind":"uploads","path":"/secure/uploads.tar","sha256":"填写校验值"}
]}
```

报告不输出号码、密钥、文件路径、异常正文或查询结果；保留not_verified列表：账号授权、真实库身份、
镜像仓库摘要、备份恢复一致性、公网TLS、官方沙箱及试点用户目录。哈希相符不证明备份可恢复或多库一致，
仍须执行原协调备份及恢复演练。脚本不初始化缺失名单表；全新关闭部署会报告未就绪。
正式登记需运维在受控内网安排，不能为了让预检通过而开放公网接口。

## 本轮验证

隔离临时状态库、合成号码和随机模拟秘密：未批准/到期拒绝、管理员及跨组织限制、撤销后缓存重放、
反馈确认拒绝、旧队列取消、重新绑定不恢复旧回复，以及预检只读/脱敏/错误备份和镜像拒绝。
不加载真实凭证，不发送真实消息，不修改前端，不开通付费服务。
