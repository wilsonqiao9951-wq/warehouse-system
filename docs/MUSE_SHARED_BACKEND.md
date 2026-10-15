# 多技师、多Muse的共享后端

每个Muse独立接入同一个HTTPS API，不依赖共同聊天或GitHub权限。GitHub负责代码、接口说明和Issue/PR协作；运行服务、账户、工单及库存数据库独立于GitHub，不能把数据库或生产密码提交到仓库。

项目说明为MUSE_PROJECT_BRIEF.md。部署后分发服务器地址及此说明，技师在受控登录工具中使用自己的账户。GET /api/muse提供机器可读入口，GET /api/muse/guide提供项目说明，POST /api/muse/query统一只读查询。完整操作合同为/openapi.json。现有API不要求Muse使用同一前端代码，但Muse自身须具备HTTP工具或连接器。只有一段文字而没有HTTP能力时无法完成接入。

工单查询沿用当前角色/组织范围；报告写入沿用同一账户、注册设备、领取归属与claim_version规则。跨组织数据库读写隔离，不因Muse端传入组织号而改变。一个技师的令牌不能放进公共项目说明。

反馈闭环：技师提交结构化症状、操作、候选零件与结果→经理审核→同组织/同明确机型/同症状代码检索解决案例→反馈新结果。失败、未解决及未审核记录不是成功证据，同一工单重复提交不增加支持数量。当前实现为可追溯案例检索，不是LLM训练、自动参数优化或成功率保证。保留来源和审核人，资料不足则返回needs_more_evidence。

API接口：

- GET /api/muse
- GET /api/muse/guide
- POST /api/muse/query
- GET /api/muse/work-orders/{id}/guidance?symptom_code=...
- POST /api/muse/work-orders/{id}/reports
- GET /api/muse/reports（经理/管理员）
- POST /api/muse/reports/{id}/review（经理/管理员）

工单指导把当前客户/设备事实、严格同机型的历史用料、审核后的解决案例及失败案例分开；候选零件显示本组织库存，不能自动下结论或扣库存。症状代码需要团队采用一致定义；当前不做自然语言语义推断，也不生成无出处的维修步骤。

远程共享还需稳定HTTPS域名、持久化数据库和上传存储、备份、生产JWT密钥、每技师账户及运行监控。当前本机地址不能供远程Muse直接访问。部署平台及GitHub目标仓库需由项目所有者确定；未部署前不可宣称多人远程服务已上线。
