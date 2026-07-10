# OpenPartsFlow 移动端 / PWA QA 清单

在发版或试点升级前，建议在真机 + 桌面组合下按下列项验证。记录环境（浏览器版本、角色、`NEXT_PUBLIC_API_BASE_URL`）、通过/失败与截图。

## 环境与安装

- [ ] iPhone Safari：可打开站点、无横向溢出、安全区正常（含刘海屏）
- [ ] Android Chrome：同上
- [ ] PWA 安装后主屏启动为 **standalone**（无浏览器地址栏）
- [ ] 离线横幅：飞行模式 / 断网时出现 **You are offline** 提示
- [ ] 恢复联网后横幅消失，接口可再次成功

## 角色与导航

- [ ] **Technician**：底栏顺序为 Today → Map → My Jobs → My Van → Profile；可切换 `X-User-Id` 后请求带头
- [ ] **Manager / Admin**：顶栏含 Dashboard、Work Orders、Calendar、Map、Inventory、Employees、Reports、Pilot、Settings 等
- [ ] **Warehouse**：可访问 Parts Usage、Inventory 等预期页面

## 工单与现场操作

- [ ] Work Orders：移动端为 **卡片**，宽屏为 **表格**；筛选区在窄屏可折叠（`Filters` 摘要）
- [ ] Work Order Detail：摘要、地址、联系人、描述、时间线、Parts used、QC、退料区块可读；锁定态明确
- [ ] My Jobs / Today：卡片上 **Navigate / Call / Start / Complete / Open** 可用；锁定工单 Start/Complete 禁用
- [ ] Start job：状态与详情刷新正确；错误时展示接口 `detail` 文案
- [ ] Complete job：完工锁定后出现锁定提示
- [ ] Parts Usage：提交用料成功；失败时错误可读；可选拍照上传

## 库存与报表

- [ ] Inventory：低库存 **告警区** 展示；表格在窄屏可横向滚动或换行不撑破布局
- [ ] Reports：异常用量在移动端以 **卡片** 高亮；桌面表格完整

## Pilot 与管理

- [ ] Pilot Checklist：以 **指标卡片** 展示；异常计数类指标在大于 0 时有视觉强调
- [ ] Dashboard：KPI 加载骨架/完成后数据正确（manager/admin）

## Service Worker 与缓存

- [ ] 断网后仍可打开此前访问过的**同源**静态页（若已被缓存）
- [ ] 断网时 **不会** 对 API 返回「假成功」；创建/更新操作失败有明确提示

## 回归（桌面 Manager）

- [ ] Work Orders 表格编辑、保存、分页、URL 查询参数同步
- [ ] 与 FastAPI 联调：RBAC、`X-User-Id` 拒绝场景有可读错误
