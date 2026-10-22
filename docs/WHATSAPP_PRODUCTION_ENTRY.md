> 新增：生产适配器强制试点白名单，见 [试点授权与上线预检](WHATSAPP_PILOT_PREFLIGHT.md)。接收/发送继续默认关闭。

# 生产入口与安全密钥加载

本阶段实现 production factory，但没有启用任何真实通道。默认仍为 disabled；可选择
production 模式检查部署，接收与发送开关仍默认 false。原部署配置保持关闭，前端不改。

## 入口与开关

沿用 `scripts.meta_deployment:adapter_app`、`webhook_app` 和 `python -m scripts.meta_deployment worker`。
新增 `META_DEPLOYMENT_MODE=production`，要求 APP_ENV=production、APP_DEBUG=false。
`META_CHANNEL_ENABLED` 控制适配器和 webhook 是否接收；`META_LIVE_SEND_ENABLED` 控制 worker 是否运行。
只开发送而没开通道会拒绝；旧 WHATSAPP_ADAPTER_ENABLED 必须 false。严格只接受 true/false。

默认关闭：webhook/adapter 业务接口503，worker不打开队列、不联网；不因生产秘密尚未准备好而读占位文件。
只打开接收但不开发送时，worker也不消费队列，防止将待发送消息误标为失败。
`check` 命令则显式检查全部生产配置/秘密/路径，不启动 worker、不创建状态库、不联网；
输出只有模式和检查完成状态，不输出配置对象、路径或秘密。不要通过打印 configuration() 调试，返回对象包含秘密。

## 凭证与状态

- 仅从 `META_APP_SECRET_FILE`、`META_VERIFY_TOKEN_FILE`、`META_ACCESS_TOKEN_FILE`、
  `WHATSAPP_SIGNING_SECRET_FILE` 读取；对应明文环境变量被拒绝。
- 文件必须绝对路径、非符号链接、常规文件、单硬链接、归当前用户或 root、权限0400或0600。
  有界读取，32–8192字符，拒绝空白、控制字符和明显占位/公开模拟常量。校验不证明 token 有效或随机性充足。
  异常只说明变量名和规则，不输出文件内容或路径。父目录须由可信运维管理，不能交给不可信用户写入。
- webhook 只读 App Secret、verify token 和签名密钥，不加载发送 token；adapter只读签名密钥；
  worker只读签名密钥和发送 token；check读取全部。webhook从不构造启用的GraphSender。
- Bridge 状态默认 `/state/bridge.sqlite3`，绑定状态默认 `/adapter-state/channel.sqlite3`，必须不同。
  运维事先创建所属服务用户拥有的0700父目录；已有状态文件须0600、非符号链接、单硬链接。
  校验不修复权限、不迁移或覆盖旧库。单机本地磁盘限制不变。
- adapter要求共享PostgreSQL DATABASE_URL；主业务JWT沿用现有配置校验。
  本阶段只新增WhatsApp秘密文件加载，主API的JWT/PostgreSQL环境配置未改。
- 内网调用固定 `http://adapter:8011`，禁代理继承、重定向和自动重试；GraphSender同样禁代理继承。
  WABA/号码ID要求数字，Graph版本要求显式 vN.0；实际版本是否仍受支持须官方沙箱确认。

## 配置模板

`deploy/whatsapp.production.override.yml` 可在现有 production + whatsapp Compose 文件后合并。
它将宿主机现有的私有秘密文件按角色只读挂载，不含实际密钥；仍将两个开关硬设为 false。
本阶段没有在真实主机使用此模板。准备卷权限、只读秘密文件和固定镜像摘要后才可安排部署；
不要直接把测试目录当生产秘密。容器用户与宿主机文件权限需一致，不能为方便改成0444。

秘密在进程启动时读取，不热加载。轮换须停 worker/暂停入站，协调更新 webhook、adapter、worker
共享签名密钥，再启动并核查；不在日志、GitHub或Muse聊天中传递凭证。

## 模拟验收

运行 `tests/test_meta_production.py`，使用临时私有目录和随机模拟凭证，覆盖关闭不读秘密、
权限/链接/占位拒绝、非法账号/版本/地址/环境拒绝、角色读取范围、状态目录和安全检查输出。
生产工厂接入真实适配器及隔离组织数据库，Meta签名消息完成绑定，Graph HTTP由MockTransport拦截；
保留状态重放只产生一次发送尝试，webhook没有启用的发送器。测试版本v99.0仅为格式样例，不可用于生产。

全部原有模拟启停、回滚、发送对账、反馈确认和组织隔离测试继续执行。
这证明生产构造与秘密加载逻辑，不证明生产PostgreSQL账号/真实凭证/Meta公网收发有效。
官方沙箱、真实TLS、试点白名单及实际凭证授权仍待后续；不得把此次测试当作启用许可。
