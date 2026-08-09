# OpenPartsFlow 移动端 / PWA QA 清单

在发版或试点升级前，建议在真机 + 桌面组合下按下列项验证。记录环境（浏览器版本、角色、`NEXT_PUBLIC_API_BASE_URL`）、通过/失败与截图。

## 环境与安装

- [ ] iPhone Safari：可打开站点、无横向溢出、安全区正常（含刘海屏）
- [ ] Android Chrome：同上
- [ ] PWA 安装后主屏启动为 **standalone**（无浏览器地址栏）
- [ ] 离线横幅：飞行模式 / 断网时出现 **You are offline** 提示
- [ ] 离线配置表单：保存后 `/sync-center` 显示同一账号、设备、工单和认领代次
- [ ] 离线配置表单照片与 QC 照片：显示设备保留状态，联网后先上传照片再提交记录
- [ ] 离线照片限制：超过 10 MiB、12 张或 50 MiB 总量时给出明确错误
- [ ] 未附加照片可在 `/sync-center` 手动丢弃；已附加到队列的照片不能单独删除
- [ ] 离线库存领用、状态、完成、审批、调拨、签收和盘点全部提示需要联网，且不进入队列
- [ ] 浏览器仍显示在线但 API 已停止时，允许的表单/照片仍能保留，未允许的写操作仍被阻断
- [ ] 在线依次打开工单池、工单详情、配置表单、推荐和车辆库存，然后断网确认同一账号/设备可重新查看
- [ ] 离线只读横幅显示快照保存时间，重新连上 API 并成功读取后横幅消失
- [ ] 换账号或换注册设备后不能看到前一个账号/设备的只读快照
- [ ] 未在线打开过的审核接口在断网时明确提示没有本机快照，不返回其他路径的近似数据
- [ ] API 停止但浏览器仍显示在线时，读取回退到快照且不会清除本机登录状态
- [ ] Service Worker 或反向代理返回 502/503/504 时，只读请求回退快照、白名单写入进入隔离队列、其他写入仍失败关闭
- [ ] 只读快照不能让认领、状态、完成、库存或审批按钮在断网时成功
- [ ] 恢复联网后横幅消失，接口可再次成功

## 角色与导航

- [ ] **Technician**：底栏顺序为 Today → Map → My Jobs → My Van → Profile；登录账号、注册设备和 claim 变化后权限即时更新
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
- [ ] 与 FastAPI 联调：登录、RBAC、注册设备和 claim 拒绝场景有可读错误且不泄露他人数据
