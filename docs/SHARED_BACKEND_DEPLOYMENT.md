# 共享后端部署交接

此文档是部署配置，不代表服务已经上线。GitHub目标仓库已确认为wilsonqiao9951-wq/warehouse-system。项目所有者已选择按每月35–40美元预算准备DigitalOcean部署，MacBook保留为测试备选。没有开通付费服务、购买域名、修改DNS或暴露本机网络。开通步骤见DIGITALOCEAN_SETUP.md。

## 从GitHub恢复官网数据

仓库根目录是后端部署目录，现有frontend保持原样。catalog-bundle/保存分块Base64编码的压缩官网数据及逐文件SHA256清单；它不包含生产工单、数据库、上传文件或秘密。首次本地运行和测试前执行`python -m scripts.install_catalog_bundle`。Docker构建自动执行同一脚本，校验分块、压缩包、每个文件及提取路径，遇到不同内容的既有文件会拒绝覆盖。解包后的JSON被Git忽略，避免大型JSON重复入库。

数据更新者在审核后的本地完整目录运行`python -m scripts.build_catalog_bundle`，一起提交分块、manifest及对应代码。不要直接编辑Base64文件。完整HTML审核快照仍在本地归档，仓库中证据包含来源URL和哈希；这里不声称可离线重放缺失的HTML快照。

## MacBook试运行方案

建议先以现有MacBook承载API、PostgreSQL和上传文件，通过Cloudflare Tunnel发布固定HTTPS API域名。每位技师的Muse使用同一API地址、各自账户和设备凭证；Muse必须支持实际HTTP工具调用，仅收到项目介绍不能自动获得调用能力。

Cloudflare官方说明发布应用无需付费Access套餐，正式公网应用需要Cloudflare管理的域名。主机租赁费为零；域名注册及续费按选定域名结算，购入前确认价格。电费、备份存储及未来生成式模型API费用另计，当前审核案例检索不调用生成式模型。来源：https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/ 和 https://developers.cloudflare.com/tunnel/get-started/ 。

此方案是部署建议，当前下方Compose仍是Caddy直连公网方案，不能直接当作Tunnel方案执行。Tunnel部署时应移除公网80/443映射，由cloudflared连接容器私网API或仅监听127.0.0.1的API；PostgreSQL不开放公网端口。隧道令牌、数据库密码和JWT密钥不进入GitHub。HTTP入口仍执行应用认证及组织隔离，不能把隧道地址当成授权。

上线前核实系统及运行时仍获得安全更新、持续接电、防休眠、重启后服务恢复、稳定网络、磁盘空间及硬件状态。内存建议16GB，8GB需通过实际负载测试再确定试用范围；这不是已验证的容量承诺。不要在未确认型号和系统前指定Docker Desktop版本或重装操作系统。

数据库及上传文件每日备份到另一设备或受控存储，上线前演练恢复；官网目录可从版本化数据重建。故障恢复目标和可接受停机时间由试运行结果确定。MacBook休眠、断网或故障会使所有技师失去服务，因此先小范围试用，负载及稳定性验收后再扩大。未来可将同一后端及数据库迁移至云主机，Muse保留固定API域名。

## 发布内容

发布后端代码、迁移、接口说明、测试及官网目录运行数据。不发布.env、数据库、上传文件、设备令牌、私有工单和客户记录。完整官网HTML审核快照体积较大，不进入服务镜像；审核保留在本地。数据目录是静态官网源，不是组织运营数据库。

## 运维配置

准备Docker主机及指向该主机的API域名。将deploy/production.env.example复制为本地.env.production，设置真正的域名、前端来源及随机JWT/数据库密码；不能保留占位值。数据库密码使用URL安全字符，因为会嵌入数据库URL。

执行：`docker compose --env-file .env.production -f docker-compose.production.yml up -d --build`。

API服务和数据库不直接发布主机端口，Caddy提供HTTPS。80/443用于域名证书和服务入口。PostgreSQL、上传文件、证书使用持久化卷，必须另设备份和恢复流程。此配置没有自动创建任何生产管理员或演示账户。

每位技师通过管理员邀请建立自己的账户、角色和组织；不同Muse仅共享API地址与项目说明，不共享凭证。服务器到服务器请求不依赖浏览器CORS；如果Muse在浏览器直接发请求，只配置真实前端来源，不使用开放所有来源替代身份验证。

验收：GET /api/muse、/api/muse/guide、/openapi.json；未登录POST /api/muse/query须401。使用各自技师身份验证工单查询、注册设备领取、结构化反馈提交、经理审核、同机型指导检索及跨组织隔离。

项目说明：docs/MUSE_PROJECT_BRIEF.md。后台协作流程：GitHub Issue描述需求，分支/PR交付，CI验收后部署。代码在GitHub不等于远程API已经运行。后续生成式模型或更复杂的排名策略须基于审核数据、独立评估及明确的运行配置，不从一次用料自动学习适配。

首次初始化：在只有运维人员可访问的终端执行`docker compose --env-file .env.production -f docker-compose.production.yml exec api python -m scripts.bootstrap_owner --email YOUR_EMAIL --organization YOUR_TEAM`。脚本交互输入并确认密码，数据库只存Argon2哈希；已有任何用户时拒绝再次初始化，不会覆盖现有账户。随后通过个人管理员登录及邀请建立技师账户。不要运行seed_demo来初始化生产环境。
