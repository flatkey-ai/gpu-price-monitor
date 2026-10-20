# 返回数据口径与契约

仅 UCloud 认证 API 报价另带 `target_index`：对应调用方 UCloud 目标数组（内联 JSON 或显式 FILE）的零起始下标，用于在过滤后关联原始目标。项目 ID 不写入报价返回；不同项目即使硬件配置相同，也可通过下标区分。

`collect_prices` 返回标准 Python `dict`，可使用 `json.dumps` 序列化；`collect` CLI 的 stdout 为 JSON。接口不写数据库，也不自动混入历史缓存。

## 顶层结构

| 字段 | 语义 |
| --- | --- |
| `schema_version` | 当前为 `1` |
| `status` | `success`、`partial` 或 `failed` |
| `collected_at` | 本次采集时间，UTC |
| `prices` | 本次成功解析并符合筛选的报价数组 |
| `provider_results` | 每来源状态、筛选应用情况和结构化错误 |
| `coverage` | 可选：`include_coverage=True` / CLI `--coverage` 请求的本次型号覆盖报告 |

一个来源失败时保留其他来源的成功报价。筛选后无匹配是可解释的正常结果，不能仅以空 `prices` 判断失败；检查每来源状态。未知 / 未实现来源与无匹配不同，未实现来源返回 `not_implemented`。

CLI 退出码 `0` 为全部来源成功（含无匹配）、`2` 为部分来源失败、`1` 为全部失败或配置无效。Python 调用方通过返回状态处理来源失败；配置格式等调用错误应按 API 校验行为处理。

## 型号覆盖报告

`coverage` 的 `scope=returned_quotes` 表示只检查本次筛选后的 `prices`，不额外请求网络。`models` 按内置主流 GPU 目标名单返回，其他识别到的型号保存在 `extra_models`。它仅按型号族建立报价索引，原始显存、SXM / PCIe / NVL 等变体、产品类型和购买条件仍保留；不合并 VM、容器、算力分项或促销价格，也不计算最低价。`extra_models` 可能含保守命名的同系列变体，不能当作额外唯一物理型号数。

每个型号含 `gpu_model`、`status`、`quote_count`、`numeric_quote_count`、`providers`、`currencies`、`units`、`quote_indices`。`quote_indices` 是顶层 `prices` 的零起始下标，供调用方查看具体变体、配置、模式和条件。

`totals` 包含 `requested_models`、`priced_models`、`unavailable_listings_only_models`、`contact_sales_only_models`、`not_found_models`，以及 `returned_quotes`、`matched_quotes`、`extra_models`。`collection_status` 另保留采集整体状态，避免来源失败时将型号缺失误当作全市场没有报价。

| 覆盖状态 | 含义 |
| --- | --- |
| `priced` | 至少一条数值挂牌未标记 `offline` / `ended` / `upcoming`；仍不证明库存、购买资格或价格包含整机全部成本 |
| `unavailable_listings_only` | 仅有下线、结束或尚未开始的数值挂牌 |
| `contact_sales_only` | 只有无数值的联系销售记录 |
| `not_found` | 本次返回数据中没有该型号；可能受所选来源、筛选或来源失败影响，不表示全市场不销售 |

报告不换汇，不将月价与小时价排序比较，不将询价或缺失转换为零元，也不改变 `status` / `provider_results` 的错误语义。调用方应同时检查报价、来源状态和覆盖状态。

## 报价语义

`prices` 中每条报价包含以下字段。未知信息保留 `null`、空数组或明确的 `unspecified`，不从卡名、地区库存或访问位置猜测：

| 字段 | 规则 |
| --- | --- |
| `provider`、`product_type` | 来源名称；当前产品类型包含 `gpu_instance`、EBCloud 的 `gpu_container`、Suanli 的 `gpu_compute` |
| `gpu_model`、`raw_name`、`raw_sku` | GPU 名称、来源原始名称及 SKU；未知 SKU 为 `null` |
| `gpu_variant`、`vram_gb`、`gpu_count` | 硬件版本、显存和实例 GPU 数量；来源不明确时为 `null` |
| `amount`、`currency`、`unit` | 原币十进制字符串或询价 `null`；单位为 `gpu_hour` 或 UCloud 公开促销的 `gpu_month`，不换汇 |
| `billing_mode` | 可确认的计费方式，如 `on_demand`、公开促销 `monthly` |
| `price_basis` | `advertised_per_gpu`、`gpu_component`、`starting_price` 或整实例分摊 `instance_total_allocated` |
| `quote_status` | `quoted`、`starting_at` 或 `contact_sales` |
| `regions`、`geographic_scope` | 地区列表；公开来源范围为 `regions` / `unspecified`，UCloud 公开套餐为 `zone`，认证 API 为请求上下文 `requested_zone` |
| `account_scope` | 普通公开目录为 `public_catalog`；Lambda API 为 `authenticated_catalog`，UCloud 公开促销为 `public_promotion`，认证 API 为 `account_quote` |
| `tax_scope` | 来源可确认时 `excluded`，未知时 `unspecified`；未知值不能视作含税 |
| `observed_at` | UTC 采样时间 |
| `effective_from`、`effective_until` | 可确认的 ISO 生效日期，未知为 `null` |
| `source_url`、`source_type` | 官方来源和类型；网页为 `public_page`，Nebius / DigitalOcean 为 `public_documentation`，RunPod / UCloud 公开促销 / Azure 为 `official_public_api`；Lambda API 为 `official_api`，UCloud API 为 `official_quote_api` |
| `availability` | 公开页面 / UCloud API 为 `unknown`；UCloud 公开促销保留下线 / 活动状态；仅 Lambda API 按容量报告为 `capacity_reported` / `no_capacity_reported`，不保证下单成功 |
| `notes` | 价格限制、承诺期、购买条件等来源说明数组 |

Nebius L40S 等拆分报价可额外返回 `components`，说明资源分项。Lambda 默认公开页的 `amount` 是来源挂牌每卡小时价，`price_basis=advertised_per_gpu`；`instance_price` 为该价格乘明确卡数后的派生整实例小时价，不是第二个独立报价。Lambda API / UCloud 则从来源整实例原价除以卡数，使用 `instance_total_allocated`。这些价格属于完整资源包，不等于裸 GPU 单独售价。

`instance_price` 包含十进制字符串 `amount`、原币 `currency`（如 USD、EUR、CNY）和 `unit=instance_hour` / `instance_month`。UCloud 还可包含白名单金额字段 `original_amount`、`details`、`original_details`；不返回原始账号响应。UCloud `normalization` 明确记录整实例金额按卡数分摊的公式、保留 12 位小数及 `ROUND_HALF_UP` 舍入；公开接口另含分值除以 100 的转换。

Nebius GPU / CPU / RAM 分项价格不等于整实例租价。Crusoe 的 Contact sales 不能生成数值；公开挂牌不代表库存充足或支持自助购买。起价与确定报价需要分别处理，不能无条件进入确定价比较。

若来源提供多组历史或未来生效价格，不能把任意数字当当前价格；保留可确认的适用日期。未采样的历史价格不能由本库还原。

## 筛选

Python `filters` 接受数组字段：`gpu_models`、`currencies`、`billing_modes`、`regions`、`compute_countries`、`sales_countries`、`zones`、`gpu_counts`。

| 筛选 | Nebius | Crusoe | Lambda | AutoDL | UCloud |
| --- | --- | --- | --- | --- | --- |
| GPU 型号、币种、计费方式 | 支持 | 支持 | 支持 | 支持 | 支持 |
| 地区 | 依据来源范围核对 | 不支持 | 不支持 | 不支持 | 公开按官方映射；API 按请求 target |
| 可用区 | 不支持 | 不支持 | 不支持 | 不支持 | 公开按官方映射；API 按请求 target |
| 卡数 | 不支持 | 不支持 | 支持 | 不支持 | 支持 |
| 服务 / 销售国家 | 无可靠映射 | 无可靠映射 | 无可靠映射 | 无可靠映射 | 未开放筛选；公开保留官方 country_code 元数据 |

| 筛选 | RunPod | DigitalOcean | Verda |
| --- | --- | --- | --- |
| GPU 型号、币种、计费方式 | 支持 | 支持 | 支持 |
| 卡数 | 不支持，目录未给实例数量 | 支持，明确单卡 / 8 卡 | 支持，硬件列明确数量 |
| 地区、可用区、服务 / 销售国家 | 不支持 | 不支持 | 不支持 |

| 筛选 | EBCloud | Suanli | Azure |
| --- | --- | --- | --- |
| GPU 型号、币种、计费方式 | 支持 | 支持 | 支持 |
| 地区 | 不支持 | 不支持 | 按返回的 ARM 地区核对 |
| 卡数 | 支持；当前只采默认 1 卡 | 不支持；每部署卡数未知 | 支持；固定两规格为 1 / 4 卡 |
| 可用区、服务 / 销售国家 | 不支持 | 不支持 | 不支持 |

配置格式支持字段不代表来源支持应用。返回的每来源信息记录请求条件及应用 / 不支持情况，不静默忽略。对来源未说明地区的价格不能标注为指定地区报价，也不能由币种、网页语言或访问 IP 猜测国家。

若 Nebius 的相关报价缺少地区说明，地区筛选返回 `unverifiable_filter`，而不是把未知地区当成确定的 `no_matches`。来源不提供该维度时返回 `unsupported_filter`。

Lambda 默认公开页来自 `https://lambda.ai/instances`，实例卡数由 8 / 4 / 2 / 1 卡表明确给出。`regions=[]`、`geographic_scope=unspecified`，不支持地区、国家或可用区筛选；挂牌不证明库存。`tax_scope=excluded`，USD 币种依据以 `currency_source_url` 保留。

公开页 `resources` 使用 `vcpus`、`memory_gib` 和 `storage`；`storage` 包含十进制字符串 `amount`、原始 `unit`（`TiB` 或 `GiB`）及 `type=SSD`。不把 TiB 的数值当作 GiB，也不直接改成十进制 GB。

显式选择 `LAMBDA_SOURCE=api` 后，`capacity_regions` 才来自认证目录的容量响应；它不是逐地区价格，不能填入报价 `regions`。API `instance_price` 保留 USD 实例小时原价，`amount` 为按卡数分摊成本，`resources` 使用 `vcpus`、`memory_gib`、`storage_gib`、`architecture`。默认公开模式即使已有 API key 也不请求该目录。

仅 UCloud API 的 `instance_price` 为 CNY 整实例小时价，`amount` 为按请求 GPU 数量分摊的值。`resources` 使用 `vcpu_count`、`memory_mb`、`disks` 保留请求资源；`requested_configuration` 保留去掉 `ProjectId` 的请求配置。地区 / 可用区来自请求 target，`geographic_scope=requested_zone`；询价响应不回显这些条件，不能视为独立核验，更不证明有库存或规格可售。

## RunPod GPU Pods 目录

`amount` 直接保留官方 `securePrice` / `communityPrice` 的 USD / GPU / 小时目录金额，`price_basis=advertised_per_gpu`。每个云层独立返回，`cloud_tier=secure` / `community`；`conditions` 保存 `cloud_type=secure_cloud` / `community_cloud` 和 `rate_type=catalog`。

只有相应 `secureCloud` / `communityCloud=true` 且有正数价格时才返回。禁用云层的占位金额、空价、零价、未启用类型及 MIG / vGPU 分区不作为完整 GPU 报价。`gpu_count=null`，没有 `instance_price`，不为目录价虚构整实例配置。

`raw_sku` 保留官方 GPU 类型 ID，`raw_name` 为展示名称，`vram_gb` 为目录显存；`gpu_model` 去除独立的 SXM / PCIe / NVL 版本和重复显存，版本保存为 `gpu_variant`。`regions=[]`、`zones=[]`、`geographic_scope=unspecified`、`availability=unknown`。存储另计，不能把 GPU 目录费率当结算总价。

## DigitalOcean GPU Droplet

`instance_price` 保存官方计划的 USD 实例小时原价，`amount` 按明确的 1 / 8 卡数量分摊，`price_basis=instance_total_allocated`。`billing_mode` 分开为 `on_demand` / `spot`，Spot 另带 `preview=true`。同卡不同风冷 / 液冷变体保存在 `gpu_variant`。

`source_last_verified` 是来源文档写明的核查日期，不能替代 `observed_at` 或 `effective_from`。来源表未给出显存和 CPU / RAM / 存储，`vram_gb=null`、`resources={}`；地区与库存同样未知。不能从其他可用性页面拼接成地区特定报价。

## Verda GPU 实例

USD 与 EUR 页面分别采样，不从一个币种换算另一个。普通 GPU instances 的 On-demand 表提供 `Price` 和 `Spot price`，对应 `billing_mode=on_demand` / `spot`。网页 JSON-LD 的小时实例单位与表格金额交叉核对。

`instance_price` 保留整实例小时金额，`gpu_count` 来自硬件列明确的 `1x` 等数量；`amount` 按卡数分摊，`price_basis=instance_total_allocated`，`normalization` 说明公式及 12 位小数、`ROUND_HALF_UP` 规则。`resources` 包含 `cpu_count`、`ram_gb`、`listed_gpu_vram_gb`；显存和 SXM 版本保留原文。

`raw_sku` 包含硬件、CPU、RAM 和表列显存，区分相同 GPU 的不同资源配置；不能只按型号去重。地区、国家、可用区、税费和库存未验证，保持明确的未知状态。

## UCloud 公开促销月卡

默认 `UCLOUD_SOURCE=public`。官网匿名 `ListPackage` 返回活动 10204 / 10216 / 10248 的具体套餐，`CurPrice` 和 `OriginalPrice` 以分计；当前只接受 `DurationUnit=month`、`Durations=[1]`。

`amount` 为 CNY 整套餐月价按 `gpu_count` 分摊，`unit=gpu_month`、`billing_mode=monthly`、`price_basis=instance_total_allocated`。`instance_price` 保留 `amount`、`original_amount`、`currency=CNY`、`unit=instance_month`。**不除以 720 或假定一个月的使用小时数。** 它不是标准按需单价。

`regions` / `zones` 各为已核对的单一 ID，`geographic_scope=zone`。`location` 保存官方 `country_code`、`region`、`zone`、`region_name`、`zone_name`。本版本未开放国家筛选，保留元数据不代表 `--country` 已支持。`resources` 保留 `vcpu_count`、`memory_mb`、`disk_gb`、`disk_type`、`bandwidth_mbps`、`cpu_platform` 等完整套餐配置。

`account_scope=public_promotion`、`source_type=official_public_api`。每个具体 Package × Zone 独立返回，不能用同组最低价复制为不同带宽、资源或位置报价。促销身份和套餐配置应参与调用方的比较 / 去重条件。

`promotion` 保留 `activity_id`、`title`、`only_new_users`、`purchase_limit`、`user_types`、`activity_state`、`activity_status`、`duration`、`duration_unit`、`discount_allow_renew`、`eligibility_verified` 及来源提供的活动起止时间。10204 / 10216 / 10248 元数据表示新老同享、限购 3 / 5 / 5，但前端资格规则存在文案冲突，所以 `eligibility_verified=false`。优惠续费标志不保证未来价格或购买资格。

`availability` 为 `offline`、`ended`、`upcoming` 或 `unknown`，无 `available` 承诺。下线仍可保留挂牌作为证据，不表示能下单。活动元数据、网页规则和实际结算资格需分别核对。

## EBCloud 单卡 GPU 容器

`product_type=gpu_container`。`selected_configuration` 保留来源“按量付费＋1卡”的明确选择；`gpu_count=1`、`amount=instance_price.amount`，后者单位为 `instance_hour`。`normalization` 记录按卡数分摊，不能将未选中的多卡或包年包月选项外推成报价。

`resources.cpu_cores` 保留十进制字符串（可含小数），`memory` 保留金额、GB / GiB 和 DDR 类型。支持存储类型与计算网络仅描述页面配置，不推导附送容量。免费试用、券和会员返券不抵扣公开小时价。

## Suanli 共享 GPU 算力费率

`product_type=gpu_compute`，`pricing_product_scope=["cloud_host", "serverless_deployment"]` 保留官方统一适用范围。只有本节明确声明云主机与弹性部署共用卡时价，才返回 `advertised_per_gpu` / `gpu_hour`；`billing_meter=second` 保留按秒计费条件，不转成 Token API 价格。

每部署的卡数未知，`gpu_count=null`，不生成 `instance_price`。当前表未提供 CPU / RAM / 磁盘，`resources={}`。NPU 和未核验的其他加速卡不归入 GPU 费率。原始名称、显存和 `gpu_vendor` 保留，地区与库存未知。

## Azure 固定规格地区零售价

仅覆盖 `Standard_NC4as_T4_v3` 与 `Standard_ND128isr_NDR_GB200_v6`，文档分别明确 1 张 T4 / 4 张 GB200。`resources` 保留 `vcpus` / `memory_gib`；`hardware_source_url` 可追溯对应官方规格。

`instance_price` 为 USD 整 VM 小时零售价，按卡数分摊为 `gpu_hour`，`normalization.rounding=exact`。`regions` 为单一 `armRegionName`；`location.region_name` 是来源展示名，不等于已核验的国家或可用区。

每 ARM 地区 / `on_demand` 或 `spot` 选择最新已生效 Consumption 主计量，`effective_from` 保留来源生效时间，未来版本不进入当前结果。`azure_meter` 保留计量 / 产品 / SKU 标识，`conditions.product_scope=base_vm_without_windows_license`。Windows 授权产品、Low Priority、Dev/Test、预留及嵌套 savings-plan 价格排除；管理磁盘、网络等费用另计，挂牌不代表容量或订阅资格。

## AutoDL 普通价与会员价

AutoDL 公开首页每个 GPU 卡片返回两条价目，按标签区分：

| 字段 | 含义 |
| --- | --- |
| `pricing_tier` | `ordinary`（普通用户）或 `member`（炼丹会员） |
| `membership_required` | 会员价为 `true`，普通价为 `false` |
| `membership_discount` | 会员显示折扣的十进制比例，如 `0.9`；普通价为 `null` |

`amount` 为对应标签直接展示的 CNY / GPU / 小时价，`billing_mode=on_demand`，`price_basis=advertised_per_gpu`。会员金额不是普通价，不能不带条件地进入同一比较。库只读取公开宣传的会员价，不购买或验证会员资格。

`gpu_count=null`，`regions=[]`，`geographic_scope=unspecified`、`availability=unknown`；来源没有逐机器配置或实时库存，不能把 GPU 卡片数量当作可租数量。未公布 CPU、内存、磁盘或生效日期时不补造。普通 / 会员两种身份需一并保留，避免调用方按同型号去重时覆盖价格条件。

## 错误和调用方责任

错误区分未实现、未支持筛选、网络 / 超时、来源请求、页面 / 文档解析及其他可识别来源失败。仅可选 Lambda API / UCloud API 缺凭据返回 `missing_credentials`；UCloud 内联目标缺失或无效分别返回 `missing_price_targets` / `invalid_price_targets`。FILE 读取 / 校验失败为全局 `ConfigurationError`，在来源采集前终止；公开免费路径不需要凭据。诊断不得回显 API key、Cookie、签名、会话内容或原始账号响应。

库不把错误表示成零元，不自动使用上次成功报价。换汇、数据过期、历史合并、价格变化、数据库和上传都由调用方处理；调用方应保存来源、单位和采样时刻，避免丢失价格语义。
