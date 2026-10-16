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

## 维修反馈闭环

继续使用 `POST /api/muse/work-orders/{work_order_id}/reports`，沿用当前技师身份、设备和工单领取权限及 Idempotency-Key。每次回访创建新报告，独立进入 pending 审核，不覆盖历史报告。

`outcome` 记录本次结果（resolved / partial / unresolved）。可选 `repair_followup` 示例：

```json
{
  "previous_report_id": 123,
  "recurrence": "not_observed",
  "observation_days": 14,
  "actual_parts": [{"part_id": 45, "quantity": 1}],
  "actual_parts_complete": true
}
```

- recurrence 为 unknown（未确认）、not_observed（观察期内未见复发）、recurred（已复发）；not_observed 必须提供正数 observation_days。不代表永久解决。
- previous_report_id 必须属于本组织、同一工单且机型和标准症状仍一致。首次报告可省略。回访需提交完整的症状、检查步骤、结果说明和用料快照，不自动复制旧报告。
- actual_parts 是技师明确报告的实际使用零件及正数数量，仅接受本组织零件，不写库存流水、不认证适配。actual_parts_complete=false 表示清单可能不完整；true 且空数组表示明确未使用零件。旧 part_ids 仍仅表示报告提及。
- 同工单、同症状按最新提交且已审核的报告去重；审核时间不会改变提交顺序。未审核或已拒绝回访不替换当前已审核证据；经理可拒绝错误记录恢复此前证据。
- 已审核复发记录即使 outcome=resolved，也不能作为持续解决证据，返回 non_resolved_cases 及复发提示。修复复发后再次回访、审核，才可能恢复正向案例。
- 来源详情 GET /api/muse/reports/{id} 保留 repair_followup、审核者、审核时间、原始症状、原报告 ID；实际用料候选提供 actual_use_evidence 和来源路径。反馈数量不等于推荐用量。
- 旧报告没有回访数据时返回 null，不推断无复发或实际安装。不计算未经校准的成功率，不进行模型训练。

数据库迁移 20261015_0022 增加可空 JSON repair_followup；旧报告不回填、不改写。前端无需改动即可由 Muse 调用上述后端 API。

## 待回访清单与到期提醒

对已审核报告调用 `PUT /api/muse/reports/{report_id}/followup-schedule`：
```json
{"due_at":"2026-11-01T10:00:00-05:00","reason":"维修后七天复查"}
```
必须有原工单写权限（管理员或持有有效设备与领取版本的技师）；经理仍走审核/领取管理权限。日期必须带时区，服务器存 UTC。due_at=null 表示取消计划，reason 必填，调整前后时间和操作者写审计。旧报告不自动安排回访。

查询 `GET /api/muse/followups?scope=mine&status=open`，或：
```json
{"resource":"followups","scope":"mine","followup_status":"open","skip":0,"limit":25}
```
scope 支持 mine / available / all，始终限制当前组织。status 支持 open / due / upcoming / awaiting_review / completed / all；open 包括未到期、到期和待审核。counts 为所选 scope 下各状态总数，total 为状态筛选后的数量。按计划时间和来源报告 ID 排序，limit 最大 100。

Muse 在会话开始或技师询问待办时查询，将 reminder_required=true 的项目展示为到期提醒。返回 UTC due_at、as_of、工单编号、准确机型、症状、来源路径、提交路径及 previous_report_id。is_overdue 可在待审核时为 true，但 reminder_required=false，避免催促重复提交。提醒为查询时计算，不推送邮件或外部消息，也不要求新增云服务。

沿用 POST /api/muse/work-orders/{work_order_id}/reports，repair_followup.previous_report_id 使用清单值，填写 recurrence、观察天数、实际用料及完整结果。只有直接关联该计划来源的反馈才处理该计划；同工单无关反馈不关闭计划。
- 未提交：到期或未到期；待审核反馈：awaiting_review；审核通过：completed；仅有被拒绝反馈：重新显示到期/未到期。
- completed 只表示这次回访已审核，不代表维修成功；复发仍会作为负面证据影响指导。
- 审核撤销时状态随查询重新计算；需要再次回访时给最新已审核反馈另排计划。
- 原报告审核撤销后计划不进入清单。机型发生变更会返回 model_evidence_current=false，需先核对身份；不会把旧机型案例自动适配到新机型。
- 未审核反馈明细仅本人或经理/管理员获得来源链接；其他有工单读取权限的同组织用户只看到待审核状态。

迁移 20261015_0023 增加可空 followup_due_at 和索引。排期和提醒不改变维修建议、库存或适配状态。
