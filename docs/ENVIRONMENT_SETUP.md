# OpenPartsFlow 环境变量说明（前后端）

本文说明 **`NEXT_PUBLIC_API_BASE_URL`**（前端）与 **`CORS_EXTRA_ORIGINS`**（后端，公测用）在不同场景下的取值。  
前端请求路径为：`{NEXT_PUBLIC_API_BASE_URL}` + `/work-orders` 等，因此基址 **必须包含 `/api` 后缀**（与当前 `frontend/lib/api.ts` 约定一致）。

---

## 前端：`NEXT_PUBLIC_API_BASE_URL`

| 场景 | 示例值 | 说明 |
|------|--------|------|
| **本机桌面浏览器** | `http://127.0.0.1:8000/api` 或 `http://localhost:8000/api` | 与本地 Uvicorn 一致即可。 |
| **手机与电脑同一 Wi‑Fi** | `http://192.168.x.x:8000/api` | `192.168.x.x` 为电脑局域网 IP；手机上的 `localhost` **不是**你的电脑。 |
| **Cloudflare 仅暴露后端** | `https://<后端隧道主机>/api` | 例如 Quick Tunnel 打印的 `https://xxxx.trycloudflare.com/api`。 |
| **自有域名 + 命名隧道** | `https://api-openparts.yourdomain.com/api` | 与 DNS、`config.yml` 中 `ingress` 一致。 |

### 重要：仅隧道前端时

若只运行：

```text
cloudflared tunnel --url http://localhost:3002
```

手机浏览器里的页面仍会把 API 发到 **`NEXT_PUBLIC_API_BASE_URL`**。若该变量仍是 `http://localhost:8000/api`，请求会打到 **手机自己**，**不会**到你的电脑。

**二选一：**

1. **再开一条隧道** 指向 `http://127.0.0.1:8000`，并把 `NEXT_PUBLIC_API_BASE_URL` 设为该 HTTPS 地址 + `/api`；或  
2. 将后端部署到已公网可访问的 HTTPS 地址，再配置前端。

每次修改 `NEXT_PUBLIC_API_BASE_URL` 后，开发模式需 **重启 `npm run dev`**；生产静态构建需 **重新 `npm run build`** 并重新部署产物。

---

## 后端：`.env` 中与公测相关的变量

| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | 数据库连接（试点勿用生产库）。 |
| `RBAC_ENFORCE` | `true` / `false`（见试点文档）。 |
| **`CORS_EXTRA_ORIGINS`** | **逗号分隔**的前端 origin 列表，无空格或自行去掉空格。用于 Cloudflare Quick Tunnel、自有域名等 **不在代码默认列表中的 HTTPS 源**。示例： `https://abc123.trycloudflare.com,https://openparts.example.com` |

修改 `CORS_EXTRA_ORIGINS` 后请 **重启 Uvicorn**。

默认仍包含 `http://localhost:3000`～`3002` 与 `127.0.0.1` 同源端口，便于本地开发。

---

## 根目录 `.env.example`

仓库根目录 `.env.example` 含后端变量示例；前端单独见 **`frontend/.env.example`**。

---

## 校验清单

1. 手机打开前端 HTTPS URL。  
2. **Profile** 页查看「当前 API Base URL」是否与预期一致。  
3. 打开 `/docs`（若对公网开放）或任意列表接口，确认无 CORS 错误。
