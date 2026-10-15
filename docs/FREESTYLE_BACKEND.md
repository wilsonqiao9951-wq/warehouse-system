# Freestyle主目录与分机型查询

543条官网确认的新零件以独立补充源接入主目录，稳定ID为`official-freestyle-{零件号}`，原主目录及Viper 3 ID不重排。完整Freestyle目录有1,141条独立零件，各机型分别建立官网章节图。共享引用不代表跨机型适配认证。

## 接口

使用既有Bearer登录。库存组织取自当前用户，不接受organization_id请求参数。

- `GET /api/catalog/freestyle/models`：8个机型、零件与章节数量。
- `GET /api/catalog/freestyle/models/{model_id}`：机型、章节及明确关联的catalog_id。
- `GET /api/catalog/freestyle/models/{model_id}/parts`：支持section_id、q、skip、limit（1–100）。只展示该机型的官网关系；返回精确零件号匹配的本组织零件库、库存量和仓库/库位。其他机型章节或未知机型404。

model_id：3100、4000、7000、7100、8000、8100、9000、9100。

每条返回`official_associations`，只含当前机型/选中章节的引用证据，`cross_model_compatibility_confirmed=false`。接口不生成现场验证或实际使用，也不根据共享零件推断其他机型的适配。未在本组织导入时organization_part=null。

目录导入复用`POST /api/catalog/parts/{catalog_id}/import`，仅既有授权角色可操作，同组织重复导入幂等；不产生库存流水。厂家状态/官网引用不是现场适配认证。Viper 3既有实际用料、现场验证及查询接口不变。

## 数据与复现

- freestyle_new_official_parts.json：确认的543条增量来源。
- freestyle_added_parts.json及freestyle_added_manifest.json：补充目录及来源/整理文件哈希；数据改变时拒绝加载，须重建。
- freestyle_graph.json：8个模型与章节关系。
- freestyle_parts_catalog.json及freestyle/*.json：完整审核清单及分机型交付清单。

先`python -m scripts.integrate_freestyle_parts`，再`python -m scripts.build_freestyle_graph`，更新后重启后端刷新缓存。保留原始索引文件不变。

## 验收

81项测试通过。真实Bearer HTTP验证全部543条主目录增量、8个模型完整分页、章节过滤、来源区分及匿名访问拒绝；测试覆盖同组织导入幂等、库存数量、其他组织隔离、不自动生成适配记录。现有Viper 3及工单用料真实接口复验通过。

证据：freestyle_integration_api_check.json、live_api_check.json、viper3_usage_api_check.json。

异常链接`35085-001-524 | PLEXUS CORP`复查HTTP404，目录没有明确编号映射，保留原引用待核验，不创建零件或机型适配。

## 工单实际使用与现场验证

分机型零件响应新增：

- `work_order_usage`：工单材料数、实际使用记录数、实际使用数量、实际使用工单数、最近实际使用时间及最多20条最近记录。
- `field_associations`：`field_observation`是普通观察，`field_verified`是授权人员明确确认；与`official_associations`独立。

新增接口：

- `GET /api/catalog/freestyle/models/{model_id}/parts/{part_id}/usage?skip=0&limit=25`：本组织零件在该机型的分页用料记录，limit最大100。其他组织零件404。
- `POST /api/catalog/freestyle/models/{model_id}/field-verifications`：JSON `{"part_id":123}`。仅admin、manager、engineer可以明确确认，记录操作者审计、时间与次数。同组织之外零件404，未知机型404。并发重复确认冲突返回409，可重试。

“实际使用”仅表示用料记录明确installed=yes且quantity>0，source为actual_usage；其余记录source=work_order_material，不计入实际使用统计。返回工单号、工单状态、数量、安装标记、记录时间、工单机型及设备机型，不代表独立适配认证；compatibility_confirmed=false。查询不会新增现场确认、官网关系或再次扣减库存。

工单machine_type与设备model若同时存在，必须都精确匹配当前机型；只存在其中一个时须为明确机型。接受完整官网机型名、精确数字编号、Freestyle加精确数字编号；仅规范大小写、空格及连字符。范围描述、其他编号、未知或冲突机型排除，7000不匹配7100、8000不匹配8100、9000不匹配9100。绑定了其他组织设备的工单也排除。

工单、用料、零件、仓库、设备和现场关联均按组织隔离。只有实际用料/观察证据的本地零件可以出现在机型总体查询；没有官网章节依据的，不纳入章节过滤。现场确认不扩散到其他机型。普通照片观察不会增加已明确验证的次数或刷新确认时间。

本轮91项测试通过；全部8机型真实Bearer验证通过，临时组织与数据清理。证据：freestyle_usage_api_check.json。原有543条增量及8机型目录查询与Viper 3用料接口继续复验。
