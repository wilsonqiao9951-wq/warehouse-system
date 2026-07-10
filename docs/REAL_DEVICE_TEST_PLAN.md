# OpenPartsFlow 真机试点测试计划

本文用于 **iPhone / Android 真机** 上的 PWA 可靠性验证，配合 `docs/MOBILE_QA_CHECKLIST.md` 与 `docs/APP_BUILD_GUIDE.md` 使用。不替代自动化测试，侧重现场操作与网络环境。

---

## 一、测试前：移动端环境核对清单

### 1. 后端 API 地址（必查）

- 前端构建或运行前设置 **`NEXT_PUBLIC_API_BASE_URL`**，指向可自手机访问的 API 根路径，例如：`https://pilot-api.example.com/api` 或局域网 `http://192.168.1.10:8000/api`。
- 手机浏览器访问的页面域名与 API 域名若不同，需确认 **FastAPI CORS** 已允许该前端来源，否则接口与上传会失败。

### 2. 局域网（同一 Wi‑Fi）联调

- 将 **笔记本电脑（跑后端）** 与 **手机** 连到 **同一 Wi‑Fi**。
- 电脑使用 `ipconfig`（Windows）查看局域网 IPv4，用该地址替换 `127.0.0.1` 写入 `NEXT_PUBLIC_API_BASE_URL` 并重新构建/部署静态前端（若已导出）。
- 在手机 Safari/Chrome 中直接打开前端地址（例如 `http://192.168.x.x:3000` 或静态服务器地址）进行测试。

### 3. Windows 防火墙

- 若手机无法访问电脑上的 8000/3000 端口，在 **Windows Defender 防火墙** 中为对应端口添加入站规则，或仅在受信网络下临时关闭防火墙做联调（**勿在生产环境长期关闭**）。

### 4. HTTPS 与完整 PWA 安装

- **iOS Safari** 对 Service Worker、主屏安装、部分 API 要求 **HTTPS**（`localhost` 例外）。
- 真机「完整 PWA 体验」（安装到主屏、稳定 SW）建议在 **HTTPS 试点环境** 验证。
- **临时本地选项**：同一局域网内用 **HTTP + IP** 可验证大部分业务与上传；安装到主屏、SW 行为可能与 HTTPS 环境略有差异，须在正式 HTTPS 上复测一遍。

---

## 二、生产部署核对清单（试点 / 生产）

| 项 | 说明 |
|----|------|
| **前端托管** | 将 `next build` 产物 `frontend/out` 部署到支持 SPA 回退的静态托管（或 CDN），路由需回到 `index.html` / 各路由 `index.html`（与 `trailingSlash` 一致）。 |
| **后端托管** | FastAPI 进程 + 反向代理（如 nginx），健康检查与日志。 |
| **数据库迁移** | Alembic / 既定迁移流程在生产库执行，并有回滚或备份方案。 |
| **环境变量** | 生产 `NEXT_PUBLIC_API_BASE_URL`、后端 DB URL、密钥、`RBAC_ENFORCE` 等与运行手册一致。 |
| **HTTPS** | 全站 TLS，证书续期策略。 |
| **文件上传存储** | `uploads/work-order-parts` 等目录持久化到磁盘或对象存储；多实例时需共享存储或统一上传服务。 |
| **备份策略** | 数据库定期备份、上传目录备份、恢复演练记录。 |

---

## 三、真机功能测试步骤

以下为 **逐条勾选** 的推荐顺序。每条记录：设备型号、系统版本、浏览器、角色、`X-User-Id`、通过/失败、截图或日志。

### A. PWA 安装

1. **iPhone Safari — PWA 安装**
   - 用 Safari 打开 **HTTPS** 试点站点 → 分享 → **添加到主屏幕**。
   - 从主屏幕图标启动，确认以 **全屏 / standalone** 样式打开（无 Safari 地址栏）。
2. **Android Chrome — PWA 安装**
   - Chrome 打开 HTTPS 站点 → 菜单或安装提示 → **安装应用** 或 **添加到主屏幕**。
   - 从启动器打开，确认独立窗口样式。

### B. 登录与角色（模拟）

> 当前试点 UI 使用顶部 **角色下拉** + **`X-User-Id`** 模拟身份，非 OAuth 真登录。

3. **Technician 模拟**
   - 角色选 **technician**，填写与后端一致的 **`X-User-Id`**（数字）。
   - 确认底栏：Today / Map / My Jobs / My Van / Profile 可切换，接口请求正常。
4. **Manager 模拟**
   - 角色选 **manager**，填写 **`X-User-Id`**。
   - 确认 Dashboard、Work Orders、Reports、Pilot Checklist、Inventory 等入口可访问。

### C. 工单现场操作（手机）

5. **Start job（手机）**
   - 从 **My Jobs** 或 **Today** 或 **Work Order Details** 对未锁定工单执行 **Start**。
   - 期望：成功提示或状态变为进行中；失败时展示 **可读错误**（含离线提示）。
6. **Complete job（手机）**
   - 对同一工单执行 **Complete**。
   - 期望：工单锁定，再次操作 Start/Complete 应禁用或报错明确。
7. **Add parts used（手机）**
   - 打开 **Parts Usage**（warehouse/admin 角色），选择工单、零件、仓库、数量。
   - 可选：**拍照 / 相册** 附预览 → 提交；期望库存逻辑成功，错误时文案可读。
8. **Upload QC picture（手机相机）**
   - 打开 **Work Order Details**，在 **QC pictures** 使用 **Take QC photo** 或 **Choose from library**。
   - 期望：预览出现 → 上传进度或「Working…」→ 成功后列表中缩略图可打开；失败时错误可读。

### D. 网络与离线

9. **Offline banner**
   - 开启飞行模式或断开 Wi‑Fi，在应用内导航。
   - 期望：顶部出现 **You are offline** 横幅；API 操作失败且 **不伪造成功写入**。
10. **Reconnect**
    - 恢复网络，等待横幅消失；再次执行一次只读请求（如列表）与一次写操作（如 Start 或添加 QC）。
    - 期望：读写恢复正常，无需强制杀进程。

### E. 报表与库存

11. **Low stock alert**
    - **Inventory** 页顶部 **低库存告警** 区域与 KPI 是否与后端数据一致。
12. **Abnormal usage report**
    - **Reports** 页异常用量列表/卡片是否展示、导出链接在真机是否可打开（注意跨域与登录）。

---

## 四、测试结论模板（可复制）

```
日期：
测试人：
环境：HTTPS / HTTP+LAN   前端 URL：
API：NEXT_PUBLIC_API_BASE_URL=
设备：iPhone ___ / Android ___  系统版本：___

| 序号 | 项 | 结果 | 备注 |
|------|----|------|------|
| 1 | iPhone PWA 安装 |  |  |
| 2 | Android PWA 安装 |  |  |
| ... | ... |  |  |

阻塞问题：
非阻塞问题：
```

---

## 五、如何在真机上测（最短路径）

1. 电脑启动 FastAPI，确认手机能访问 `http://<电脑局域网IP>:8000/docs` 或健康接口。
2. 前端 `NEXT_PUBLIC_API_BASE_URL` 设为 `http://<电脑IP>:8000/api`，`npm run dev -- -H 0.0.0.0` 或部署静态 `out` 到同一网段可访问地址。
3. 手机浏览器打开前端 URL → 选角色、填 `X-User-Id` → 按第三节顺序执行。
4. 若需验证 **完整 PWA 安装**，将同一套前后端部署到 **HTTPS 试点域名** 后重复 A、D 节。
