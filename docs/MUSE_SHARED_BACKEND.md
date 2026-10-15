# 多技师、多Muse的共享后端

每个Muse独立接入同一个HTTPS API，不依赖共同聊天或GitHub权限。GitHub负责代码、接口说明和Issue/PR协作；运行服务、账户、工单及库存数据库独立于GitHub，不能把数据库或生产密码提交到仓库。

项目说明为MUSE_PROJECT_BRIEF.md。部署后分发服务器地址及此说明，技师在受控登录工具中使用自己的账户。GET /api/muse提供机器可读入口，GET /api/muse/guide提供项目说明，POST /api/muse/query统一只读查询。完整操作合同为/openapi.json。现有API不要求Muse使用同一前端代码，但Muse自身须具备HTTP工具或连接器。只有一段文字而没有HTTP能力时无法完成接入。

工单查询沿用当前角色/组织范围；报告写入沿用同一账户、注册设备、领取归属与claim_version规则。跨组织数据库读写隔离，不因Muse端传入组织号而改变。一个技师的令牌不能放进公共项目说明。

反馈闭环：技师提交结构化症状、操作、候选零件与结果→经理审核→同组织/同明确机型/同症状代码检索解决案例→反馈新结果。失败、未解决及未审核记录不是成功证据，同一工单重复提交不增加支持数量。当前实现为可追溯案例检索，不是LLM训练、自动参数优化或成功率保证。保留来源和审核人，资料不足则返回needs_more_evidence。

API接口：

- GET /api/muse
- GET /api/muse/guide
- GET /api/muse/symptoms（公开项目观察词表，不含组织数据）
- POST /api/muse/symptoms/resolve（登录后分类，非诊断）
- GET /api/muse/work-orders/{id}/symptoms（本组织工单症状原文与分类）
- POST /api/muse/query
- GET /api/muse/work-orders/{id}/guidance?symptom_code=...
- POST /api/muse/work-orders/{id}/reports
- GET /api/muse/reports（经理/管理员）
- GET /api/muse/reports/{id}（同组织的已审核来源；未审核仅提交人/经理/管理员）
- POST /api/muse/reports/{id}/review（经理/管理员）

工单指导把当前客户/设备事实、严格同机型的历史用料、审核后的解决案例及失败案例分开；候选零件显示本组织库存，不能自动下结论或扣库存。症状使用版本1.0的项目观察词表：13类稳定代码，中英文完整同义短语归一；不解释厂家故障码、不推断故障原因。复杂自由文本只给待确认候选，不把关键词命中直接用于案例检索。

没有显式症状参数时，Muse指导读取当前工单problem_description；有显式参数则优先使用，未知参数不会悄悄退回更宽的查询。反馈新增可选symptom_text，迁移0021以nullable symptom_context保存原始输入、分类依据、词表版本及来源；旧报告不改写，读取时仅归一已知旧代码。未知输入保留并提示确认，不作为跨案例匹配代码，guidance_eligible须有可识别症状。分类不会自动创建维修步骤、零件适配、用料或审核记录。

指导返回历史检查步骤的逐条案例引用、已审核来源明细、独立工单支持数、未解决案例提及及证据缺口。仅一个案例会标记limited；至少两个独立解决工单才标记multiple_reviewed_cases，这不是置信度、成功率或适配评分。来源工单机型被纠正后会重新核对，不再沿用过期机型快照。库存只影响同等案例证据的排序，不会凭有货生成推荐；停用仓库/库位不计入可用量，负库存提示账实核对。查询没有领用、预留、采购或完工副作用。

旧工单part-recommendations接口已取消按相同工单类型跨机型匹配和未经审核的用料推断，与Muse指导统一证据来源。缺symptom_code返回空列表；有依据的候选仍不推断本次用量，recommended_quantity为null，需要技师另行确认。前端源代码保持不改；旧网页未传症状时不会显示旧式推荐。

维修反馈支持Idempotency-Key：同组织同次请求的网络重试返回原报告，数据库唯一约束防止并发重试创建重复记录；键不能换内容、换工单或换提交人。无键旧客户端保持兼容。幂等重试不会跳过当前工单权限检查，也不会重复写入提交审计。

远程共享还需稳定HTTPS域名、持久化数据库和上传存储、备份、生产JWT密钥、每技师账户及运行监控。GitHub仓库已选warehouse-system，DigitalOcean为待开通方案；目前暂停开通，由所有者研究。当前本机地址不能供远程Muse直接访问，未部署前不可宣称多人远程服务已上线。
