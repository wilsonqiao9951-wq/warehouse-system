# OpenPartsFlow 前端构建与 PWA / Capacitor 指南

本文说明如何在本地运行 Next.js 前端、构建静态资源、安装 PWA，以及使用 Capacitor 打包原生壳时的注意事项。

## 架构摘要

- **后端**：FastAPI（默认 `http://127.0.0.1:8000/api`）。
- **前端**：Next.js 16，`output: "export"` 静态导出，产物目录为 `frontend/out`（Node.js 20.9+）。
- **PWA**：`public/manifest.json`、`public/sw.js`（仅缓存**同源**静态资源，**不**缓存跨域 API 响应，避免离线误读接口数据）。
- **Capacitor**：`frontend/capacitor.config.ts` 中 `webDir: "out"`，`appId: com.openpartsflow.app`，`appName: OpenPartsFlow`。

## 本地运行

在 PowerShell 中（注意使用 `;` 而不是 `&&` 连接命令）：

```powershell
Set-Location c:\Users\wilso\OpenPartsFlow\frontend
npm install
$env:NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:8000/api"
npm run dev
```

也可在**仓库根目录**执行（根目录 `package.json` 会转发到 `frontend`）：

```powershell
Set-Location c:\Users\wilso\OpenPartsFlow
npm install --prefix frontend
npm run dev:3002
```

浏览器访问 Next 开发服务器提示的地址（一般为 `http://localhost:3000`）。  
确保 FastAPI 已启动且与 `NEXT_PUBLIC_API_BASE_URL` 一致。

**说明**：`next.config.mjs` 仅在 **`npm run build`（生产）** 时启用 `output: "export"`；`next dev` 下不启用，以避免与 Cloudflare Tunnel 联调时偶发的 **`Cannot find module './xx.js'`** 等开发缓存/chunk 错误。静态产物与 PWA 行为仍以 `npm run build` 结果为准。

## 构建前端

```powershell
Set-Location c:\Users\wilso\OpenPartsFlow\frontend
npm run build
```

成功后应生成 `frontend/out` 目录。Capacitor `npx cap sync` 会读取该目录。

## 如何测试移动端视口

1. 使用 Chrome DevTools → **Toggle device toolbar**（设备模拟）。
2. 选择 iPhone / Pixel 等机型，检查底栏、安全区、横向是否溢出。
3. 在 Application → **Manifest** / **Service workers** 中核对 PWA 注册情况。

## 在 iPhone（Safari）上安装 PWA

1. 将静态站点部署到 **HTTPS**（iOS 要求安全上下文才能稳定使用 SW / 安装）。
2. Safari 打开站点 → 分享按钮 → **Add to Home Screen**。
3. 主屏幕图标来自 `manifest.json` 与 `apple-touch-icon` 相关配置（见 `app/layout.tsx` metadata）。

## 在 Android（Chrome）上安装 PWA

1. Chrome 打开 HTTPS 站点。
2. 若满足安装条件，地址栏或菜单会出现 **Install app**；也可使用应用内「Install app」按钮（由 `beforeinstallprompt` 触发）。

## Capacitor：安装与同步

**说明**：仓库已包含 `capacitor.config.ts` 时，一般**不需要**再执行 `npx cap init`（会与现有配置冲突）。推荐流程：

```powershell
Set-Location c:\Users\wilso\OpenPartsFlow\frontend
npm run build
npm install
npx cap add android   # 首次添加平台时执行一次
npx cap add ios       # 需在 macOS + Xcode 环境
npx cap sync
```

- `npm run cap:sync` 等同于 `npx cap sync`（见 `package.json` scripts）。
- `npm run cap:open:android` / `cap:open:ios` 用于打开原生工程。

## Android 打包（概要）

1. 完成 `npm run build` 与 `npx cap sync`。
2. 用 Android Studio 打开 `frontend/android`（若已 `cap add android`）。
3. 在 Android Studio 中配置签名、生成 **AAB/APK** 并走 Play 内测流程。

## iOS 打包（概要）

1. 在 **macOS** 上安装 Xcode、CocoaPods。
2. `npx cap add ios` 后 `npx cap sync`，用 Xcode 打开 `frontend/ios/App`。
3. 配置 Bundle ID、签名与 TestFlight / App Store 流程。

## 部署策略与已知限制

1. **静态导出**：当前 `next.config.mjs` 使用 `output: "export"`，适合托管到任意静态文件服务器 + PWA。若未来引入必须服务端渲染的动态路由或部分 Next 特性，需重新评估是否改为 Node 托管或 **Capacitor 加载远程 URL**（`server.url` 指向已部署的 HTTPS 站点）。
2. **API 与离线**：Service Worker **不会**把 `NEXT_PUBLIC_API_BASE_URL` 指向的跨域接口响应写入 Cache API；离线时接口会失败，界面依赖 `lib/api.ts` 与离线横幅提示，**不会伪造写入成功**（未实现离线队列前）。
3. **工单零件列表**：`GET /work-order-parts` 单次最多 `limit=100`（后端限制）；若试点数据量更大，需在后续迭代增加按 `work_order_id` 筛选的 API。
4. **Capacitor 首次添加平台**：本仓库未必已提交 `android/`、`ios/` 目录；新环境需本地执行 `cap add` 再同步。

## 建议的后续能力（未实现）

- 推送通知（FCM / APNs）
- 条码扫描（Capacitor 插件）
- 离线工单队列与冲突解决
- 照片压缩与上传体积控制
- GPS 到岗签到与地理围栏

---

## 使用 Cloudflare Tunnel 做公网手机测试

**目标**：在不改业务代码的前提下，用 HTTPS 暴露本机前端，供外网手机访问（PWA、相机上传等）。详细步骤见 **`docs/CLOUDFLARE_TUNNEL_GUIDE.md`** 与 **`docs/PUBLIC_TESTING_CHECKLIST.md`**。

**简要流程（Wilson / PowerShell）**

1. 启动后端：`uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`（项目根目录、虚拟环境已激活）。  
2. 启动前端并固定使用 **3002**：`Set-Location frontend; npm run dev`（若 Next 自动改用其他端口，以终端为准并更新 CORS / 隧道 URL）。  
3. **仅测页面**时：新开窗口执行 `cloudflared tunnel --url http://localhost:3002`，用手机打开输出的 `https://....trycloudflare.com`。  
4. **要测 API**：再对后端开一条隧道 `cloudflared tunnel --url http://127.0.0.1:8000`，在 `frontend/.env.local` 设置  
   `NEXT_PUBLIC_API_BASE_URL=https://<后端隧道主机>/api`，在根目录 `.env` 设置  
   `CORS_EXTRA_ORIGINS=https://<前端隧道主机>`（无尾斜杠），**重启 Uvicorn 与 `npm run dev`**。  
5. 手机打开 **前端** HTTPS URL；在 **Profile** 核对显示的 API base URL 是否正确。  

**注意**：不要把临时 `trycloudflare.com` 字符串写进 Git；仅用环境变量与本地 `config.yml`。仅隧道前端、API 仍指向 `localhost` 时，手机无法访问 API（见 **`docs/ENVIRONMENT_SETUP.md`**）。
