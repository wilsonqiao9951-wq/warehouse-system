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
