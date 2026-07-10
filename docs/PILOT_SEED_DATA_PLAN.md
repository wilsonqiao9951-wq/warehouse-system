# OpenPartsFlow 试点种子数据计划

目标：在 **首次内部试点** 首日开始前，准备好最小但可跑通全流程的数据集（用户、仓库、零件、库存、工单）。不替代公司主数据治理流程；数字为建议起点，可按现场 SKU 调整。

---

## 1. 必需用户（Required users）

与 `docs/PILOT_RUNBOOK.md` §3 对齐，至少：

| 登录标识建议 | 角色（后端 `UserRole`） | 用途 |
|----------------|-------------------------|------|
| `pilot-admin` | `admin` | 配置、排障、审计 |
| `pilot-manager` | `manager` | 派工、报表、完工核对 |
| `pilot-wh-01` | `warehouse` | 库存、Parts Usage、调拨 |
| `pilot-tech-01` | `engineer`（前端称 technician） | 主试点技师 |
| `pilot-tech-02` | `engineer` | 可选：双技师试点 |

**注意**

- 前端当前通过 **角色下拉 + `X-User-Id`** 与后端用户 ID 绑定；种子用户创建后，将 **数字 ID** 发给每人一页纸，避免选错角色导致 403（`RBAC_ENFORCE=true` 时）。

---

## 2. 必需角色（Required roles）

系统已有角色模型，试点需各至少 **1 人**：

- `admin`
- `manager`
- `warehouse`
- `engineer`（技师）

无需新建「角色类型」；确保每个试点账号的 `role` 字段与上表一致。

---

## 3. 必需仓库（Required warehouses）

| 类型 | 建议名称示例 | 用途 |
|------|--------------|------|
| 主仓 / 中心仓 | `Main DC` | 采购入库、向 van 调拨 |
| 区域仓（可选） | `Regional Hub` | 若业务流程需要 |

至少 **1 个非 van** 仓库用于集中库存与向车上补货场景。

---

## 4. 必需 Van 仓（Van warehouses）

| 建议名称示例 | 关联 | 用途 |
|--------------|------|------|
| `Van - Tech 01` | 绑定 `pilot-tech-01` 用户（`assigned_user_id` 等字段按现有模型） | 技师车上库存 |
| `Van - Tech 02` | 若启用第二技师 | 同上 |

试点 **至少 1 个 Van 仓**；Parts Usage 扣减需指向有效 `warehouse_id`。

---

## 5. 必需零件（Required parts）

建议最少 **5～10 条** 有真实 `part_number` / `name` / `unit` / `default_cost` 的零件主数据，覆盖：

- 高频消耗件 ≥ 2  
- 中频件 ≥ 2  
- 低频或贵重件 ≥ 1（用于异常用量测试）

**字段**：与当前 `Part` / 导入模板一致；若有 `min_stock` / `safety_stock`，填入合理值以便 **低库存告警** 可测。

---

## 6. 最低起始库存（Minimum starting inventory）

目标：支撑 **3 天试点** 内多次「用料 + 可能的退库/调拨」而不频繁断货（除非刻意测断货）。

| 位置 | 建议 |
|------|------|
| Main DC | 每个种子零件 **≥ 20～50** 单位（按历史用量调整） |
| Van - Tech 01 | 每个常用件 **≥ 5～15** 单位 |

- [ ] 导入或手工录入后，在 **Inventory** 页核对 **balances** 与实物大致一致。  
- [ ] 刻意保留 **1～2 个 SKU** 略低于 `min_stock`，用于验证 **低库存告警**（勿影响关键路径工单）。

---

## 7. 样例工单（Sample work orders）

建议准备 **≥ 5 张** 工单，覆盖：

| # | 场景 | 状态建议 | 指派 |
|---|------|----------|------|
| 1 | 标准维修、单地址、有电话 | `open` → 技师 Start | tech-01 |
| 2 | 同一技师第二张进行中 | `in_progress` | tech-01 |
| 3 | 已完成锁定（历史） | `completed` + locked | tech-01 |
| 4 | 另一城市/地址（测筛选与地图链接） | `open` | tech-01 |
| 5 | 可选：指派 tech-02 或无人指派（测经理分配） | `open` | 按试点设计 |

**字段建议**：`ticket_number` / `wo_number`、`store_name` or `outlet_name`、`address`、`city`、`contact_phone`、`schedule_date`（与 Today 视图一致）、`job_type`、`revenue`（用于异常用量报表）。

---

## 8. 推荐测试场景（与种子数据联动）

1. **技师 Day1 上午**：对工单 1 Start → 添加 status → 从 Van 扣一件 Parts Usage（可选带照片）→ 上传 QC → Complete → 确认锁定。  
2. **经理**：Work Orders 筛选、打开 Details、看利润/异常报表、Pilot Checklist。  
3. **仓库**：Inventory 低库存、Parts Usage 从 Main 扣料（若流程允许）、导出 Excel。  
4. **离线/弱网**（可选）：见 `docs/REAL_DEVICE_TEST_PLAN.md`。  
5. **RBAC**：用错误 `X-User-Id` 访问他人 Van 数据应失败（`RBAC_ENFORCE=true`）。

---

## 9. 种子数据执行顺序（建议）

1. Users（各角色）  
2. Warehouses（主仓 + Van）  
3. Parts  
4. Opening inventory / balances  
5. Work orders  
6. 经理抽查 Pilot Checklist + 导出备份  

完成后在 `docs/PILOT_RUNBOOK.md` Pre-Launch Checklist 上打勾。
