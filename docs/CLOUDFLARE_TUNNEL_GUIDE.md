# OpenPartsFlow — Cloudflare Tunnel 公开测试指南（Windows / PowerShell）

本文说明如何用 **Cloudflare Tunnel（cloudflared）** 把本机前端（如 `http://localhost:3002`）和/或后端（`http://127.0.0.1:8000`）暴露到公网，供手机 HTTPS 访问与 PWA 测试。  
**勿将临时 `trycloudflare.com` URL 写入仓库源码**；仅通过环境变量与本地 `config.yml` 配置。

**前置条件**

- 已安装 [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)，且 `cloudflared version` 在 PowerShell 中可用。

### Windows：若提示 `cloudflared` 不是内部或外部命令

用 **winget** 安装（推荐）：

```powershell
winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
```

安装完成后 **关闭并重新打开** PowerShell（或注销再登录），使 PATH 生效；再执行：

```powershell
cloudflared --version
```

若仍找不到，可用**完整路径**运行（winget 默认常见位置）：

```powershell
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" --version
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:3002
```

或在**当前** PowerShell 会话临时加入 PATH 后再用 `cloudflared`：

```powershell
$env:Path += ";C:\Program Files (x86)\cloudflared"
cloudflared --version
```

若安装目录不同，可在资源管理器中搜索 `cloudflared.exe` 以本机为准。
- 本机已运行：FastAPI（8000）、Next 开发服务器（**3002**，与当前约定一致）。

---

## A. 快速临时公网 URL（Quick Tunnel）

仅暴露**前端**（适合先确认隧道与手机能打开页面；**若 API 仍是本机 localhost，手机无法调 API** — 见 `docs/ENVIRONMENT_SETUP.md`）。

```powershell
cloudflared tunnel --url http://localhost:3002
```

终端会打印类似 `https://<random>.trycloudflare.com` 的 **HTTPS** URL，用手机浏览器打开即可。

**Windows 上可能出现的 `ERR Cannot determine default origin certificate path` / `cert.pem`**

Quick Tunnel 在部分 Windows 环境会打印上述 **ERR**（与命名隧道用的 `cert.pem` 有关）。若随后日志出现 **`Registered tunnel connection`** 且浏览器能打开 trycloudflare 地址，通常 **可忽略**。若页面始终打不开，再确认本机 `http://localhost:3002` 已启动，并查阅 [Cloudflare Tunnel 故障排查](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/troubleshoot-tunnels/)。

仅暴露**后端**（用于把 API 单独暴露给已配置好的前端）：

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

记下输出的 `https://...trycloudflare.com`，将其作为 `NEXT_PUBLIC_API_BASE_URL` 的 **origin + `/api`**（见环境文档）。**每次重启 quick tunnel，URL 会变**，需同步更新前端环境并重启 `npm run dev`。

---

## B. 前端与后端各一条 Quick Tunnel（常见手机联调）

开**两个** PowerShell 窗口：

**窗口 1 — 前端**

```powershell
cloudflared tunnel --url http://localhost:3002
```

**窗口 2 — 后端**

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

然后：

1. 在 `frontend/.env.local` 设置 `NEXT_PUBLIC_API_BASE_URL=https://<后端隧道主机>/api`（路径必须以 `/api` 结尾，与 `lib/api.ts` 一致）。
2. 将后端隧道域名加入后端 **CORS**：根目录 `.env` 中 `CORS_EXTRA_ORIGINS` 增加前端隧道完整 URL（含 `https://`），逗号分隔。重启 Uvicorn。
3. **重启** Next：`Ctrl+C` 后再次 `npm run dev`（确保 3002 且加载新 env）。

---

## C. 永久命名隧道（Named tunnel + 自有域名）

适用于固定子域、团队长期公测（需在 Cloudflare DNS 托管域名）。

```powershell
cloudflared tunnel login
cloudflared tunnel create openpartsflow
cloudflared tunnel route dns openpartsflow openparts.yourdomain.com
cloudflared tunnel route dns openpartsflow api-openparts.yourdomain.com
```

> 若 `tunnel route dns` 语法随 CLI 版本变化，以 [官方文档](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) 为准。

使用 **配置文件** 代替仅 `tunnel run` 默认行为（推荐）：

```powershell
cloudflared tunnel run openpartsflow
```

---

## D. 示例配置文件（Windows）

路径（按用户替换）：`%USERPROFILE%\.cloudflared\config.yml`  
例如用户名为 Wilson：`C:\Users\Wilson\.cloudflared\config.yml`。

**示例内容**（域名、隧道名、`credentials-file` 文件名请按你账号实际修改）：

```yaml
tunnel: openpartsflow
credentials-file: C:\Users\Wilson\.cloudflared\<tunnel-uuid>.json

ingress:
  - hostname: openparts.yourdomain.com
    service: http://localhost:3002
  - hostname: api-openparts.yourdomain.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

- `<tunnel-uuid>.json` 为 `cloudflared tunnel create` 后生成的凭证文件名。
- `service` 指向本机服务；**无需**在 YAML 里写死 `trycloudflare` 临时域名。

---

## Wilson 建议执行顺序（PowerShell 摘要）

**仅 Quick Tunnel 验证页面能否打开：**

```powershell
# 1）本机已启动后端与前端（前端端口 3002）
# 2）新窗口：
cloudflared tunnel --url http://localhost:3002
# 3）手机打开输出的 https://....trycloudflare.com
```

**Quick Tunnel 同时测 API（推荐公测最小集）：**

```powershell
# 窗口 A
cloudflared tunnel --url http://127.0.0.1:8000
# 窗口 B
cloudflared tunnel --url http://localhost:3002
# 然后按 docs/ENVIRONMENT_SETUP.md 设置 NEXT_PUBLIC_API_BASE_URL 与 CORS_EXTRA_ORIGINS，重启前后端。
```

**命名隧道：**

```powershell
cloudflared tunnel login
cloudflared tunnel create openpartsflow
# 配置好 %USERPROFILE%\.cloudflared\config.yml 后：
cloudflared tunnel run openpartsflow
```

---

## 已知限制

- Quick Tunnel URL **每次变化**；正式演示优先命名隧道或固定域名。
- 浏览器 **混合内容**：HTTPS 页不能请求 `http://` API；公网前端应对 **HTTPS** API。
- 后端 **CORS** 必须包含浏览器地址栏中的前端 **origin**（含 `https://` 与端口，若有）。
- **不要**把临时隧道 URL提交到 Git；仅用 `.env` / `.env.local` / `CORS_EXTRA_ORIGINS`。
