# Viper 3 后端试点

从已核验的官网设备/章节页面生成 Viper 3 Flavor 查询图：8个章节、143条独立目录零件。只匹配完整 Viper 3 Flavor 机型及明确官网零件URL，不按名称包含 Viper 推断，不引入Viper 2/4章节。零件可跨机型共享，但只有Viper 3章节明确列出的关联出现在此链路。

## 接口

均使用现有Bearer登录，组织由登录账户决定，不接受客户端传入organization_id。

- `GET /api/catalog/models/viper-3`：官网设备信息、章节及章节零件catalog_id、来源证据、独立零件总数。
- `GET /api/catalog/models/viper-3/parts?section_id=...&q=...&skip=0&limit=25`：按章节或零件号/名称检索，limit最大100。章节ID为官网完整ID，例如`Viper 3 Flavor|Cladding Assembly`。未知或其他机型章节返回404。
- `POST /api/catalog/models/viper-3/field-verifications`：请求`{"part_id":123}`。仅admin、manager、engineer可明确确认本组织零件用于Viper 3；记录确认次数、时间和操作者审计。其他组织零件返回404。重复提交累计确认次数。
- 目录导入复用 `POST /api/catalog/parts/{catalog_id}/import`；不会自动产生库存。

## 查询响应与来源

每条返回catalog_id、零件号、名称、官网链接、图片、official_associations、field_associations及organization_part。

- `official_associations`：官网章节关系和来源页面证据，代表目录列举关系。
- `field_associations.source=field_observation`：历史员工照片/观察记录，不当作已确认适配。
- `field_associations.source=field_verified`：授权人员明确提交的现场验证，属于本组织经验，不改写官网关系，不代表厂家认证。
- `organization_part`：按本组织精确零件号匹配零件库；未导入为null。包含part_id、启用状态、库存总量及仓库/库位数量。未产生库存流水时库存0。未分配库位以location_id=null表示。

现场独有零件可出现在机型总体查询，official_associations为空；由于没有官网章节证据，不纳入章节过滤结果。现阶段只用精确零件号映射组织零件，不自动合并旧编号、厂家编号或类似名称。

库存从本组织流水按目的/来源仓库与库位计算，调拨计入两端，已用/出库扣除。外组织仓库、库位、零件、观察及流水均不返回。官网图片和本地现场照片分别保留。

## 数据生成与验证

`python -m scripts.build_viper3_graph` 从manual_reference_checks.json及页面快照构建data/organized/viper3_graph.json，检查快照哈希后生成。更新图后重启后端以刷新缓存。

测试覆盖8章/143零件、Viper 2/4隔离、章节过滤、库存流水数量/库位、跨组织读写隔离、现场观察/明确验证区分、验证权限和审计。live_api_check.json保存真实Bearer HTTP检索验收结果。前端及原始索引未修改，无数据库结构迁移。

## 工单用料接入

机型零件查询新增`work_order_usage`，与官网关联及现场验证分开。包含用料记录数、实际使用记录数/数量、实际使用工单数、最近使用时间及最多20条最近明细。

新增`GET /api/catalog/models/viper-3/parts/{part_id}/usage?skip=0&limit=25`，返回本组织零件的分页用料明细（limit最大100），未安装记录仍返回但不计实际使用。其他组织零件404。

“实际使用”仅表示工单用料记录明确`installed=yes`且数量>0，不是独立适配认证。其余标为`work_order_material`。每条保留工单号、工单状态、记录时间、数量、安装标记及工单/设备机型来源。用料不创建PartMachineAssociation，不升级现场观察或改写官网关联。

工单machine_type或绑定设备model必须明确为Viper 3；若两者均有值，必须都匹配。未知机型、机型冲突、跨组织设备/工单/零件/仓库均排除。仅有用料证据的本地零件可出现在机型总查询；没有官网章节关系时，不纳入章节过滤。工单数量不再次扣库存，库存仍从现有库存流水读取。

验证：75项回归测试通过；`scripts.verify_live_viper3_usage`使用临时组织和Bearer请求验证实际用料、非安装材料、机型/组织隔离、分页及无自动现场验证，清理临时数据。证据见`data/verification/viper3_usage_api_check.json`。

## 17条增量接入与候选复核

17条官网确认零件由独立补充源接入主目录，catalog_id采用稳定official-viper3-零件号，不重排原目录ID。只接入有明确Viper 3引用的记录，Viper Carts独有零件3506751不接入。新增记录可复用原目录导入入口，由授权用户加入本组织零件库；不会自动新增库存或用料/现场验证。

来源清单及整理文件均用哈希验证，数据变化须重跑scripts.integrate_viper3_parts，再重建scripts.build_viper3_graph并重启后端。补充源独立于原始索引，重复导入同组织零件保持幂等。

27条名称候选重新访问官网，未找到明确Viper 3手册引用，全部保留待核验，见viper3_candidate_review.json。77项测试通过；新增17条主目录与机型查询、原库存与工单实际用料隔离通过Bearer HTTP验证。
