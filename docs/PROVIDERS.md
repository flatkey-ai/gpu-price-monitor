# 平台能力与官方依据

核查与实现口径：2026-10-21，版本 0.9.0。当前支持 **Nebius、Lambda、Crusoe、AutoDL、UCloud、RunPod、DigitalOcean、Verda、Azure** 九家，`all` 选择这九家。默认公开模式不需要账号、密钥、充值、绑卡或购买 GPU；AutoDL 需本地 Playwright / Chromium。认证分支与授权市场另行显式选择，不因已有密钥而自动启用。

本页说明来源、单位和地理证据；实际条数随来源变化。**2026-10-21 15:12:56（北京时间）九家公开实抓成功，共 833 条**：Nebius 36、Crusoe 24、Lambda 22、UCloud 374、AutoDL 24、RunPod 68、DigitalOcean 19、Verda 52、Azure 214。574 条有已核验国家关联，588 条有价格地区 / 可用区，其中 UCloud 374 条全部下线；36 条仅平台覆盖，209 条未定位目录。Azure 214 条覆盖 45 个价格地区，其中 14 条国家未知。以上不是全地域可购库存。 见 [九家公开采样](../examples/nine-providers-2026-10-21.json)。原 [五家采样](../examples/five-providers-2026-10-21.json) 是北京时间 2026-10-21 14:35 的历史证据：共 480 条，其中 374 条 UCloud 中国月包已下线，36 条 Nebius 仅平台覆盖，其余 70 条没有价格地区。采集成功不等于当前可购或覆盖所有国家。

## 地理与金额共同约定

- `compute_countries` 表示价格所绑定的部署国家，使用 ISO 两字母代码。币种、销售税区、公司所在地、容量地区和机房覆盖不能单独证明这个字段。
- `regions` / `zones` 保留来源代码。`price_scope` 区分未知位置目录、平台覆盖、地区 / 可用区报价及请求配置询价。`geographic_coverage` 只汇总本批返回的证据，不是库存报告。
- 地区、国家和可用区组合必须在同一报价内成立。来源不支持的维度返回 `unsupported_filter`；支持但证据不足返回 `unverifiable_filter`。
- 金额字符串、币种、GPU / 整实例单位、配置、折扣和生效日期保留。按月不折算为假定小时数；未知金额不填 0；`observed_at` 是抓取时刻，不是价格生效日。

## Nebius：公开组件价与可选配置估价

默认 `NEBIUS_SOURCE=public`，读取 [Compute 计价文档](https://docs.nebius.com/compute/resources/pricing) 的 [官方 Markdown](https://docs.nebius.com/compute/resources/pricing.md)。解析 GPU / CPU / RAM 分项、USD / ILS、按需 / Spot 及来源明确的生效日期；存在多个日期区间时按采样日期选择，未知或冲突结构会失败。GPU 分项不等于整机费用；Spot 的 From 保留为起价。

公开文档里的地区表示平台可用范围，返回 `price_scope=platform_coverage`。可按来源覆盖代码筛选，但不能据此宣称芬兰、美国等国家各有独立报价。ILS 的计价或税务适用对象也不等于 GPU 部署在以色列。公开路径不推断国家、可用区或实例卡数。

可选 `NEBIUS_SOURCE=api` 已实现 [Estimate Batch](https://docs.nebius.com/rest-api/billing/v1/calculator/estimate-batch)：

1. 提供 `NEBIUS_ACCESS_TOKEN` 与 `NEBIUS_PRICE_TARGETS_FILE` / `NEBIUS_PRICE_TARGETS_JSON` 之一，参见 [targets 模板](../configs/nebius-targets.example.json)。单批 1–20 个目标、JSON 不超过 256 KiB。
2. 目标指定项目、地区、国家、GPU 型号 / 卡数和完整 `resource_specs`，含 VM 平台 / 预设及启动盘；可包含支持的附加磁盘 / 文件系统估价。只发送 calculator 参数，不创建资源。
3. 通过只读 `GET /iam/v2/projects/{project_id}` 核对项目地区，并依 [官方地区表](https://docs.nebius.com/overview/regions) 校验国家。平台 / 预设按 [官方 VM 类型](https://docs.nebius.com/compute/virtual-machines/types) 的明确映射核对 GPU 型号、显存、卡数和地区；未知平台拒绝，不由调用者随意贴型号。当前支持 H100、H200、B200、B300、RTX PRO 6000、L40S 对应的已核验平台；实际列表以适配器的 `SUPPORTED_PLATFORMS` 为准。暂不接受不能单独核验的 zone。
4. 使用 Bearer access token 请求固定官方 endpoint `POST https://api.nebius.cloud/billing/v1/calculator/estimate-batch`；调用方负责 token 续期。
5. `currency=usd/ils`、`aggregation_units=hour/month` 原样核对响应。整批配置成本及资源分项保留，再按明确 GPU 数量分摊为 `gpu_hour` / `gpu_month`；`price_basis=instance_total_allocated`。月聚合不表示包月承诺。默认 `offer_types=[]`；显式 `CONTRACT_PRICE` 保留账号合同条件，不能当公共最低价。

配置估价为 `source_type=official_quote_api`、账号专属 `account_scope` 与 `requested_region_quote`，不是匿名全目录枚举。目标、响应资源关联、GPU 卡数、完整聚合单位和分项合计均需通过验证；可变范围或不完整配置不输出可疑价格。

**验证边界：14 项合成离线测试通过；尚未使用有效 token 完成真实成功询价。** 官方 [OpenAPI](https://api.nebius.cloud/openapi.json) 和配置模板用于实现核对，不作为实际可售规格或账号报价的证据。

## Lambda：公开实例页与可选认证目录

默认 `LAMBDA_SOURCE=public`，读取 [官方实例页](https://lambda.ai/instances)。本次 22 条保留 1 / 2 / 4 / 8 卡配置。网页单位是 USD / GPU / 小时，`price_basis=advertised_per_gpu`；`instance_price` 是该金额乘卡数的推导值，保留推导标记。CPU、内存 GiB、磁盘 GiB / TiB 按表中配置保存，不混用十进制 GB。

`LAMBDA_SOURCE=api` 与 `LAMBDA_API_KEY` 显式选择 `GET https://cloud.lambda.ai/api/v1/instance-types`。`price_cents_per_hour / 100` 是**整实例**美元小时价，再除 `specs.gpus` 得每 GPU 分摊价；不能直接与网页单卡价比较。认证结果标 `account_scope=authenticated_catalog`。

API 的 `regions_with_capacity_available` 保存为 `capacity_regions`，不填入价格 `regions`。公开表和该 API 均未给独立逐地区价格，国家 / 地区 / zone 筛选不支持；没有容量不是零元或永久下架。可选 API 已有离线解析测试，尚未完成真实有效账号成功联调。

官方依据：[原价格入口](https://lambda.ai/pricing) · [List instance types](https://docs.lambda.ai/api/cloud#listInstanceTypes) · [OpenAPI](https://docs.lambda.ai/api/cloud/spec.json)。

## Crusoe：只读取 GPU instances

来源为 [官网 GPU instances pricing](https://www.crusoe.ai/cloud/pricing#gpu-instances)。仅解析这一独立区块，保留 On-demand 与 Current Spot；相邻模型 API、托管推理和微调费用不混入。本次共 24 条，其中 Contact sales 数值为空；显存未公布的询价项保持未知。From / Starting at 保留起价语义，GPU 型号和硬件变体不合并。

数值单位为公开 USD / GPU / 小时。当前表没有实例卡数、CPU / RAM / 磁盘和具体价格地区，保持未知；不由平台机房目录推断国家。公开挂牌、Spot 及询价项均不保证实时容量或购买资格。

按原 Word 核查结论，尚未确认枚举当前公共 GPU VM 租价的官方 API。`/projects/{project_id}/compute/vms/types` 是规格目录；Billing 的 cost / unit_price 是账号费用；`SelfServeFlavor.price_per_hour` 属于托管模型部署，都不能替代公共 VM 报价。当前没有将这些接口包装成免费价格接口。

官方依据：[API 文档](https://docs.crusoecloud.com/api/) · [OpenAPI](https://api.crusoecloud.com/v1/openapi.json) · [Quota / Capacity 与购买条件](https://support.crusoecloud.com/hc/en-us/articles/51755978765467-GPU-Quota-vs-Capacity-Understanding-On-Demand-and-Reserved-Instances-RIPA)。

## AutoDL：免费首页与授权地区市场分开

默认 `AUTODL_SOURCE=public`，以新的未登录浏览器上下文读取 [公开首页](https://www.autodl.com/home)。本次普通用户 / 炼丹会员各 12 条，共 24 条 CNY / GPU / 小时挂牌。普通、会员分别设置 `pricing_tier`，会员要求和页面折扣另存，不假设调用者有会员资格。首页没有报价地区、国家、zone、实例卡数或 CPU / 内存 / 磁盘，均保持未知；不等于逐机器市场或实时库存。公开路径忽略 token 与保存会话。

可选 `AUTODL_SOURCE=market` 已实现读取用户授权登录态的 [算力市场](https://www.autodl.com/market/list)，需 `AUTODL_STORAGE_STATE_PATH`：

- 调用者自行保存并维护登录态，例如 `python -m playwright codegen --save-storage=playwright/.auth/autodl.storage-state.json https://www.autodl.com/market/list`，手动登录后关闭窗口。状态文件含凭据，不提交或分享。
- 仅访问默认按量市场的允许只读请求与分页，校验页数、总数、重复项及页面 / API 元数据。页面显示的货币、金额、每小时单位为价格依据，不猜私有 API 原始金额的倍率。
- 保留机器标识、来源 `region_sign` / 地区名、GPU / 显存、单卡资源与已显示的会员条件。金额是挂牌每 GPU 价，市场可用 GPU 数不当成整实例卡数，国家与 zone 不推断。
- 地区代码可筛选，价格标 `regional_quote`；租用按钮和剩余 GPU 只说明观察时状态，不保证后续库存。失效登录态返回 `login_required` / `storage_state_invalid`，不回退成首页价，不输出不完整分页。

**验证边界：8 项合成市场测试通过，尚未使用有效登录态成功抓取真实市场。** 当前 `AUTODL_TOKEN` 保留但两种模式均不使用。

原 Word 提到的 [Pro API](https://www.autodl.com/docs/instance_pro_api/) 与 [弹性部署 API](https://www.autodl.com/docs/esd_api_doc/) 面向已有 `instance_uuid` / `deployment_uuid`；并非全市场价目。Pro 的 `payg_price` / `origin_pay_price` 不因名称就假定单位；弹性部署 `price` 的“元 × 1000”口径不能套用其他接口。`gpu_stock` 没有返回价格。当前不调用这些已有资源接口，也不保存 SSH 等访问数据。另见 [计费说明](https://www.autodl.com/docs/price/)。

## UCloud：匿名月包与账号配置小时询价分开

默认 `UCLOUD_SOURCE=public`，匿名读取 [GPU 官网](https://www.ucloud.cn/site/product/gpu.html) 引用的 [官方前端 API](https://api.ucloud.cn/)：`ListPackage`、`ListActivity`、`GetActivityFlags`、`ListAllRegions`、`ListAllZones`，均为只读。采集活动 10204 / 10216 / 10248 的具体套餐，不用套餐组最低价代替完整配置。

本次 374 条均为中国月卡且 `availability=offline`。`DurationUnit=month`、`Durations=[1]`，`CurPrice` / `OriginalPrice` 的分值除 100 为 CNY 整套餐月价，再按卡数分摊 `gpu_month`，整套餐保留 `instance_month`；不除 720。CPU、内存、磁盘、带宽与 CPU 平台保留。

国家 / region / zone 来自官方目录关联，当前已支持 `--country CN` 及地区 / zone / 卡数筛选。活动限购、优惠续费及资格说明单列；接口元数据与促销页面资格文案有差异时保持未验证。下线状态不得丢弃，非下线标志也不等于现货。不将 [活动页](https://www.ucloud.cn/site/active/gpu.html) 的限量新客体验价当通用月价。

可选 `UCLOUD_SOURCE=api` 调用 [GetUHostInstancePrice](https://docs.ucloud.cn/api/uhost-api/get_uhost_instance_price)，需公私钥与 [完整目标](../configs/ucloud-targets.example.json)。当前限定 1–20 项、JSON ≤128 KiB、`MachineType=G`、`ChargeType=Dynamic`、`Count=1`；指定地区、zone、GPU、CPU、内存 MB 与磁盘 GB。私钥只在本地生成签名，不作为请求参数发送。仅 `RetCode=0` 且金额 / 计费方式通过校验才返回报价。

正常采集入口每次为 API 请求加载官方地区 / zone 目录，核对地区、zone 归属及国家；不是根据请求币种猜国家。返回 CNY 整实例小时价及分摊 `gpu_hour`，`account_scope=account_quote`、`requested_zone_quote`，折前价及明细分别保留。它仍是完整配置、账号条件下的询价，响应本身没有独立回显确认全部部署位置；不代表全地区枚举或现货。

**验证边界：公开月包已真实匿名采集；可选认证询价有离线测试，尚未完成有效账号真实成功询价。** 旧 GPU 月价 PDF 和失效价格 Markdown 不作为当前价格回退。官方规格枚举不保证各地区均可售。

官方依据：[规格查询](https://docs.ucloud.cn/api/uhost-api/describe_available_instance_types) · [签名算法](https://docs.ucloud.cn/api/summary/signature) · [询价文档](https://docs.ucloud.cn/api/uhost-api/get_uhost_instance_price)。


## RunPod：匿名 GPU Pods 目录，云档位分开

只读请求 [官方 GraphQL](https://api.runpod.io/graphql) 的 `gpuTypes`，结构依据 [官方 API 规范](https://graphql-spec.runpod.io/)，展示入口为 [定价页](https://www.runpod.io/pricing)。仅收集 GPU Pods 的按需 `securePrice` / `communityPrice`，通过 `secureCloud` / `communityCloud` 判断该档是否启用；不读取账号、执行 mutation、租用实例或混入 Serverless、预留、Spot。

`cloud_tier=secure|community` 与 `conditions.cloud_type` 标明两种云服务，不能省掉档位后将不同价误认为官网不一致，也不能当作普通价 / 会员价。2026-10-21 独立实抓中，B300 Secure / Community 为 USD 8.99 / 6.94，H200 SXM 为 USD 5.29 / 3.59；这些数值是当时观察证据，不作固定回退。

金额为 USD / GPU / 小时，保留显存与明确硬件变体。目录没有报价绑定的实例 GPU 数量、CPU / RAM、国家 / 地区 / zone，保持未知；不将机房列表或最大卡数当作一条完整实例配置。禁用云档位、空值 / 零值未报价、MIG / vGPU 分区不作为完整 GPU 报价。云档位可用标志不证明库存，返回 `availability=unknown`。

## DigitalOcean：公开整实例按需与 Spot 价

来源 [官方 Droplet 定价文档](https://docs.digitalocean.com/products/droplets/details/pricing/)，仅读取 On-Demand GPU Droplet Pricing 与 Spot GPU Droplet Pricing 两个明确表，不把 CPU、Contract 联系销售或其他产品混入数值报价。无需 API token。

官网表价是完整 Droplet **整实例小时价**；按明确 `(8x)` 或官方 [单卡 / 八卡配置说明](https://docs.digitalocean.com/products/droplets/how-to/gpu/create/) 分摊为每 GPU 小时价，保留 `instance_price` 和 `gpu_count`。例如 H200 八卡整机 USD 35.76/h，对应每 GPU USD 4.47/h。币种按官方 USD 定义，不由美元符号猜成其他币种。

Spot 与按需分开，Spot 可能每日改变并被回收；B300 风冷 / 液冷报价当前出现在 Spot 表，不伪造成普通按需价。表中未给价格地区、显存、CPU / RAM / 磁盘，保持未知，不拼接其他页面机房范围。`source_last_verified` 是文档标注的核验日期，既不是本次 `observed_at`，也不当作价格生效日期。

## Verda：USD / EUR 两张原币整实例表

分别读取 [USD 定价页](https://verda.com/pricing?currency=usd) 与 [EUR 定价页](https://verda.com/pricing?currency=eur)，校验页面当前选中币种。仅收集 GPU instances → On-demand 表内的 Price / Spot price 列；Instant clusters、Confidential computing、CPU、Serverless 和 Reserved 另有条款，不混用。

页面表格和官方 JSON-LD 一起核对金额、币种及“hourly instance price”单位。保留 1 / 2 / 4 / 8 卡数、整实例价和 CPU / RAM / 显存，再按卡数分摊为 `gpu_hour`，分摊精度记录在 `normalization`。USD / EUR 各是供应商原始挂牌，不能称为库换汇。Spot 与按需保留不同中断和容量条件。

当前表没有绑定价格国家、地区、zone；供应商总部或平台机房覆盖不能将这些报价变成芬兰 / 欧洲地区价。库存、税、另计存储网络和账号折扣未核验。

## Azure：固定 GPU SKU 的公开逐地区零售价

读取无需密钥的 [Azure Retail Prices API](https://prices.azure.com/api/retail/prices)，官方口径见 [API 文档](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)。当前严格限定四个已核验 GPU VM SKU：`Standard_NC4as_T4_v3`（1 × T4 16 GB）、`Standard_ND128isr_NDR_GB200_v6`（4 × GB200，每卡 192 GB）、`Standard_NC40ads_H100_v5`（1 × H100 NVL 94 GB）、`Standard_NC24ads_A100_v4`（1 × A100 PCIe 80 GB），不是 Azure 全 GPU SKU 抓取器。

只接受对应基础 VM 产品、USD、`Consumption`、主计量地区、`1 Hour`、已到生效时间的按需 / Spot 条目；保留并按生效时间选择地区费率。不将 Windows 许可、Low Priority、Dev/Test、预留或嵌套 Savings Plan 费率合并。所有分页必须完成、连续且限定官方地址与原查询范围，否则来源失败，不悄悄返回前几页。

`retailPrice` 是完整 VM 小时价，按 [T4 规格](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ncast4v3-series)、[GB200 规格](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nd-gb200-v6-series)、[H100 规格](https://learn.microsoft.com/en-us/azure/virtual-machines/ncads-h100-v5)、[A100 规格](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nca100v4-series) 的明确 GPU 数量分摊；保留原实例价、规格和 meter 信息。磁盘、网络等其他服务另计。`armRegionName` / `location` 来自价格响应，可按 region 筛选；部署国家依据 [官方地区目录](https://learn.microsoft.com/en-us/azure/reliability/regions-list) 中已核验的 58 个 programmatic name 映射，记录 `location_source`；未知新地区保持空国家，不由前缀、币种或地区名称猜测。支持已核验国家和地区筛选，当前不推断可用区。四 SKU 本次返回 214 条、45 个地区、22 个已映射国家 / 地区代码；14 条 edge / government / Jio 等地区保留未知国家。全局国家筛选遇到相关未知国家记录会返回 `unverifiable_filter`，可结合明确地区筛选，例如 US + eastus，不静默排除缺证据报价。零售目录不证明订阅配额、容量、税或可购性。
