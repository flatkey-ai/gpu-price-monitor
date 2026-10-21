# 五个平台的来源、金额与地区证据

核查口径：2026-10-21，版本 0.13.0。推荐采集范围是原文档的 **Nebius、Lambda、Crusoe、AutoDL、UCloud**。全部由独立 Python 固定规则执行，不使用 Codex / LLM 或模型 API Key。另四家扩展适配器单独列在文末。

## 来源策略

| 策略 | 行为 |
| --- | --- |
| `api_preferred` | 五家推荐；Nebius 当前 Spot API 加官网 JSON 普通目录；Lambda 有 key 用 API、无 key 用公开页；无 key 的 UCloud 用 CompShare 匿名小时询价；Crusoe / AutoDL 用已说明的固定页面规则 |
| `api_only` | 仅允许价格 API；Nebius 只取 Spot，不加网站目录；Crusoe / AutoDL 页面来源明确报 `api_price_source_unavailable` |
| `configured` | 默认兼容行为，遵循各 `*_SOURCE`；Nebius public 保持旧文档 + Spot，UCloud public 保持旧 UHost 活动月包 |

有任一 UCloud 账号 key 时，接口优先策略要求完整签名 UHost 询价配置，不能悄悄改成 CompShare；显式 API 认证失败、请求失败、结构变化都直接报错。选择页面 / 网站 JSON 是请求前的规则，不是接口报错后的兜底。实际 `source_type`、`collection_method`、`selection_reason`、`fallback_reason` 随结果返回；混合源不冒充单一 API。

默认 `market` CSV 接受实际每 GPU 小时目录 / 地区价；`compact` 额外要求已核实国家和 region；`full` 为所有原始来源记录。起步价、组件、月包、询价、资格未核实的特殊优惠和明确下线项不进入有效小时表。库保留原币，不除以 720，不补造地区。

## Nebius：地区 Spot API 与普通目录 JSON

- 当前 Spot 接口：[GET /billing/v1alpha1/spot-price](https://api.nebius.cloud/billing/v1alpha1/spot-price)，[官方使用说明](https://docs.nebius.com/signup-billing/spot-prices)明确无需认证。
- 普通目录：[官网价格页](https://nebius.com/prices)。程序只从 HTML 的 `__NEXT_DATA__` 提取构建 ID、locale 和路由，随后 GET 同源 `/_next/data/{buildId}/en/prices.json`，从官方页面 JSON 中唯一的 `NVIDIA GPU Instances` 表解析价格；不从 HTML 取金额。

Spot 核对平台、SKU、region、金额、币种、`GPU hour`、`effectiveTime` 与 `snapshotTime`，完成分页 / 新鲜度校验后返回 `regional_quote`。国家使用[官方地区目录](https://docs.nebius.com/overview/regions)的明确映射；未知国家不猜。抢占式价格可随使用过程变化，源快照、生效时间、观察时间分别记录，历史图表和 From 不代替当前价。

网站 JSON 普通目录当前有五个确定小时费率：B300、B200、H200、H100、RTX PRO 6000；L40S Intel / AMD 是 From，GB300 / GB200 是 Contact us。程序严格核对 On-demand / GPU-hour 列和官网 USD 说明，保留 vCPU / RAM GB。页面没有声明 GPU 数量、单卡显存、云 API SKU 或价格地区，均不猜；其范围是 `unlocated_catalog`，可进 market，不能进 compact。L40S 起价和询价仅审计，不把 GPU 单独组件当整机价。

此来源标 `source_type=official_website_json`，保留实际 `api_endpoint`；**它是网站数据接口，不是正式稳定的云价格 API**，所以 `api_only` 不添加该目录。接口优先模式为 Spot + 网站 JSON；任何所选来源的结构改变都报错，不从文档或旧样本补金额。存储、税、账号最终费用和库存另有条件，公开每 GPU 费率不等于含所有附加服务的整机账单。

兼容模式另保留 [Compute 计价文档](https://docs.nebius.com/compute/resources/pricing)及官方 Markdown：生效日期、USD / ILS、GPU / CPU / RAM 分项和 From 均保留。文档供给范围单列 `coverage_regions` / `coverage_countries`，不当地区价；ILS 是客户计费辖区，不能据此认定机器部署在以色列。

可选账号估价需显式 `NEBIUS_SOURCE=api`、`NEBIUS_ACCESS_TOKEN` 和一个 targets FILE / JSON。调用 [Estimate Batch](https://docs.nebius.com/rest-api/billing/v1/calculator/estimate-batch)，先只读核验项目地区和受支持 GPU 预设，再核对完整资源 / 聚合单位 / 分项总价。它不是匿名全目录，合同报价也不是所有人可购的普通价；当前尚缺有效 token 的真实成功联调证据。

## Lambda：认证实例 API 或公开实例页

有 `LAMBDA_API_KEY` 时，接口优先使用 [GET instance-types](https://cloud.lambda.ai/api/v1/instance-types)，文档见 [List instance types](https://docs.lambda.ai/api/cloud#listInstanceTypes)与 [OpenAPI](https://docs.lambda.ai/api/cloud/spec.json)。`price_cents_per_hour / 100` 是整实例 USD 小时价，再除 `specs.gpus` 分摊每卡；保留原实例价和卡数。

无 key 时，接口优先在请求前选择[官网实例页](https://lambda.ai/instances)，Python HTTP / 固定 HTML 结构解析 1 / 2 / 4 / 8 卡配置、每 GPU 小时价及明确 CPU / RAM / 磁盘单位。API 和页面单位不同，不能把整机 API 总价直接与网页单卡价比较。

`regions_with_capacity_available` 仅存 `capacity_regions`，不填价格地区。API / 页面均没有依据证明独立逐地区费率，目录可进 market，不能仅凭容量进入 compact。显式 `LAMBDA_SOURCE=api` 或 api_only 缺 key 会报错；鉴权或结构错误不回退网页。公开页已有真实采集，认证目录仍缺有效 key 的成功联调证据。

## Crusoe：程序解析 GPU instances 区块

来源为[官方 GPU instances 价格页](https://www.crusoe.ai/cloud/pricing)。Python HTTP 取得 HTML 后，以固定区块标题、列和单位解析 GPU instances；只保留该区块的 On-demand / Current Spot / Contact sales，不混入相邻托管推理、微调、模型 API。数值单位为 USD / GPU / 小时；From 保持起价，Contact sales 为 null，不填零。

[官方 OpenAPI](https://api.crusoecloud.com/v1/openapi.json)重新核查显示，VM types 的 Type 是 CPU / GPU / 内存 / 磁盘等规格，没有价格字段。Billing `unit_price` 是账号费用，Reservations `price` 是客户合同，Foundry `price_per_hour` 是模型部署，均不能替代当前公共 VM 租价。[认证说明](https://docs.crusoecloud.com/reference/api/)的签名凭据不会使规格接口新增价格。

因此接口优先明确选择页面规则，api_only 返回 `api_price_source_unavailable`。公开表没有价格国家 / 地区和整实例卡数，保持未知；确定数值可进 market，不可伪造成多个国家价。没有数值的 Current Spot 栏不等于已抓到实时 Spot 报价；库存和可购资格未核实。

## AutoDL：固定 DOM 普通 / 会员价与授权市场

公开路径用新的未登录 Playwright / Chromium 上下文，以固定 DOM 规则读取[官网首页](https://www.autodl.com/home)普通用户和炼丹会员价格。`pricing_tier`、会员要求及来源折扣分别保留，CNY / GPU / 小时不混币种。公开路径不使用 token 或保存登录态。首页缺价格位置，可进入 market；缺国家 / region 不进入 compact。

`AUTODL_SOURCE=market` 与 `AUTODL_STORAGE_STATE_PATH` 可选用户授权[市场](https://www.autodl.com/market/list)。程序核验允许的只读请求、分页、重复项、页面金额 / 每小时单位，保留机器标识、来源地区和每卡资源。市场可用卡数不当实例选定卡数，国家 / zone 不猜。登录态过期报错，不回退首页，不租资源。

原文档的 [Pro API](https://www.autodl.com/docs/instance_pro_api/)和[弹性部署 API](https://www.autodl.com/docs/esd_api_doc/)面向已有实例 / 部署，不是全市场价目；`gpu_stock` 无价格。已有资源价格字段不能仅凭名称猜倍率，`AUTODL_TOKEN` 当前不用于公开 / 市场模式。api_only 拒绝此页面来源。首页已实采；授权市场仍缺有效会话成功联调证据。

## UCloud：CompShare 匿名小时询价与 UHost 分开

无 key 的 `api_preferred` / `api_only` 使用 UCloud 旗下**优云智算 CompShare**（[官方平台介绍](https://www.compshare.cn/docs/overview/platform/introduce)）：

- 配置发现：[CompShare 价格页](https://www.compshare.cn/price-list)。只解析该页同源前端目录的 GPU / CPU / 内存 / 磁盘 / ZoneId 等配置，丢弃嵌入金额，不执行任意 JS。
- 实时报价：匿名 `POST https://api.compshare.cn/`，JSON `Action=GetCompShareInstancePrice`；[官方询价文档](https://www.compshare.cn/docs/gpus/instance/getcompshareinstanceprice)。每条配置都发实际询价，不从前端目录复制价格。
- 位置证据：[官方 ZoneId 表](https://www.compshare.cn/docs/gpus/instance/describecompsharesupportzone)精确关联 Region / Zone，再与 UCloud 当前匿名国家 / 地区 / 可用区目录核对；未知 ZoneId 明确排除并保留诊断，不借用邻近区域。
- 计费单位：[官方计费说明](https://www.compshare.cn/docs/operation/charge/billdescribe)的 Postpay 小时口径。请求含 GPU 型号 / 数量、CPU、内存 MB、磁盘 GB、Region / Zone，`Quantity=1`。

只有 `RetCode=0`、响应 Action / ChargeType / 金额结构核验成功才返回。比较值采用 `OriginalPriceDetails` 的普通原价，实际返回的 Instance / SystemDisks / Disks / CompShareImage 分项求和，再按明确 GPU 数分摊为 CNY / GPU / 小时；整实例原值、分项与公式保留。`PriceDetails` 折后值的资格 / 会员身份未核实，仅作审计，不称通用会员价或最低价。

返回明确标记 `UCloud · CompShare（优云智算）` 产品线，与 UHost 不混用。位置是官方核验的**请求上下文**，响应没有独立回显位置；不是库存查询，也不证明全部型号、地区或配置可售。未请求的网络、共享存储、付费镜像等附加服务不在报价中。部分配置失败时检查逐项诊断，不能以零价或旧价凑齐。

CompShare 已取得真实匿名询价成功响应，不需要供应商 key、充值或创建 GPU。最终本批范围以 `provider_results` 的发现 / 请求 / 成功 / 失败及未核验区域诊断为准，不把目录配置数当成功报价数。

有任一 UCloud key 时，接口优先要求完整 `UCLOUD_PUBLIC_KEY`、`UCLOUD_PRIVATE_KEY` 和 targets，走原 [GetUHostInstancePrice](https://docs.ucloud.cn/api/uhost-api/get_uhost_instance_price)签名 UHost 询价；显式 `UCLOUD_SOURCE=api` 同样如此。只读核验完整位置 / GPU / CPU / RAM / 磁盘目标，私钥本地签名，不创建实例。该认证分支仍缺有效账号成功联调证据，失败不回退 CompShare。

兼容 `configured` + `UCLOUD_SOURCE=public` 保留旧 [UHost 活动](https://www.ucloud.cn/site/active/gpu.html)匿名月套餐。月金额和下线状态只保留审计，不除以 720，不当当前每小时租价。

## 历史证据与另四家扩展

日期样本只证明当时来源，不作现价、可购承诺或运行时回退，见 [examples](../examples/README.md)。原先只数严格地区项的历史 CSV 不能代表 0.13 market 的目录覆盖。

| 扩展适配器 | 来源与边界 |
| --- | --- |
| RunPod | [匿名 GraphQL](https://api.runpod.io/graphql) GPU Pods 目录，Secure / Community 分开；不把云档位当会员，不补地区，不采 Serverless |
| DigitalOcean | [GPU Droplet 定价文档](https://docs.digitalocean.com/products/droplets/details/pricing/)，明确整实例卡数分摊；按需 / Spot 与硬件变体分开 |
| Verda | [USD](https://verda.com/pricing?currency=usd) / [EUR](https://verda.com/pricing?currency=eur)分别读取，JSON-LD 核对整机单位，不在库内换汇，不猜部署国家 |
| Azure | [Retail Prices API](https://prices.azure.com/api/retail/prices)，限四个已核验 GPU SKU，生效地区费率和官方国家映射；不代表全 SKU、订阅库存或配额 |

`--providers all` 会包含这四家；原文档五家模板不会运行它们。
