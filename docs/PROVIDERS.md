# 平台能力与官方依据

文档核查日期：2026-10-20。0.6.0 接入 Nebius、Crusoe、Lambda、AutoDL、UCloud、RunPod、DigitalOcean、Verda、EBCloud、Suanli、Azure 共 11 家官方公开来源。公开模式无需账号、密钥、充值、绑卡或购买 GPU 资源；AutoDL 需要本地浏览器依赖。可选 Lambda API / UCloud 认证分支仅有离线样本验证，没有成功的真实认证报价记录。

型号覆盖报告针对一次返回的 `prices`，只索引型号族，不合并价格或比较不同产品。它不代表所有厂商、地区和库存已经完整采集。见 [11 家来源 JSON](../examples/all-providers-2026-10-20.json) 和 [主流型号覆盖报告](../examples/mainstream-coverage-2026-10-20.json)。

2026-10-20 北京时间 16:01 的完整 CLI 采集成功返回 746 条记录（734 条数值价格、12 条联系销售），内置 34 个目标型号族均为 `priced`，零缺口。`priced` 表示有未标下线的数值挂牌，不保证库存、结算总价或每个显存及硬件变体均已覆盖；`extra_models` 的 26 个标签可能包含同系列保守别名，不能作为唯一物理型号数。

## RunPod：匿名 GPU Pods 目录

- 使用 [官方 GraphQL](https://api.runpod.io/graphql) 的只读 `gpuTypes` 查询，无 Authorization、API key 或登录态。来源标签 `official_public_api`，价格入口为 [官网价格页](https://www.runpod.io/pricing)。
- 2026-10-20 实抓 46 个完整 GPU 变体、68 条数值（Secure 31、Community 37）。包括 RTX 30 / 40 / 50 系列、RTX A / Ada / PRO、A100、H100、H200、B200、B300、MI300X、MI350X 等；数量仅描述该次采样。
- `securePrice` / `communityPrice` 必须配合 `secureCloud` / `communityCloud` 标志。禁用云层仍可能带占位金额，不能作为可用价格。空价、零价、未启用条目和 MIG / vGPU 分区不进入完整 GPU 结果。
- 两种云层分别保留 `cloud_tier`、`conditions.cloud_type`，金额为公开 USD / GPU / 小时目录价，存储另计。目录没有完整实例卡数和 CPU / RAM 配置，`gpu_count=null`，不推导整机价。
- 地区、可用区、国家及库存均未知，不能拿机房库存地点替代价格范围。支持型号、币种和计费方式筛选。
- [官方价格口径](https://www.runpod.io/articles/comparison/runpod-vs-replicate)明确目录价按 GPU 小时计；[GraphQL schema](https://graphql-spec.runpod.io/)定义目录字段；[Pods 计价说明](https://docs.runpod.io/pods/pricing)说明存储另计。

## DigitalOcean：公开 GPU Droplet 按需 / Spot 文档

- 解析 [官方 Droplet 计价文档](https://docs.digitalocean.com/products/droplets/details/pricing/) 中独立的 On-demand / Spot GPU 表，来源标签 `public_documentation`，不使用 API key。
- 2026-10-20 实抓 19 条（11 条按需、8 条 Spot），包含 NVIDIA H100 / H200 / B300 与 AMD MI300X / MI325X / MI350X / MI355X 等。GPU 型号和风冷 / 液冷变体保留原文，不为 RTX 4000 / 6000 补造 Ada 后缀。
- 表中金额是完整 GPU Droplet 计划的 USD 实例小时价；按官方明确的单卡 / `(8x)` 卡数分摊为 `gpu_hour`，保留 `instance_price`。支持型号、卡数、币种和计费方式筛选。
- 价格表没有可关联的显存、CPU、RAM、磁盘或价格地区 / 可用区；这些信息保持未知，不拼接其他可用性页来假定当前配置。
- Spot 是 public preview，公布价格可每日变化，实例可被回收；`availability=unknown`。`source_last_verified` 是文档核查日期，不是价格生效日或本库采样时间。
- [单卡 / 8 卡配置依据](https://docs.digitalocean.com/products/droplets/how-to/gpu/create/) · [USD 价格约定](https://docs.digitalocean.com/reference/api/reference/sizes/)

## Verda：公开 GPU 实例 USD / EUR 价目

- 使用 [官网价格页](https://verda.com/pricing) 的 USD / EUR 页面，仅采集 GPU instances 的 On-demand 区块中明确的 `1x` 配置。来源标签 `public_page`，无需账号或密钥。
- 2026-10-20 实抓 52 条：13 个资源配置 × 2 种计费模式 × 2 种币种，共 11 个型号；这是一次采样数量，来源变化时不会保证固定条数。
- 保留表内 On-demand / Spot 两列，`billing_mode=on_demand` / `spot`；CPU、Reserved、Confidential computing、Instant clusters、Serverless 和 Storage 价格不混入普通 GPU 实例。
- 单卡实例的整实例小时价保存在 `instance_price`，`price_basis=instance_total_allocated`；`amount` 按明确卡数分摊，`unit=gpu_hour`。USD / EUR 各自采样，不换汇。
- `resources` 保留 CPU 数量、RAM GB 和表列 GPU 显存；硬件的 SXM 版本单独保留。同型号不同 CPU / RAM 的配置不会按型号去重覆盖。
- 未公布价格地区、国家和可用区；不能由公司所在地推断。支持型号、卡数、币种和计费方式筛选。Spot 中断、购买条件和实时库存未验证，`availability=unknown`。

## EBCloud：明确选中的单卡 GPU 容器配置

- 解析 [英博云官网](https://www.ebcloud.com/) 的 GPU 容器卡片，来源 `public_page`。必须同时验证单选按钮的 `checked` 与 `is-selected`：计费为“按量付费”，数量为“1卡”；条件不一致即失败，不读取未选中的多卡或包月价。
- 2026-10-20 实抓 7 条，包含 RTX 4090D（2.06 CNY / 小时）、RTX 4090、H100、A100、A800、A40、A16。这是一次公开采样，不代表库存或结算价格。
- `product_type=gpu_container`，不是独立 VM 或模型推理执行价。显式单卡配置的整容器小时价保存在 `instance_price`，分摊为 `gpu_hour`；CPU 核数可为小数，内存 GB / GiB 与 DDR 类型保留原文。支持卡数筛选，但本采集器只返回默认单卡配置。
- 不套用免费试用时长、注册券或会员返券。地区、可用区、税费和库存未知，支持的存储类型也不等于套餐包含存储容量或整个物理板卡分配承诺。

## Suanli：云主机与弹性部署共用的 GPU 卡时费率

- [共绩算力官方价格区块](https://suanli.cn/product/serverless/)明确“弹性服务部署和云主机统一卡时定价，按秒收费”。采集器要求该局部声明存在，再解析本节 GPU 卡型 / 显存 / 价格三列表，来源 `public_page`。
- 2026-10-20 实抓 18 条 GPU 费率，含 L20 48GB（4.00 CNY / GPU / 小时）、H20、H100 / H200 / H800、A100 / A800、L40 / L40S、RTX 4090 / 5090 等。原表的昇腾 / 昆仑 NPU 和未验证的海光加速卡被排除；Moore Threads S4000 作为 GPU 保留。
- `product_type=gpu_compute`、`pricing_product_scope=["cloud_host", "serverless_deployment"]`，`price_basis=advertised_per_gpu`、`billing_meter=second`。这是统一 GPU 算力费率，不混入 Token 推理 API，也不虚构一个完整 VM 的总价。
- 当前表没有 CPU / RAM / 磁盘或每部署卡数，`resources={}`、`gpu_count=null`。地区、国家、可用区和库存未知；不支持这些位置维度或卡数筛选。

## Azure：两种固定 GPU VM 规格的匿名地区零售价

- 调用 [Microsoft Retail Prices API](https://prices.azure.com/api/retail/prices)，来源 `official_public_api`；[官方文档](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)明确不需要身份认证。不会请求订阅或部署资源。
- 仅支持 [NCasT4 v3](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ncast4v3-series) 的 `Standard_NC4as_T4_v3`（T4 16GB × 1，4 vCPU / 28 GiB RAM），以及 [ND GB200 v6](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nd-gb200-v6-series) 的 `Standard_ND128isr_NDR_GB200_v6`（GB200 192GB × 4，128 vCPU / 900 GiB RAM）。不代表 Azure 全规格目录。
- 2026-10-20 该固定范围实际返回 106 条，涉及 39 个 ARM 地区；数量随公开目录变化。仅采已生效、零阶梯起点的基础 VM Consumption 主计量，分开按需 / Spot，排除 Windows 授权产品、Low Priority、Dev/Test、预留和嵌套 savings-plan 价格。
- `instance_price` 保留 USD 整实例小时零售价，按文档卡数分摊为 `gpu_hour`；资源单位保留 GiB。每地区 / 模式选择已经生效的最新价格版本，保留 `effective_from` 和原始 Azure 计量标识。
- `regions` 来自返回的 `armRegionName`，支持地区与卡数筛选；可用区和国家筛选不支持。地区价格不证明配额、容量、订阅资格、税费或可购性，`availability=unknown`。分页仅访问固定官方端点和已核验的同范围偏移量。

## 尚未接入的来源

Vast.ai 官网引用的[公开价格 feed](https://storage.googleapis.com/vast-public-gpu-pricing/gpu-pricing-public.json)自身声明批量采集需要数据许可，本项目当前未接入该 feed。此说明只描述该来源声明和当前实现范围，不代表其他厂商或型号已全部覆盖。

## Lambda：默认免费公开页，可选认证 API

- 默认 `LAMBDA_SOURCE=public`，来源 [官方实例页](https://lambda.ai/instances)。不使用 API key；即使调用方已有 key，也不会自动发认证请求。
- 2026-10-20 公开页采样得到 4 张规格表、22 条价格，分别覆盖 8 / 4 / 2 / 1 卡实例。该数量仅描述一次采样，后续来源内容可能变化。
- 公开 `amount` 为挂牌 USD / GPU / 小时，`price_basis=advertised_per_gpu`、`account_scope=public_catalog`。`instance_price` 是单卡价乘卡数推导的实例价，不是独立来源报价。
- 保留 CPU、内存 GiB、磁盘 GiB / TiB 单位。国家、地区和可用区未在价格表明确，保持未知；挂牌不证明库存或可下单。
- 可用 `collect --lambda-source api` 或环境变量 `LAMBDA_SOURCE=api` 显式选择旧目录 API，才要求 `LAMBDA_API_KEY`。API 为 `GET https://cloud.lambda.ai/api/v1/instance-types`。
- API `price_cents_per_hour` 为整实例每小时美分价，除以 100 保存原价，再按 `specs.gpus` 分摊。`account_scope=authenticated_catalog`；该认证模式尚未完成真实账号联调。
- API `capacity_regions` 仅表达容量，不变成报价 `regions`；两种模式均不支持按地区、国家或可用区查询独立价格。
- [实例价格页](https://lambda.ai/instances) · [官方 API](https://docs.lambda.ai/api/cloud#listInstanceTypes) · [OpenAPI](https://docs.lambda.ai/api/cloud/spec.json)

## Nebius：公开文档已实现

- 使用公开 Compute 计价 Markdown，保留 GPU / CPU / RAM 分项、地区范围、币种和生效日期；当前无需 token。
- `POST https://api.nebius.cloud/billing/v1/calculator/estimate-batch` 是独立的认证配置估价分支，尚未实现，不能当成枚举所有价格的接口。
- 分项价格不能直接代表整机成本。Spot 的“From”是起价，采样不代表全天最低价。
- 地区可按明确来源范围筛选；信息不足时返回 `unverifiable_filter`。国家、可用区和实例卡数不能猜测。
- [Compute 计价](https://docs.nebius.com/compute/resources/pricing) · [估价 API](https://docs.nebius.com/rest-api/billing/v1/calculator/estimate-batch) · [价格页](https://nebius.com/prices)

## Crusoe：公开页面已实现

- 解析官网 GPU instances 区块，排除同页托管推理。无需账号凭据。
- Contact sales 金额为空；挂牌或起价不独立证明有库存或可自助购买，相关承诺与购买条件保留在说明中。
- 公开 VM 规格 / 容量接口不是当前公开价格目录。Billing 的单价也不能自动等同公共挂牌价。
- 当前来源未给逐地区价格，因此地区、国家、可用区、卡数筛选不可验证，不静默忽略。
- [价格页](https://www.crusoe.ai/cloud/pricing) · [API 文档](https://docs.crusoecloud.com/api/) · [OpenAPI](https://api.crusoecloud.com/v1/openapi.json) · [购买条件说明](https://support.crusoecloud.com/hc/en-us/articles/51755978765467-GPU-Quota-vs-Capacity-Understanding-On-Demand-and-Reserved-Instances-RIPA)

## UCloud：默认匿名促销月卡，可选认证 API

- 默认 `UCLOUD_SOURCE=public`；已有公私钥不会让采集器自动走认证。来源为 [GPU 官网](https://www.ucloud.cn/site/product/gpu.html) 使用的 [匿名前端 API](https://api.ucloud.cn/)，`ListPackage` / `ListActivity` / `GetActivityFlags` / `ListAllRegions` / `ListAllZones` 均为只读，不登录、充值、绑卡或创建资源。
- 当前覆盖官网明确引用的活动 `10204` / `10216` / `10248` 的完整 Package，新增 4090 48GB / 5090。2026-10-20 扩展后实抓 374 条，全部 `offline`。初次两活动采样为 358 条；[北京2 / 可用区B / T4S 单卡示例](../examples/ucloud-public-cn-bj2-2026-10-20.json)仍是当时 18 条历史筛选结果，不改写为新的全量采样。挂牌采集成功不代表可购。
- 当前均为 `DurationUnit=month`、`Durations=[1]`。`CurPrice` / `OriginalPrice` 的分值除以 100 得到 CNY 整套餐月价，按 GPU 数量分摊为 `gpu_month`；整套餐保留 `instance_month`，不除以 720，不当作标准按需小时价。
- 具体 Package 保留 CPU、内存、磁盘、带宽和 CPU 平台；不使用 `ListPackageGroup` 最低价代替具体配置。位置通过官方地区 / 可用区映射关联，支持 region / zone / GPU / 卡数筛选。国家筛选尚未开放，仍保留官方 `location.country_code`。
- `account_scope=public_promotion`。10204 / 10216 / 10248 活动元数据标为新老同享、限购分别 3 / 5 / 5，并保留优惠续费标志。但官网长租规则含新用户试用限制，与元数据不一致，所以资格一律未验证，不能承诺人人可买或未来续费价不变。
- `GetActivityFlags` 的下线状态和活动状态保留，未命中下线也仅 `unknown`；不据此推断有库存。官网活动规则及 [促销页](https://www.ucloud.cn/site/active/gpu.html)只作为资格说明，不将 9.9 元新客体验价混成通用月价。
- 旧 GPU 价格文档不作回退：`gpu/price.md` 当前 404；现行 [UHost 价格文档](https://github.com/UCloudDoc-Team/uhost/blob/master/price.md)不含 GPU 数值，旧 PDF 的 K80 / P40 / V100 月价不能冒充当前整实例价。[GPU 机型文档](https://github.com/UCloudDoc-Team/gpu/blob/master/type.md)给规格与可用区，不提供当前价格。
- 只有显式 `UCLOUD_SOURCE=api` / `--ucloud-source api` 才使用公私钥和完整目标调用 `GetUHostInstancePrice`。该分支 `account_scope=account_quote`，为 CNY 实例小时成本分摊，地区来自未回显核验的请求，不同于免费促销映射；尚未完成成功的真实认证询价。
- API 目标仍限 1–20 项、MachineType=G、Dynamic、Count=1；详见 [接入说明](DEPLOYMENT.md)。缺凭据 / 缺内联目标 / 无效内联目标分别返回 `missing_credentials` / `missing_price_targets` / `invalid_price_targets`；显式 FILE 设置失败仍是全局配置错误。
- [规格查询](https://docs.ucloud.cn/api/uhost-api/describe_available_instance_types) · [认证询价文档](https://docs.ucloud.cn/api/uhost-api/get_uhost_instance_price)

## AutoDL：免费公开首页普通 / 会员价

- 2026-10-20 北京时间 14:55 的完整 Python / CLI 采集成功返回 12 条普通价和 12 条会员价，与 Lambda 22 条共同构成 [46 条公开采样示例](../examples/lambda-autodl-2026-10-20.json)。数量仅描述该次采样，不代表库存。
- 来源为 [公开首页](https://www.autodl.com/home) 的“炼丹会员及租用价格”卡片，页面由 JavaScript 渲染。需可选 Playwright 及本地 Chromium，不需要登录、充值或绑卡。
- 在新的未登录浏览器上下文中依次读取“普通用户”和“炼丹会员”标签；不使用 `AUTODL_TOKEN`、保存的 storage state 或用户 Cookie。
- 每个 GPU 返回 ordinary / member 两种 `pricing_tier`，会员条目带 `membership_required=true` 和显示折扣 `membership_discount`。会员优惠条件保留，未购买或核验会员资格。
- 金额为公开 CNY / GPU / 小时挂牌，`account_scope=public_catalog`、`source_type=public_page`。首页未给实例卡数、机房、国家、可用区或 CPU / 内存 / 磁盘配置，均不猜测。
- 不支持地区、国家、可用区和卡数筛选；这些卡片不等于逐地区市场报价或实时库存。两标签结构、型号集合或显示折扣发生无法解释的变化时采集失败，不静默输出未验证价格。
- 市场页面的逐机器 / 地区报价另需联调；Pro / 弹性部署的已有资源 API 也不等于完整市场目录。当前免费路径不调用这些账号接口。
- [公开首页](https://www.autodl.com/home) · [市场](https://www.autodl.com/market/list) · [计费说明](https://www.autodl.com/docs/price/) · [Pro API](https://www.autodl.com/docs/instance_pro_api/) · [弹性部署 API](https://www.autodl.com/docs/esd_api_doc/)
