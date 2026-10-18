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

## 逾期跟进与回访统计（契约 1.3）

新增 GET /api/muse/followups/stats（或 query resource=followup_stats），支持 scope=mine/available/all。返回计划数、去重工单数、各回访状态、按时/迟交/未交逾期/未到期数量，以及已审核复发工单数。所有统计在分页之前计算，始终仅限当前组织与所选范围。

GET /api/muse/followups 新增 status=overdue（到期尚无有效提交）、late（迟交，包含待审核与已完成）、recurred（该计划最新已审核直接回访为复发）。
- submission_timing 使用最早一份当前仍为 pending 或 approved 的直接关联回访提交时间，和当前计划时间比较；rejected 不满足回访要求。
- submission_delay_seconds 表示迟交时长或未提交时当前逾期时长；overdue_days 为未提交逾期的完整天数；followup_needed 标记需要催办。
- is_overdue 现在只表示未有效提交的逾期。review_overdue 单独表示计划时间已过、等待审核；审核等待不算技师提交延迟。
- 原本按时提交但审核较晚仍为 on_time；迟交审核后仍可通过 late 查询。
- 改期会按新时间重新计算，旧时间保存在排期审计中。此处是当前计划状态统计，不是历史履约率。

新增 GET /api/muse/followups/recurrences（或 query resource=repair_recurrences），查询本组织当前已审核复发记录，包含未排期的回访。按工单和完全相同的标准症状代码集合取最新已审核报告；待审核的新反馈不会覆盖旧已审核结果。返回来源报告路径、原报告 ID、机型当前性及观察天数。后续审核确认未见复发后，旧复发仍可从历史来源读取，但不再列为该症状当前复发。

统计中的 recurrence 数量与计划数量使用不同总体，不能相除推导复发率或成功率。多个症状/计划可属于同一工单，分别提供记录数和工单去重数。来源路径可逐条核验；不自动认定适配、不修改库存或工单状态。无需新增数据库迁移，仍为 0023。

## 按机型和症状汇总维修证据（契约 1.4）

GET /api/muse/repair-statistics，或 query resource=repair_statistics，可用 machine_model（准确官方机型名称）、symptom_code（支持明确别名）、skip、limit 筛选。统计仅限当前组织的已审核报告；当前工单机型必须与报告快照一致，未知机型/无标准症状报告计入 excluded_report_counts，不混合到确定机型。

每个机型/标准症状组，按工单取最新提交且已审核的匹配报告。返回：
- 独立工单数、resolved/partial/unresolved 原始结果数；
- recurred/not_observed/unknown 复发观察数；resolved 与 recurred 可以同时出现，不能把原始解决数当作持续成功；
- actual_parts 明确报告的实际用料、数量、独立工单支持数及 source_case_ids，报告提及但未明确实际使用的零件不进入实际用料汇总；
- repeat_failure_signal：至少一例已审核复发，或至少两个部分解决/未解决工单，仅用于提示排查；
- needs_more_evidence 与原因：单一案例、复发观察不完整、实际用料不完整、负面结果；
- 来源案例（最多20条）及 sources_path，后者分页读取全部来源；每条仍可通过报告详情追溯原始反馈；
- guidance_query 模板，Muse 必须填入待修目标 work_order_id，调用现有 repair_guidance。后端再次核对同机型与组织，并排除目标工单自身，统计本身不是维修处方。

GET /api/muse/repair-statistics/cases?machine_model=...&symptom_code=... 提供来源分页，limit 最大100。非法/未知症状不会退回全量结果，无匹配证据时明确提示。

实际数量是每个工单最新报告的用料快照之和，不是累积消耗、库存流水或推荐用量。多个症状会使同一工单及用料出现在多个组，不能跨组相加当独立工单总数。观察期不同，不计算成功率或复发率；not_observed 只表示报告观察期内未见复发。所有记录保留来源，不自动认定适配、改库存或改变审核结果。数据库仍为0023，无新增迁移。


## Quest 2000／4000 查询

47条官网已确认新零件使用 official-quest-{part_number} 稳定ID接入主目录，原有23条ID不变。GET /api/catalog/quest/models、/quest/models/{model_id}、/quest/models/{model_id}/parts 提供列表、章节和分页零件查询；model_id仅2000和4000。零件接口支持section_id、q、skip、limit。2000为51条/16章节，4000为63条/15章节，70条独立零件，44条共享官网引用不能相加或推断通用。

Muse query资源新增quest_models、quest_model、quest_parts，后两者必须传model_id。返回当前机型/章节官网来源、图片及主要字段、organization_part及本组织库存位置；未知机型或其他机型章节404。不自动写入组织库存、现场验证或适配关系。主目录现有POST /api/catalog/parts/{catalog_id}/import仍需授权，重复导入幂等且不会增加库存。本轮未新增Quest工单用料、现场验证或维修指导机型支持。

运行数据通过catalog-bundle/quest补充包同步，安装器校验哈希且拒绝覆盖不同内容。原审核来源及访问时间保留；无法确认的Viper/Freestyle项继续保留，前端未改。


## ABS 1.0／2.0 目录查询

已接入170条已确认新零件，使用official-abs-{part_number}稳定ID，保留324条既有记录ID。ABS 1.0为309条/20章节，ABS 2.0为216条/31章节，去重494条，其中31条有两代官网引用。缺图15条、厂家缺失6条保持空缺，不阻塞已确认身份的目录接入。

GET /api/catalog/abs/models、/abs/models/{model_id}、/abs/models/{model_id}/parts；model_id严格为1.0或2.0。零件查询支持section_id、q、skip、limit（最大100）。Muse query新增abs_models、abs_model、abs_parts资源，后两者必须传model_id。每条只返回当前机型/章节的官网关系与本组织库存位置；跨代章节或未知机型404。

官网共享引用不是跨代适配认证；不自动创建库存、工单用料或现场验证。本轮只接入目录与分机型查询，ABS维修指导、工单用料和现场验证机型支持尚未扩展。公开运行数据由catalog-bundle/abs独立增量包恢复并校验，主库schema仍0023，前端未改。


## ED 150／ED 200/250／ED 300 目录查询

本轮重新核验29个官网手册页面和303个零件页面，新增122条主目录记录，保留181条既有记录ID。ED 150为158条/9章节，ED 200/250为200条/10章节，ED 300为91条/5章节；去重303条，115条具有多个机型的官网引用。200/250沿用官网合并机型标签，不能由此认证200与250通用。缺图16条、缺厂家5条、缺厂家料号1条原样保留，不补猜测值。

GET /api/catalog/ed/models、/ed/models/{model_id}、/ed/models/{model_id}/parts；model_id为150、200-250或300。零件查询支持section_id、q、skip、limit（最大100）。Muse query资源为ed_models、ed_model、ed_parts，后两者必须传model_id。例如：
```json
{"resource":"ed_parts","model_id":"200-250","limit":25}
```
响应只含所选机型/章节的官网关联和当前组织库存；未知机型或跨机型章节404，所有请求需认证。新增ID为official-ed-{part_number}。沿用授权的主目录导入接口，重复导入不会增加库存。官网引用不代表现场验证或跨机型适配；本次未扩展ED维修指导或工单用料机型支持。

公开运行数据由catalog-bundle/ed恢复并校验；官网链接、访问时间和快照哈希保留。原始页面快照在本机data/verification/ed_20261016中。审核清单中的“待接入主目录”表示接入前快照，实际接入以ed_added_manifest.json和ed_graph.json为准。数据库schema保持0023。


## MD150／MD200／MD250 目录查询

重新核验30个官网手册页面和72个零件页面，新增45条主目录记录、复用27条既有记录ID。MD150为52条、MD200为57条、MD250为50条，各9章节；去重72条，50条具有多个机型官网引用。缺图1条、缺厂家1条保持空缺，官网关系不代表跨机型适配。

GET /api/catalog/md/models、/md/models/{model_id}、/md/models/{model_id}/parts；model_id严格使用150、200、250。零件查询支持section_id、q、skip、limit（最大100）。Muse query支持md_models、md_model、md_parts，后两者必须传model_id。例如：
```json
{"resource":"md_parts","model_id":"200","limit":25}
```
所有接口需认证；每条仅返回所选机型/章节的官网关联和当前组织库存。未知机型或跨机型章节404。新增ID为official-md-{part_number}，既有授权导入接口保持幂等，不增加库存。不自动创建现场验证或认定适配；本次未扩展MD维修指导或工单用料机型支持。

运行数据通过catalog-bundle/md恢复并校验；链接、访问时间、快照哈希保留。原始快照位于本机data/verification/md_20261016；审核中待接入主目录列表为接入前快照，实际以md_added_manifest.json、md_graph.json为准。schema保持0023，前端未改。


## DF 150／DF 200/250 目录查询

重新核验18个官网手册页面和215个零件页面，新增21条主目录记录、复用194条既有记录ID。DF 150为118条/7章节，DF 200/250为164条/8章节；去重215条，67条具有两个官网机型标签的引用。200/250沿用官网合并标签，不自动认定二者通用。缺图16条、缺厂家5条、缺厂家料号1条保持空缺。

GET /api/catalog/df/models、/df/models/{model_id}、/df/models/{model_id}/parts；model_id严格使用150、200-250。零件查询支持section_id、q、skip、limit（最大100）。Muse query支持df_models、df_model、df_parts，后两者必须传model_id。例如：
```json
{"resource":"df_parts","model_id":"200-250","limit":25}
```
所有接口需认证；每条仅返回所选机型/章节官网关联和当前组织库存，未知机型或跨机型章节404。新增ID为official-df-{part_number}；既有授权导入保持幂等，不增加库存。不自动认定适配或创建现场验证；本次未扩展DF维修指导或工单用料机型支持。

运行数据由catalog-bundle/df恢复并校验，保留官网链接、访问时间和快照哈希。本机原始快照在data/verification/df_20261016；审核清单的待接入列表为接入前快照，实际以df_added_manifest.json及df_graph.json为准。schema仍0023，前端未改。


## DB 150／DB 200 / 275 Standard 目录查询

重新核验9个官网手册页面和61个零件页面，新增17条主目录记录，复用44条既有记录ID。DB 150为46条/3章节，DB 200 / 275 Standard为48条/4章节；去重61条，33条有两个官网机型标签引用。200 / 275 Standard沿用官网合并标签，不推断200与275通用。缺厂家1条保持空缺；本轮无缺图及身份未确认链接。

GET /api/catalog/db/models、/db/models/{model_id}、/db/models/{model_id}/parts；model_id严格为150或200-275。零件查询支持section_id、q、skip、limit（最大100）。Muse query支持db_models、db_model、db_parts，后两者必填model_id。例如：
```json
{"resource":"db_parts","model_id":"200-275","limit":25}
```
所有接口需认证；仅返回所选机型/章节官网关联和当前组织库存。未知机型或跨机型章节404。新增ID为official-db-{part_number}；既有授权导入保持幂等且不增加库存。不自动认定适配或创建现场验证；本次未扩展DB维修指导或工单用料机型支持。

运行数据由catalog-bundle/db恢复并校验，保留官网链接、访问时间和快照哈希。本机原始快照为data/verification/db_20261016；审核清单待接入列表是接入前快照，实际以db_added_manifest.json及db_graph.json为准。schema仍0023，前端未改。


## 7000／7100 Ice Combo目录查询（2026-10-17）

重新核验24个官网手册页面和361个零件页面。361条独立零件全部复用主目录既有ID，新增零件0条；本轮新增精确机型和章节查询。7000 Ice Combo为254条/9章节，7100 Ice Combo为196条/13章节，89条有两个机型官网引用，不代表跨机型适配。缺图3条、缺厂家27条保持空缺，身份未确认链接0条。

GET /api/catalog/icecombo/models、/icecombo/models/{model_id}、/icecombo/models/{model_id}/parts；model_id严格为7000或7100。支持section_id、q、skip、limit（最大100）。Muse query资源为icecombo_models、icecombo_model、icecombo_parts，后两者必填model_id。例如：
```json
{"resource":"icecombo_parts","model_id":"7100","limit":25}
```
请求需认证；仅返回当前机型/章节官网关联与本组织库存，未知机型及跨机型章节404。既有授权导入接口保持幂等且不增加库存。不自动创建现场验证或认定适配；本次未扩展Ice Combo维修指导或工单用料机型支持。

运行数据由catalog-bundle/icecombo恢复并校验，包含空的新增清单及完整关联图；官网链接、访问时间、快照哈希保留。本机原始快照位于data/verification/icecombo_20261017，schema仍0023，前端未改。


## 8000／8100 Crew-Serve目录查询（2026-10-17）

重新核验29个官网手册页和393个零件链接。确认390条独立零件，全部复用既有主目录ID，新增零件0条。本轮建立8000 Crew-Serve的229条/13章节与8100 Crew-Serve的175条/14章节查询；14条共享官网引用不代表适配。缺图3条、缺厂家18条保持空缺。3个官网链接404（35085-001-524 | PLEXUS CORP、3508088、3507458对应引用），保留待核验及原章节证据，不据此建立已确认关系。

GET /api/catalog/crewserve/models、/crewserve/models/{model_id}、/crewserve/models/{model_id}/parts；model_id为8000或8100。支持section_id、q、skip、limit（最大100）。Muse query资源为crewserve_models、crewserve_model、crewserve_parts，后两者必填model_id：
```json
{"resource":"crewserve_parts","model_id":"8100","limit":25}
```
请求需认证，只返回所选机型/章节来源和本组织库存；未知机型及跨机型章节404。授权目录导入仍幂等且不增加库存。不自动认定跨机型适配、创建现场验证或扩展Crew-Serve维修指导/实际用料机型支持。

catalog-bundle/crewserve提供校验后的运行数据，保留官网链接、访问时间、快照哈希。完整本机审核（含待核验）在data/verification/crewserve_20261017。schema0023，前端不变。


## 9000／9100 Self-Serve目录查询（2026-10-17）

重新核验32个官网手册页面和547个零件页面，确认547条独立零件，全部复用主目录既有ID，新增零件0条。9000 Self-Serve为356条/16章节，9100 Self-Serve为241条/14章节；50条共享官网引用不代表跨机型适配。缺图4条、缺厂家51条保持空缺，本轮身份未确认链接0条。

GET /api/catalog/selfserve/models、/selfserve/models/{model_id}、/selfserve/models/{model_id}/parts；model_id严格为9000或9100。支持section_id、q、skip、limit（最大100）。Muse query资源为selfserve_models、selfserve_model、selfserve_parts，后两者必填model_id：
```json
{"resource":"selfserve_parts","model_id":"9100","limit":25}
```
所有接口需认证，返回所选机型/章节官网来源及当前组织库存；未知机型或跨机型章节404。既有授权导入保持幂等，不增加库存。不自动认定适配、创建现场验证或扩展Self-Serve维修指导/实际用料机型支持。

catalog-bundle/selfserve提供校验后的运行数据，保留官网链接、访问时间及快照哈希。本机完整审核在data/verification/selfserve_20261017，schema0023，前端不变。


## TJ 45 / TJ 90、TJ 150目录查询（2026-10-18）

重新核验7个官网手册页面和34个零件页面。34条独立零件中新增3条（official-tj-{part_number}），复用31条既有ID。TJ 45 / TJ 90为33条/2章节，TJ 150为29条/3章节；28条共享官网引用不代表通用。45/90沿用官网合并标签，不认定二者相互适配。本轮身份未确认链接0条，审核字段无缺失，图片可用。

GET /api/catalog/tj/models、/tj/models/{model_id}、/tj/models/{model_id}/parts，model_id严格为45-90、150。支持section_id、q、skip、limit（最大100）。Muse query资源tj_models、tj_model、tj_parts，后两者必填model_id：
```json
{"resource":"tj_parts","model_id":"45-90","limit":25}
```
请求需认证，仅返回所选机型/章节官网关系与本组织库存；未知机型或跨机型章节404。授权目录导入幂等且不增加库存。不自动认定适配、创建现场验证或扩展TJ维修指导/实际用料机型支持。

catalog-bundle/tj校验恢复运行数据，保留官网链接、访问时间、快照哈希。本机完整审核在data/verification/tj_20261018；审核待接入列表是接入前快照，最终接入以tj_added_manifest.json及tj_graph.json为准。schema0023，前端不变。


## WBK8／WBK9／WBK10目录查询（2026-10-18）

重新核验8个官网手册页和39个零件页。39条独立零件中新增19条（official-wbk-{part_number}），复用20条既有ID。WBK8为13条/1章节，WBK9为11条/1章节，WBK10为33条/3章节；11条有多机型官网引用，不自动认定通用。6条缺图保持空缺，其余审核字段齐全，本轮身份未确认链接0条。

GET /api/catalog/wbk/models、/wbk/models/{model_id}、/wbk/models/{model_id}/parts；model_id严格为8、9、10。支持section_id、q、skip、limit（最大100）。Muse query资源wbk_models、wbk_model、wbk_parts，后两者必填model_id：
```json
{"resource":"wbk_parts","model_id":"10","limit":25}
```
请求需认证，仅返回当前机型/章节官网关系与本组织库存；未知机型及跨机型章节404。授权目录导入幂等且不增加库存。不自动认定适配、创建现场验证或扩展WBK维修指导/实际用料机型支持。

catalog-bundle/wbk校验恢复运行数据，保留官网链接、访问时间、快照哈希。本机完整审核在data/verification/wbk_20261018，审核待接入列表为接入前快照，实际以wbk_added_manifest.json和wbk_graph.json为准。schema0023，前端不变。


## 37T／37F／37K目录查询（2026-10-18）

重新核验23个官网手册页和119个零件页。119条独立零件中新增25条（official-series37-{part_number}），复用94条既有ID。37T为83条/6章节，37F为64条/7章节，37K为80条/5章节；72条有多机型官网引用，不代表通用。缺图1条、缺厂家6条保持空缺，身份未确认链接0条。

GET /api/catalog/series37/models、/series37/models/{model_id}、/series37/models/{model_id}/parts；model_id严格为37t、37f、37k。支持section_id、q、skip、limit（最大100）。Muse query资源series37_models、series37_model、series37_parts，后两者必填model_id：
```json
{"resource":"series37_parts","model_id":"37t","limit":25}
```
接口需认证，只返回所选机型/章节官网来源及本组织库存。未知机型与跨机型章节404。授权导入幂等、不增加库存。不自动认定适配或创建现场验证；本轮不扩展维修指导与实际用料机型支持，不包含MCD 37等其他机型。

catalog-bundle/series37提供校验恢复数据，保留官网链接、访问时间、快照哈希。本机完整审核在data/verification/series37_20261018；审核待接入清单是接入前快照，实际以series37_added_manifest.json与series37_graph.json为准。schema0023，前端不变。


## Multiplex全系列入口：myCoke可确认范围（2026-10-18）

按官网设备页manufacturer_name_display=MULTIPLEX筛选，并在接入时重新检查23个设备页的品牌、身份及快照哈希。共核验107个手册页面、376个零件页面，130条新增、246条复用既有主目录ID。包括本轮37T/F/K已接入的记录，不重复计为新增。21条缺图、14条缺厂家信息保持空缺，零件身份未确认链接0条。跨系列共享227条，仅表示有多个明确官网引用。

| 官网机型/机型组 | model_id | 零件数 | 章节数 |
|---|---|---:|---:|
| 138 EDA2 | 138-eda2 | 17 | 1 |
| 146F | 146f | 8 | 1 |
| 148 EDP | 148-edp | 9 | 1 |
| 37F | 37f | 64 | 7 |
| 37K | 37k | 80 | 5 |
| 37T | 37t | 83 | 6 |
| 44G Series | 44g-series | 90 | 8 |
| 44K04 / 44KX04 | 44k04-44kx04 | 53 | 3 |
| 44K22 / 44KX22 | 44k22-44kx22 | 48 | 2 |
| 44MR04 / 44MX04 | 44mr04-44mx04 | 77 | 5 |
| 50 Series Control Panel | 50-series-control-panel | 18 | 1 |
| 50ERC / 44ERC | 50erc-44erc | 89 | 6 |
| 50G Series | 50g-series | 103 | 8 |
| 50MA04 / 50MAX04 / 50MR04 | 50ma04-50max04-50mr04 | 60 | 3 |
| 72 | 72 | 51 | 5 |
| APH3 / APKV3 | aph3-apkv3 | 15 | 1 |
| MCD 37 | mcd-37 | 70 | 6 |
| Old Style | old-style | 11 | 1 |
| S-250M | s-250m | 36 | 5 |
| SC180 | sc180 | 10 | 2 |
| WBK10 | wbk10 | 33 | 3 |
| WBK8 | wbk8 | 13 | 1 |
| WBK9 | wbk9 | 11 | 1 |

GET /api/catalog/multiplex/models、/multiplex/models/{model_id}、/multiplex/models/{model_id}/parts。零件查询支持section_id、q、skip、limit（最大100）。Muse query资源multiplex_models、multiplex_model、multiplex_parts；后两者必填表中model_id。设备详情包含manufacturer、category和manufacturer_evidence。
```json
{"resource":"multiplex_parts","model_id":"44g-series","limit":25}
```
GET /api/catalog/multiplex/coverage或Muse resource=multiplex_coverage查询收录边界、已接入23组及品牌官网待审核资料。myCoke完整收录范围与全球品牌全产品范围分别标识，worldwide_all_series_complete=false。品牌官网Fresh Blender、BIC等资料仅发现文件入口，零件表与机型关系尚待审核，不能把它们计为已接入。保留所有发现的来源及抓取异常，不从文件标题推断适配。

请求需认证，只返回当前精确机型/章节的关联和本组织库存；未知机型、跨机型章节404。合并标签不拆成已认证互相通用的独立机型，Old Style仍为官网原始标识。授权导入幂等、不增加库存。不会把其他品牌机型（如Viper、TJ、ED）混入；零件可来自供应商，品牌筛选依据设备页而非每个零件的生产厂家。本轮不扩展维修指导或实际用料机型支持。

公开catalog-bundle/multiplex提供数据与覆盖清单，保留访问时间、官网链接与快照哈希。原始myCoke审核在data/verification/multiplex_20261018，品牌官网页面在multiplex_brand_20261018。审核待接入列表是接入前快照，最终以multiplex_added_manifest.json及multiplex_graph.json为准。schema0023，前端不变。


## Lancer：CokeParts／myCoke 范围（2026-10-18）

以官方设备页 manufacturer_name_display=LANCER CORPORATION 为准，本轮重新核验 20 个目录分组、95 个手册页、632 个零件链接。确认 628 个独立零件：393 条新增、235 条复用已有主目录 ID。4 个未确认零件链接保留待核验；49 条缺图片、12 条缺厂家、9 条缺厂家料号、2 条缺 CONA 编号。名称和描述无缺失。只覆盖当前 CokeParts／myCoke 索引中的 Lancer，未扩展厂家官网全产品目录。

| 官网机型/分组 | model_id | 零件数 | 章节数 |
|---|---|---:|---:|
| 1 and 2 Valve Tower (Model 300) | 1-and-2-valve-tower-model-300 | 22 | 3 |
| 1500 Prechiller (SONIC) | 1500-prechiller-sonic | 40 | 2 |
| 1500 | 1500 | 76 | 4 |
| 1523 Drop-In Series (1523 / 2206) | 1523-drop-in-series-1523-2206 | 30 | 2 |
| 22 INCH ACIB (Bevariety) | 22-inch-acib-bevariety | 129 | 8 |
| 2300 Drop-In (Bevariety) | 2300-drop-in-bevariety | 76 | 4 |
| 2300 Drop-In SERIES (2306-2308-2310) | 2300-drop-in-series-2306-2308-2310 | 62 | 2 |
| 2300 Drop-In Sabre Plug-In | 2300-drop-in-sabre-plug-in | 32 | 1 |
| 2300 HP Drop In | 2300-hp-drop-in | 7 | 2 |
| 2300 Ice Cooled Drop In (Bevariety) | 2300-ice-cooled-drop-in-bevariety | 13 | 4 |
| 2300 SP Drop In | 2300-sp-drop-in | 3 | 2 |
| 23308 Drop-In | 23308-drop-in | 25 | 1 |
| 23308 - Sonic UDM (Bevariety) | 23308-sonic-udm-bevariety | 106 | 11 |
| 2400 Free Standing, Plug-in | 2400-free-standing-plug-in | 34 | 1 |
| 2500 | 2500 | 71 | 4 |
| 30 INCH ACIB (Bevariety) | 30-inch-acib-bevariety | 138 | 8 |
| Lancer 4500 - 44 | lancer-4500-44 | 84 | 4 |
| Lancer 4500 IBD22, IBD30 | lancer-4500-ibd22-ibd30 | 186 | 7 |
| Lancer 4500 IBD44 | lancer-4500-ibd44 | 84 | 4 |
| Remote Pump Assembly (Bevariety) | remote-pump-assembly-bevariety | 22 | 1 |

GET /api/catalog/lancer/models、/lancer/models/{model_id}、/lancer/models/{model_id}/parts。Muse POST /api/muse/query 资源为 lancer_models、lancer_model、lancer_parts，后两项必须提供 model_id。零件支持 section_id、q、skip、limit（最大 100）。

```json
{"resource":"lancer_parts","model_id":"lancer-4500-ibd22-ibd30","limit":25}
```

认证后仅查询当前精确机型/章节的官网引用和本组织库存；未知机型与跨机型章节返回 404。官网合并机型标签不拆分为互相适配的声明；303 条零件在多个分组中被引用，仅表示官网多处关联。授权导入幂等且不增加库存。来源 URL、访问时间和页面哈希保留，字段空缺和身份未确认项不推测。本轮不扩展维修指导或实际用料机型支持。

运行数据通过 catalog-bundle/lancer 校验恢复，原始审核保留于本机 data/verification/lancer_20261018。待接入清单为审核时快照，最终以 lancer_added_manifest.json、lancer_graph.json 为准。数据库 schema 0023，前端不变。

## Cornelius：CokeParts／myCoke 范围（2026-10-18）

交叉检查设备页与手册章节，以 manufacturer_name_display=MARMON / CORNELIUS 为品牌证据，核验243个手册URL、1453个零件链接。覆盖38个官方目录分组、247个章节、1449个独立零件：264条新增、1185条复用。32组有设备页品牌证据，6组依赖手册章节品牌证据（manufacturer_evidence_scope=manual_section）。仅覆盖当前CokeParts/myCoke索引，不扩展厂家官网产品。

4个异常链接保留待审：3个官网原始链接含厂家文字并返回404，1条缺少Parts Catalog分类。62条缺图、19条缺厂家、1条缺厂家料号保持空缺；名称和描述无缺失。549个零件被多个分组引用，不代表跨机型适配。

GET /api/catalog/cornelius/models、/cornelius/models/{model_id}、/cornelius/models/{model_id}/parts。Muse POST /api/muse/query资源为cornelius_models、cornelius_model、cornelius_parts，后两项必填model_id。零件支持section_id、q、skip、limit（最多100）。

示例：{"resource":"cornelius_parts","model_id":"idc255-pro-fast-gate","limit":25}

需认证，仅返回所选分组/章节和本组织库存；未知机型与跨机型章节404，导入幂等且不增加库存。CI2000 Plus与CI2000 (Plus)保留不同官网ID，不凭相似名称合并。Viper 2/3/4分开查询，原有Viper 3专用链路保持不变。本轮不扩展维修指导或实际用料的机型支持。

公开catalog-bundle/cornelius含5份可校验运行数据，保留来源URL、时间与哈希；原始审核在本机data/verification/cornelius_20261018。审核脚本默认重新抓取，--resume仅复用一小时内哈希一致的页面及同地址图片检查。待接入清单为审核时快照，实际以cornelius_added_manifest.json及cornelius_graph.json为准。schema0023，无迁移，前端不变。

| 官方分组 | model_id | 零件 | 章节 |
|---|---|---:|---:|
| 2 Flavor (3H.P.) - V4 | 2-flavor-3h-p-v4 | 86 | 16 |
| 3 Valve Tower (Ceramic) | 3-valve-tower-ceramic | 6 | 2 |
| Appex 6 | appex-6 | 21 | 6 |
| Automated Beverage System (ABS 1.0) | automated-beverage-system-abs-1-0 | 309 | 20 |
| Automated Beverage System (ABS 2.0) | automated-beverage-system-abs-2-0 | 216 | 31 |
| CB2323 / CB1522 / CB3023 (IntelliCarb Units) Golden Corral | cb2323-cb1522-cb3023-golden-corral | 56 | 5 |
| CI2000 Plus | ci2000-plus | 6 | 2 |
| DB 150 | db-150 | 46 | 3 |
| DB 200 / 275 Standard | db-200-275-standard | 48 | 4 |
| DF 150 | df-150 | 118 | 7 |
| DF 200/250 | df-200-250 | 164 | 8 |
| ED 150 | ed-150 | 158 | 9 |
| ED 200/250 | ed-200-250 | 200 | 10 |
| ED 300 | ed-300 | 91 | 5 |
| IDC255 Pro Fast Gate | idc255-pro-fast-gate | 101 | 11 |
| TJ 150 | tj-150 | 29 | 3 |
| TJ 45 / TJ 90 | tj-45-tj-90 | 33 | 2 |
| Viper 2 Flavor | viper-2-flavor | 109 | 8 |
| Viper 3 Flavor | viper-3-flavor | 143 | 8 |
| Viper 4 Flavor | viper-4-flavor | 107 | 8 |
| Viper Carts | viper-carts | 3 | 1 |
| Backroom Package (McDonald's) | backroom-package-mcdonald-s | 48 | 9 |
| CB1522 18in SABRE TOWER | cb1522-18in-sabre-tower | 25 | 2 |
| CB1522D | cb1522d | 25 | 2 |
| CB2323 SABRE 23in TOWER W/CDD | cb2323-sabre-23in-tower-w-cdd | 34 | 2 |
| CB2323-8vlv (Wendy's) | cb2323-8vlv-wendy-s | 44 | 4 |
| CB2323L SELF CLOSING LID | cb2323l-self-closing-lid | 20 | 2 |
| CB2323L SLIDING LID | cb2323l-sliding-lid | 36 | 2 |
| CC2323 TOWER W/ SLIDING LID | cc2323-tower-w-sliding-lid | 27 | 2 |
| CC2323L SELF CLOSING LID | cc2323l-self-closing-lid | 19 | 2 |
| CI2000 (Plus) | ci2000-plus-parenthesized | 6 | 2 |
| DB 275 - BCP Pneumatic Ice Gate | db-275-bcp-pneumatic-ice-gate | 27 | 5 |
| Energize 6 | energize-6 | 29 | 8 |
| Leopard | leopard | 6 | 3 |
| Prism | prism | 51 | 1 |
| Quest 2000 | quest-2000 | 51 | 16 |
| Quest 4000 | quest-4000 | 63 | 15 |
| SFV - 1 | sfv-1 | 60 | 1 |


## McCann 2.5／20 GALLON（2026-10-18）

核验 CokeParts/myCoke 的7个手册URL及38个零件URL，设备页厂家明确为 MCCANN MANUFACTURING。38个独立零件中新增21条、复用17条；2.5 GALLON为29条/1章节，20 GALLON为31条/4章节。共同引用22条，仅记录官网关联，不认定适配。身份待确认链接0条，1条缺图保留空缺，其他已检查字段齐全。未扩展品牌官网目录。

GET /api/catalog/mccann/models、/mccann/models/{model_id}、/mccann/models/{model_id}/parts。Muse资源 mccann_models、mccann_model、mccann_parts；精确ID为2-5-gallon、20-gallon。零件支持section_id、q、skip、limit（最大100）。

示例：{"resource":"mccann_parts","model_id":"2-5-gallon","limit":25}

请求需认证，仅返回所选机型/章节与当前组织库存；未知机型或跨机型章节404。导入幂等且不增加库存，不自动产生现场验证，不扩展维修指导或实际用料的机型支持。

公开catalog-bundle/mccann提供5份可校验运行数据，来源URL、访问时间、快照哈希保留。本机审核在data/verification/mccann_20261018；待接入列表为审核时快照，最终以mccann_added_manifest.json和mccann_graph.json为准。schema0023，无迁移，前端不变。


## Wunder-Bar Variety Tea Tower（2026-10-18）

核验CokeParts/myCoke的16个手册URL、129个零件URL；设备页厂家为WUNDER-BAR。确认129个独立零件：99条新增、30条复用，覆盖3个官方分组、13个章节。共同引用70条仅表示官网关联，不认定通用。身份待确认链接0条；14条缺图保持空缺，其余已检查字段齐全。未扩展品牌官网目录。

| 官方分组 | model_id | 零件 | 章节 |
|---|---|---:|---:|
| (Crew) Space Saver Variety Tea Tower | crew-space-saver-variety-tea-tower | 70 | 5 |
| (Crew) Variety Tea Tower (Space Saver) | crew-variety-tea-tower-space-saver | 70 | 5 |
| (VTT) Variety Tea Tower | vtt-variety-tea-tower | 115 | 3 |

GET /api/catalog/wunderbar/models、/wunderbar/models/{model_id}、/wunderbar/models/{model_id}/parts。Muse资源wunderbar_models、wunderbar_model、wunderbar_parts，后两项必填精确model_id。零件支持section_id、q、skip、limit（最大100）。

示例：{"resource":"wunderbar_parts","model_id":"vtt-variety-tea-tower","limit":25}

请求需认证，仅返回所选机型/章节与当前组织库存；未知机型或跨机型章节404。两个Space Saver标签保持官网各自记录，不自行合并。导入幂等且不增加库存，不自动产生现场验证，不扩展维修指导或实际用料的机型支持。

公开catalog-bundle/wunderbar提供5份可校验运行数据，保留官网URL、访问时间及快照哈希。本机审核在data/verification/wunderbar_20261018；待接入列表为审核时快照，最终以wunderbar_added_manifest.json和wunderbar_graph.json为准。schema0023，无迁移，前端不变。
