# 五个平台的来源、金额与地区证据

核查口径：公开来源样本保留各自采集日期；Lambda 控制台会话和 0.18.0 Nebius 账号目录均于 2026-10-22 完成独立 Python HTTP 实采。推荐采集范围是原文档的 **Nebius、Lambda、Crusoe、AutoDL、UCloud**。全部由独立 Python 固定规则执行，不使用 Codex / LLM 或模型 API Key。另四家扩展适配器单独列在文末。

## 来源策略

| 策略 | 行为 |
| --- | --- |
| `api_preferred` | 五家推荐；Nebius 默认 Spot API 加官网 JSON，也可显式选账号 `catalog_api`；Lambda 显式 `console` 用保存会话读内部 JSON，否则有 key 用 API、无 key 用公开页；AutoDL 显式 `market` 直接读市场 JSON；无 key 的 UCloud 用 CompShare 匿名小时询价；Crusoe及 AutoDL 首页用已说明的固定页面规则 |
| `api_only` | 仅允许价格 API，包含显式选择的 Lambda console 与 AutoDL market `official_internal_api`；Nebius 公开来源只取 Spot，显式 `catalog_api` / `api` 可用账号估价，不加网站目录；Crusoe / AutoDL 首页页面来源明确报 `api_price_source_unavailable` |
| `configured` | 默认兼容行为，遵循各 `*_SOURCE`；Nebius public 保持旧文档 + Spot，UCloud public 保持旧 UHost 活动月包 |

有任一 UCloud 账号 key 时，接口优先策略选择签名 UHost 询价；完整目录模式自动发现配置，标准模式要求显式目标，不能悄悄改成 CompShare；显式 API 认证失败、请求失败、结构变化都直接报错。选择页面 / 网站 JSON 是请求前的规则，不是接口报错后的兜底。实际 `source_type`、`collection_method`、`selection_reason`、`fallback_reason` 随结果返回；混合源不冒充单一 API。

默认 `market` CSV 接受实际每 GPU 小时目录 / 地区价；`compact` 额外要求已核实国家和 region；`full` 为所有原始来源记录。起步价、组件、月包、询价、资格未核实的特殊优惠和明确下线项不进入有效小时表。库保留原币，不除以 720，不补造地区。

## Nebius：地区 Spot、账号按需估价与公开目录

- 当前 Spot 接口：[GET /billing/v1alpha1/spot-price](https://api.nebius.cloud/billing/v1alpha1/spot-price)，[官方使用说明](https://docs.nebius.com/signup-billing/spot-prices)明确无需认证。
- 普通目录：[官网价格页](https://nebius.com/prices)。程序只从 HTML 的 `__NEXT_DATA__` 提取构建 ID、locale 和路由，随后 GET 同源 `/_next/data/{buildId}/en/prices.json`，从官方页面 JSON 中唯一的 `NVIDIA GPU Instances` 表解析价格；不从 HTML 取金额。

Spot 核对平台、SKU、region、金额、币种、`GPU hour`、`effectiveTime` 与 `snapshotTime`，完成分页 / 新鲜度校验后返回 `regional_quote`。国家使用[官方地区目录](https://docs.nebius.com/overview/regions)的明确映射；未知国家不猜。抢占式价格可随使用过程变化，源快照、生效时间、观察时间分别记录，历史图表和 From 不代替当前价。

网站 JSON 普通目录当前有五个确定小时费率：B300、B200、H200、H100、RTX PRO 6000；L40S Intel / AMD 是 From，GB300 / GB200 是 Contact us。程序严格核对 On-demand / GPU-hour 列和官网 USD 说明，保留 vCPU / RAM GB。页面没有声明 GPU 数量、单卡显存、云 API SKU 或价格地区，均不猜；其范围是 `unlocated_catalog`，可进 market，不能进 compact。L40S 起价和询价仅审计，不把 GPU 单独组件当整机价。

此来源标 `source_type=official_website_json`，保留实际 `api_endpoint`；**它是网站数据接口，不是正式稳定的云价格 API**，所以 `api_only` 不添加该目录。接口优先模式为 Spot + 网站 JSON；任何所选来源的结构改变都报错，不从文档或旧样本补金额。存储、税、账号最终费用和库存另有条件，公开每 GPU 费率不等于含所有附加服务的整机账单。

兼容模式另保留 [Compute 计价文档](https://docs.nebius.com/compute/resources/pricing)及官方 Markdown：生效日期、USD / ILS、GPU / CPU / RAM 分项和 From 均保留。文档供给范围单列 `coverage_regions` / `coverage_countries`，不当地区价；ILS 是客户计费辖区，不能据此认定机器部署在以色列。

0.18.0 的账号目录使用显式 `NEBIUS_SOURCE=catalog_api` 与 `NEBIUS_ACCESS_TOKEN`，不需要手填 targets。程序只读调用官方 [tenants](https://api.nebius.cloud/iam/v2/tenants)、[projects](https://api.nebius.cloud/iam/v2/projects)、[platforms](https://api.nebius.cloud/compute/v1/platforms)，遍历账号可访问的已有项目及 GPU preset，再逐项调用 [Estimate Batch](https://docs.nebius.com/rest-api/billing/v1/calculator/estimate-batch)。价格地区取实际项目地区并核对官方国家目录，不把平台供给范围复制成报价。分页、重复项、硬件身份、币种、单位、SKU 分项及总额均校验；单项失败留诊断，不能用零价或旧值补齐。

**2026-10-22 14:21:49（北京时间）Python 账号实采**发现并询价 37 个 GPU preset，得到 **36 条有效计算报价，覆盖 9 地区、6 国家**，另排除 117 个 CPU preset。有效型号为 B200、B300、H100、H200、L40S、RTX PRO 6000。GB300 已发现，但 API 计算费为零，返回 `compute_tariff_unavailable` 并计入未定价配置；SSD 有金额也不能把盘费当 GPU 费。结果为 `partial`，不宣称全部配置成功。该次未创建项目、VM、磁盘或付款方式；可访问项目范围不等于所有账号合同、配额或库存，多个地区同价也不证明全球统一。

账号目录主价为 VM 的 GPU / CPU / RAM 计算资源小时费，再按明确卡数分摊。`instance_price.scope=compute_resources_only`；配置的 40 GiB SSD 用同批独立磁盘估价另列 `storage_quote`，`full_configuration_price` 保留含盘总额和分项，CSV 条件说明另计费用。实际对照中，仅把嵌套启动盘从 40 改为 80 GiB 不改变 VM 计算费；增加独立磁盘请求才得到额外 SSD 费用。程序要求计算与磁盘 SKU 非空且不重叠，并拒绝重复磁盘计费。网络等未请求服务不在内。

显存使用当前平台 API 的 GB 字段，RAM 的 GiB 独立保留。B300 API 返回每卡 **270 GB**，与[官方产品](https://nebius.com/self-service)及[官方实测文章](https://nebius.com/blog/posts/nebius-weka-shared-kv-cache-benchmark-hgx-b300)一致；旧 VM types 文档的 288 GB 差异留作证据，不猜原因。GB300 的 279 GB / NVL72 与[官方产品](https://nebius.com/compute/gb300)及官方 preset 示例核对，但规格存在不等于已取得有效价格。[认证、配置与证据边界](nebius-crusoe.md)。

指定目标模式仍使用 `NEBIUS_SOURCE=api`、`NEBIUS_ACCESS_TOKEN` 和一个 `NEBIUS_PRICE_TARGETS_FILE` / `NEBIUS_PRICE_TARGETS_JSON`；先核验项目地区和 preset，再询全部请求资源，主金额保持完整请求总额语义。它与自动目录的计算主价口径不同，不是匿名全目录，也不保证所有合同价可读。

## Lambda：认证实例 API、公开页或免费登录态 JSON

0.16 已进一步核实标准控制台的地区价格流程：同一 SKU 在其所列可选地区共用目录价。`price_applicability` 保留具体国家/中文地区/代码和证据，支持国家、地区筛选；无可选地区的规格不进入主表，但完整目录保留。每轮匿名核对当前控制台脚本指纹，HTML 只用于版本证据，不作价格源；价格仍取三个 JSON GET。[详细规则与实采样本](lambda-console.md)。

有 `LAMBDA_API_KEY` 时，接口优先使用 [GET instance-types](https://cloud.lambda.ai/api/v1/instance-types)，文档见 [List instance types](https://docs.lambda.ai/api/cloud#listInstanceTypes)与 [OpenAPI](https://docs.lambda.ai/api/cloud/spec.json)。`price_cents_per_hour / 100` 是整实例 USD 小时价，再除 `specs.gpus` 分摊每卡；保留原实例价和卡数。

无 key 时，接口优先在请求前选择[官网实例页](https://lambda.ai/instances)，Python HTTP / 固定 HTML 结构解析 1 / 2 / 4 / 8 卡配置、每 GPU 小时价及明确 CPU / RAM / 磁盘单位。API 和页面单位不同，不能把整机 API 总价直接与网页单卡价比较。

`regions_with_capacity_available` 仅存 `capacity_regions`，不填价格地区。API / 页面均没有依据证明独立逐地区费率，目录可进 market，不能仅凭容量进入 compact。选择公开密钥 API（显式 `LAMBDA_SOURCE=api` 或非 console 的 api_only）而缺 key 会报错；鉴权或结构错误不回退网页。公开页已有真实采集，API key 分支仍缺有效 key 的成功联调证据。

0.15.0 增加显式 `LAMBDA_SOURCE=console` + `LAMBDA_STORAGE_STATE_PATH`：只 GET 控制台内部实例、预留集群和地区 JSON，使用调用者自己的登录 Cookie。**2026-10-22 用户手动登录并保存会话后，独立 Python CLI / HTTP 的三个 GET 全部实采成功，返回 36 条 GPU 报价：22 个按需实例规格、14 个预留集群配置（6 个型号/费率档）**，另审计排除 2 个 CPU 规格并保留 18 条地区元数据。无需创建 GPU 或绑定付款方式。`api_only` 允许这个 JSON 源，但清楚标为 `official_internal_api`，不能当稳定公开 API。18 条地区只是容量元数据，不能当 18 个地区分别报价；集群采用前端每 GPU 小时字段，冲突旧字段只留审计，期限与最终购买条件仍未核实，不宣称账号全部价格已获取。[操作步骤和边界](lambda-console.md)。

## Crusoe：程序解析 GPU instances 区块

来源为[官方 GPU instances 价格页](https://www.crusoe.ai/cloud/pricing)。Python HTTP 取得 HTML 后，以固定区块标题、列和单位解析 GPU instances；只保留该区块的 On-demand / Current Spot / Contact sales，不混入相邻托管推理、微调、模型 API。数值单位为 USD / GPU / 小时；From 保持起价，Contact sales 为 null，不填零。

[官方 OpenAPI](https://api.crusoecloud.com/v1/openapi.json)重新核查显示，VM types 的 Type 是 CPU / GPU / 内存 / 磁盘等规格，没有价格字段。Billing `unit_price` 是账号费用，Reservations `price` 是客户合同，Foundry `price_per_hour` 是模型部署，均不能替代当前公共 VM 租价。[认证说明](https://docs.crusoecloud.com/reference/api/)的签名凭据不会使规格接口新增价格。

因此接口优先明确选择页面规则，api_only 返回 `api_price_source_unavailable`。公开表没有价格国家 / 地区和整实例卡数，保持未知；确定数值可进 market，不可伪造成多个国家价。没有数值的 Current Spot 栏不等于已抓到实时 Spot 报价；库存和可购资格未核实。

## AutoDL：授权市场 JSON 与兼容首页

公开路径用新的未登录 Playwright / Chromium 上下文，以固定 DOM 规则读取[官网首页](https://www.autodl.com/home)普通用户和炼丹会员价格。`pricing_tier`、会员要求及来源折扣分别保留，CNY / GPU / 小时不混币种。公开路径不使用 token 或保存登录态。首页缺价格位置，可进入 market；缺国家 / region 不进入 compact。

`AUTODL_SOURCE=market` 与 `AUTODL_STORAGE_STATE_PATH` 选择用户授权[市场](https://www.autodl.com/market/list)的 `POST /api/v1/user/machine/list` JSON。普通浏览器人工登录后，用仓库内的本地导出页保存最小会话；采集时无需浏览器，支持 `api_only`，不会访问钱包、已有实例或订单接口。程序核验明确 `payg` SKU、普通 / 会员档位、总数和唯一 ID，保留每卡 CPU / 内存及价格地区。已于 2026-10-22 通过 Python / CLI 实测，完整批次 6,558 条双档小时价。[详细配置和金额精度](autodl-market.md)。

原文档的 [Pro API](https://www.autodl.com/docs/instance_pro_api/)和[弹性部署 API](https://www.autodl.com/docs/esd_api_doc/)面向已有实例 / 部署，不是该市场接口；`gpu_stock` 无价格。`AUTODL_TOKEN` 当前不用于公开 / 市场模式。市场 JSON 的国家缺口单独保留：只有当前地区名称及数据中心与官方地名证据一致的地区身份才补国家，zone 不猜。官网“已租完”保留为 `out_of_stock`，不冒充下线；缺国家的原价留 JSON，正式完整国家地区表用 `compact`。

## UCloud：CompShare 匿名小时询价与 UHost 分开

无 key 的 `api_preferred` / `api_only` 使用 UCloud 旗下**优云智算 CompShare**（[官方平台介绍](https://www.compshare.cn/docs/overview/platform/introduce)）：

- 配置发现：[CompShare 价格页](https://www.compshare.cn/price-list)。只解析该页同源前端目录的 GPU / CPU / 内存 / 磁盘 / ZoneId 等配置，丢弃嵌入金额，不执行任意 JS。
- 实时报价：匿名 `POST https://api.compshare.cn/`，JSON `Action=GetCompShareInstancePrice`；[官方询价文档](https://www.compshare.cn/docs/gpus/instance/getcompshareinstanceprice)。每条配置都发实际询价，不从前端目录复制价格。
- 位置证据：[官方 ZoneId 表](https://www.compshare.cn/docs/gpus/instance/describecompsharesupportzone)精确关联 Region / Zone，再与 UCloud 当前匿名国家 / 地区 / 可用区目录核对；未知 ZoneId 明确排除并保留诊断，不借用邻近区域。
- 计费单位：[官方计费说明](https://www.compshare.cn/docs/operation/charge/billdescribe)的 Postpay 小时口径。请求含 GPU 型号 / 数量、CPU、内存 MB、磁盘 GB、Region / Zone，`Quantity=1`。

只有 `RetCode=0`、响应 Action / ChargeType / 金额结构核验成功才返回。比较值采用 `OriginalPriceDetails` 的普通原价，实际返回的 Instance / SystemDisks / Disks / CompShareImage 分项求和，再按明确 GPU 数分摊为 CNY / GPU / 小时；整实例原值、分项与公式保留。`PriceDetails` 折后值的资格 / 会员身份未核实，仅作审计，不称通用会员价或最低价。

返回明确标记 `UCloud · CompShare（优云智算）` 产品线，与 UHost 不混用。位置是官方核验的**请求上下文**，响应没有独立回显位置；不是库存查询，也不证明全部型号、地区或配置可售。未请求的网络、共享存储、付费镜像等附加服务不在报价中。部分配置失败时检查逐项诊断，不能以零价或旧价凑齐。

CompShare 已取得真实匿名询价成功响应，不需要供应商 key、充值或创建 GPU。最终本批范围以 `provider_results` 的发现 / 请求 / 成功 / 失败及未核验区域诊断为准，不把目录配置数当成功报价数。

有任一 UCloud key 时，接口优先要求完整 `UCLOUD_PUBLIC_KEY`、`UCLOUD_PRIVATE_KEY`，使用 [GetUHostInstancePrice](https://docs.ucloud.cn/api/uhost-api/get_uhost_instance_price) 签名 UHost 询价；显式 `UCLOUD_SOURCE=api` 同样如此。`catalog_scope=complete` 每轮通过官方只读 API 自动发现账号地区和 GPU 配置，再逐项询价，不需要 targets 或浏览器 Cookie；标准模式仍要求显式 targets。私钥本地签名，不创建实例。认证失败不回退 CompShare；真实联调状态见 [签名目录验收记录](ucloud-api-catalog.md)。

兼容 `configured` + `UCLOUD_SOURCE=public` 保留旧 [UHost 活动](https://www.ucloud.cn/site/active/gpu.html)匿名月套餐。月金额和下线状态只保留审计，不除以 720，不当当前每小时租价。

## RunPod：目录价与按机房最低起价

匿名官方 GraphQL 读取整卡 Pods 的 Secure / Community 按需目录。两种云类型不是会员关系，目录价没有地区绑定。`--catalog-scope complete` 另外读取官方数据中心目录，并按国家信息明确的机房查询一张 GPU 的 `lowestPrice`；返回值保留为 `starting_at`，不是具体机器配置的确定报价，不能加入确定价最低榜。CPU / RAM 最小值不能拼成虚构机器。只有洲级地点的机房明确列为国家证据缺口，不猜代码对应国家。详见 [RunPod](runpod.md)。

## 历史证据与其他扩展

日期样本只证明当时来源，不作现价、可购承诺或运行时回退，见 [examples](../examples/README.md)。原先只数严格地区项的历史 CSV 不能代表 0.13 market 的目录覆盖。

| 扩展适配器 | 来源与边界 |
| --- | --- |
| DigitalOcean | [GPU Droplet 定价文档](https://docs.digitalocean.com/products/droplets/details/pricing/)，明确整实例卡数分摊；按需 / Spot 与硬件变体分开 |
| Verda | [USD](https://verda.com/pricing?currency=usd) / [EUR](https://verda.com/pricing?currency=eur)分别读取普通、机密实例与明确卡数的即时集群；保留页面价格及 JSON-LD 口径差异，不在库内换汇，不猜部署国家 |
| Azure | [Retail Prices API](https://prices.azure.com/api/retail/prices)，26 个已核验整卡 GPU SKU，包含 T4、A10、A100、H100、H200、V100、RTX PRO 6000、V710、MI300X、GB200 的明确规格及地区费率；不代表全 SKU、订阅库存或配额，见[范围说明](azure.md) |

`--providers all` 会包含这些扩展及 RunPod；原文档五家模板不会运行它们。

### UCloud 无浏览器签名目录采集

`UCLOUD_SOURCE=api` 与 `catalog_scope=complete` 使用签名 `GetRegion`、`DescribeAvailableInstanceTypes` 和分页 `DescribeImage` 发现当前账号 GPU 配置，再对每个精确配置请求 `GetUHostInstancePrice`。配置公私钥及已授权项目 ID 即可，采集不读取或续期浏览器 Cookie。仅需四个只读动作。详见 [目录范围与真实验收步骤](ucloud-api-catalog.md)；合成响应测试与真实授权验收分别记录。

Vast 逐型号搜索只对限流、网络或超时失败做冷却后的串行重试，最多两轮（或调用者更低的重试预算）。已成功的型号不会重复抓取；记录实际重试请求数，耗尽预算仍保留明确缺口。受响应上限约束，不宣称抓到全市场机器。
