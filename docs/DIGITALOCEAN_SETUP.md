# DigitalOcean共享后端开通与交接

状态：已选方案，尚未创建服务器、购买域名或部署上线。预算为每月35–40美元，前端不改。仓库为https://github.com/wilsonqiao9951-wq/warehouse-system 。

## 费用（2026-10-15核对）

选择Bundled → Shared CPU → Basic → Regular：2 vCPU、4 GiB RAM、80 GiB SSD、4,000 GiB月出站额度，24美元/月。Daily Backups按服务器价30%计，7.20美元/月。基础合计31.20美元/月；税、域名、超额流量、额外存储及额外备份另计。35–40美元是规划预算，不是平台硬性封顶；如结算页价格不同，先核对后创建。不要误选按小时且没有同样月封顶的v5配置。当前案例检索没有大模型API费用；后续增加生成式指导需另核算。

来源：https://www.digitalocean.com/pricing/droplets 和 https://docs.digitalocean.com/products/backups/details/pricing/ 。

## 所有者开通步骤

1. 在https://cloud.digitalocean.com/ 注册并启用双因素认证，账单归项目所有者管理。
2. 创建项目mycoke-shared-backend，点击Create → Droplets。选择接近主要技师所在地的区域；美国东部团队可选纽约，其他区域先确认。
3. 系统选择Ubuntu 24.04 LTS x64；配置选择上述Bundled Basic Regular 24美元/月档，不添加托管数据库、负载均衡、额外Volume或GPU。
4. 开启Basic计划中的Daily Backups，核对新增7.20美元/月；按控制台实际显示的保留期确认恢复需求。
5. Authentication选择SSH Key。仅上传SSH公钥；私钥保存在自己设备，不能放到GitHub或聊天。主机名mycoke-api-01。
6. 检查结算配置，创建后会开始计费。在Billing设置35美元、40美元费用提醒（按控制台支持设置），提醒不等于自动停机或硬限额。
7. 配置Cloud Firewall：SSH 22仅允许运维来源IP；上线时开放TCP 80/443供HTTPS与证书验证。不要开放8000或5432。IPv4/IPv6规则按实际使用一致配置。
8. 将服务器公网IP和区域交给后端运维；这些不是秘密。凭证通过受控密钥授权或已有终端管理，不能粘贴root密码或私钥。

官方创建说明：https://docs.digitalocean.com/products/droplets/how-to/create/ 。

## 后端部署

后端运维安装受支持的Docker Engine和Compose插件，使用专用运维账户及SSH密钥。仓库PR验收合并后拉取main；合并前仅用于验收时固定PR提交SHA，不从未知分支部署生产。

```sh
git clone https://github.com/wilsonqiao9951-wq/warehouse-system.git
cd warehouse-system
cp deploy/production.env.example .env.production
chmod 600 .env.production
```

在服务器本地编辑.env.production：设置独立随机JWT_SECRET_KEY、URL安全POSTGRES_PASSWORD，以及真正的API_DOMAIN。当前没有新网页部署；仅API试运行可将FRONTEND_PUBLIC_URL设为API的HTTPS origin并将CORS_EXTRA_ORIGINS留空，正式接入浏览器前端再设置实际origin。Muse服务器端HTTP工具调用不要求浏览器CORS。

域名尚未选择：购买前向所有者报告域名完整名称、首年价、正常续费价、税费及自动续费设置，取得确认后再买。DNS将api子域名指向服务器，生效后才启动HTTPS。服务器的裸IP不是最终交给Muse的入口。

```sh
docker compose --env-file .env.production -f docker-compose.production.yml config --quiet
docker compose --env-file .env.production -f docker-compose.production.yml up -d --build
docker compose --env-file .env.production -f docker-compose.production.yml exec api python -m scripts.bootstrap_owner --email YOUR_EMAIL --organization YOUR_TEAM
```

Docker构建自动校验并恢复官网数据；启动运行Alembic迁移。bootstrap_owner只在空用户库创建第一个组织和管理员，密码交互输入；不能运行演示数据脚本初始化生产。随后管理员邀请各技师，分别注册设备并登录。

## 验收与Muse交接

验收公共manifest、guide和OpenAPI；未登录查询401。验证目录查询、Viper 3与Freestyle分机型库存、真实登录与设备领取、工单反馈、经理审核、同机型案例检索和跨组织隔离。不得把一次用料当成适配验证，不声称已训练模型。先邀请少量技师试用并观察内存/响应时间，再扩大使用；4GB配置不代表承诺无限并发。

每位Muse收到固定HTTPS API地址、docs/MUSE_PROJECT_BRIEF.md和个人登录接入方式。Muse必须具备HTTP请求工具，收到说明本身不能自动调用后端。通过工具的秘密存储保管个人凭证，不在项目介绍或共享提示词中写令牌。

## 备份和恢复

Daily Backups是整机备份，不能替代数据库逻辑备份。另设每日pg_dump和uploads备份，复制至另一受控设备或对象存储；开通额外收费存储前单独核价。备份不进GitHub。至少在上线前演练一次恢复，核对工单、组织隔离、库存及上传文件。现有Compose卷持久化不等于备份。

代码发布走PR验收；升级前备份，记录部署SHA。迁移后的数据库不能盲目用旧镜像回滚，必要时按已演练的恢复流程处理。本阶段单机部署存在单点故障，尚未配置高可用或自动故障切换。
