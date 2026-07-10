# OpenPartsFlow 公网 / 手机公开测试清单

配合 **Cloudflare Tunnel** 与 `docs/CLOUDFLARE_TUNNEL_GUIDE.md`、`docs/ENVIRONMENT_SETUP.md` 使用。每项打勾并记录环境（隧道 URL 仅写在本地笔记，勿提交仓库）。

---

## 启动前

- [ ] **后端**已在本机 **http://127.0.0.1:8000**（或文档约定端口）运行，`/docs` 可打开。
- [ ] **前端开发服务器**运行在 **http://localhost:3002**（若 3000/3001 被占用，以实际终端输出为准，并同步 CORS 与本文「端口」说明）。
- [ ] `NEXT_PUBLIC_API_BASE_URL` 已按 `ENVIRONMENT_SETUP.md` 配置为 **手机可解析的地址**（**不能**仍是 `http://localhost:8000`，除非手机上的「localhost」指向你的电脑——一般不成立）。
- [ ] 后端 `.env` 中 **`CORS_EXTRA_ORIGINS`** 已包含前端公网 **HTTPS origin**（Quick Tunnel 或自有域名），并已 **重启 Uvicorn**。

---

## 手机可达性

- [ ] Cloudflare 给出的 **HTTPS** 前端 URL 在手机 Safari/Chrome 能打开。
- [ ] 打开浏览器开发者工具（或抓包）确认 API 请求指向 **公网可达** 的后端基址，且无 **CORS** 红字。

---

## 功能冒烟（公网）

- [ ] **相机 / 相册上传**：Parts Usage 或工单详情 QC，拍照或选图 → 预览 → 提交；失败时错误文案可读。
- [ ] **PWA**：HTTPS 下尝试「添加到主屏幕」/「安装应用」（行为因平台而异，见 `APP_BUILD_GUIDE.md`）。
- [ ] **技师流程**：Today / My Jobs → Start →（可选）QC / 用料 → Complete；锁定态符合预期。
- [ ] **经理**：Dashboard / Work Orders 筛选 / Reports 异常列表 / Pilot Checklist。
- [ ] **库存**：Inventory 与低库存区域可加载。
- [ ] **离线横幅**：飞行模式或断网时出现离线提示；恢复网络后恢复。
- [ ] **图片 URL**：QC 使用「粘贴 URL」方式时，列表中图片可加载（注意混合内容与跨域）。
- [ ] **RBAC**：错误 **`X-User-Id`** 或角色下应 403 的接口被拒绝（`RBAC_ENFORCE=true` 时）。

---

## 收尾

- [ ] 关闭不再需要的 `cloudflared` 进程，避免误暴露本机服务。
- [ ] 删除或轮换已泄露的临时 URL 相关凭据（若适用）。
