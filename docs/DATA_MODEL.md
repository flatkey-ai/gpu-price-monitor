# 返回数据口径与契约

UCloud 报价另带 `target_index`：对应调用方 UCloud 目标数组（内联 JSON 或显式 FILE）的零起始下标，用于在过滤后关联原始目标。项目 ID 不写入报价返回；不同项目即使硬件配置相同，也可通过下标区分。

`collect_prices` 返回标准 Python `dict`，可使用 `json.dumps` 序列化；`collect` CLI 的 stdout 为 JSON。接口不写数据库，也不自动混入历史缓存。

## 顶层结构

| 字段 | 语义 |
| --- | --- |
| `schema_version` | 当前为 `1` |
| `status` | `success`、`partial` 或 `failed` |
| `collected_at` | 本次采集时间，UTC |
| `prices` | 本次成功解析并符合筛选的报价数组 |
| `provider_results` | 每来源状态、筛选应用情况和结构化错误 |

一个来源失败时保留其他来源的成功报价。筛选后无匹配是可解释的正常结果，不能仅以空 `prices` 判断失败；检查每来源状态。未知 / 未实现来源与无匹配不同，未实现来源返回 `not_implemented`。

CLI 退出码 `0` 为全部来源成功（含无匹配）、`2` 为部分来源失败、`1` 为全部失败或配置无效。Python 调用方通过返回状态处理来源失败；配置格式等调用错误应按 API 校验行为处理。

## 报价语义

`prices` 中每条报价包含以下字段。未知信息保留 `null`、空数组或明确的 `unspecified`，不从卡名、地区库存或访问位置猜测：

| 字段 | 规则 |
| --- | --- |
| `provider`、`product_type` | 来源名称；当前产品类型为 `gpu_instance` |
| `gpu_model`、`raw_name`、`raw_sku` | GPU 名称、来源原始名称及 SKU；未知 SKU 为 `null` |
| `gpu_variant`、`vram_gb`、`gpu_count` | 硬件版本、显存和实例 GPU 数量；来源不明确时为 `null` |
| `amount`、`currency`、`unit` | 原币十进制字符串或询价 `null`；当前单位 `gpu_hour`，不换汇 |
| `billing_mode` | 可确认的计费方式，如 `on_demand` |
| `price_basis` | `advertised_per_gpu`、`gpu_component`、`starting_price` 或整实例分摊 `instance_total_allocated` |
| `quote_status` | `quoted`、`starting_at` 或 `contact_sales` |
| `regions`、`geographic_scope` | 地区列表；公开来源范围为 `regions` / `unspecified`，UCloud 为请求上下文 `requested_zone` |
| `account_scope` | Nebius / Crusoe / Lambda / AutoDL 公开页为 `public_catalog`；Lambda API 为 `authenticated_catalog`，UCloud 为 `account_quote` |
| `tax_scope` | 来源可确认时 `excluded`，未知时 `unspecified`；未知值不能视作含税 |
| `observed_at` | UTC 采样时间 |
| `effective_from`、`effective_until` | 可确认的 ISO 生效日期，未知为 `null` |
| `source_url`、`source_type` | 官方来源和类型；Lambda / AutoDL 公开页为 `public_page`，Lambda API 为 `official_api`，UCloud 为 `official_quote_api` |
| `availability` | 公开页面 / UCloud 为 `unknown`；仅 Lambda API 按容量报告为 `capacity_reported` / `no_capacity_reported`，不保证下单成功 |
| `notes` | 价格限制、承诺期、购买条件等来源说明数组 |

Nebius L40S 等拆分报价可额外返回 `components`，说明资源分项。Lambda 默认公开页的 `amount` 是来源挂牌每卡小时价，`price_basis=advertised_per_gpu`；`instance_price` 为该价格乘明确卡数后的派生整实例小时价，不是第二个独立报价。Lambda API / UCloud 则从来源整实例原价除以卡数，使用 `instance_total_allocated`。这些价格属于完整资源包，不等于裸 GPU 单独售价。

`instance_price` 包含十进制字符串 `amount`、`currency`（USD 或 CNY）和 `unit=instance_hour`。UCloud 还可包含白名单金额字段 `original_amount`、`details`、`original_details`；不返回原始账号响应。UCloud `normalization` 明确记录公式 `instance_price.amount / gpu_count`、保留 12 位小数及 `ROUND_HALF_UP` 舍入。

Nebius GPU / CPU / RAM 分项价格不等于整实例租价。Crusoe 的 Contact sales 不能生成数值；公开挂牌不代表库存充足或支持自助购买。起价与确定报价需要分别处理，不能无条件进入确定价比较。

若来源提供多组历史或未来生效价格，不能把任意数字当当前价格；保留可确认的适用日期。未采样的历史价格不能由本库还原。

## 筛选

Python `filters` 接受数组字段：`gpu_models`、`currencies`、`billing_modes`、`regions`、`compute_countries`、`sales_countries`、`zones`、`gpu_counts`。

| 筛选 | Nebius | Crusoe | Lambda | AutoDL | UCloud |
| --- | --- | --- | --- | --- | --- |
| GPU 型号、币种、计费方式 | 支持 | 支持 | 支持 | 支持 | 支持 |
| 地区 | 依据来源范围核对 | 不支持 | 不支持 | 不支持 | 根据请求 target 本地筛选 |
| 可用区 | 不支持 | 不支持 | 不支持 | 不支持 | 根据请求 target 本地筛选 |
| 卡数 | 不支持 | 不支持 | 支持 | 不支持 | 支持 |
| 服务 / 销售国家 | 无可靠映射 | 无可靠映射 | 无可靠映射 | 无可靠映射 | 无可靠映射 |

配置格式支持字段不代表来源支持应用。返回的每来源信息记录请求条件及应用 / 不支持情况，不静默忽略。对来源未说明地区的价格不能标注为指定地区报价，也不能由币种、网页语言或访问 IP 猜测国家。

若 Nebius 的相关报价缺少地区说明，地区筛选返回 `unverifiable_filter`，而不是把未知地区当成确定的 `no_matches`。来源不提供该维度时返回 `unsupported_filter`。

Lambda 默认公开页来自 `https://lambda.ai/instances`，实例卡数由 8 / 4 / 2 / 1 卡表明确给出。`regions=[]`、`geographic_scope=unspecified`，不支持地区、国家或可用区筛选；挂牌不证明库存。`tax_scope=excluded`，USD 币种依据以 `currency_source_url` 保留。

公开页 `resources` 使用 `vcpus`、`memory_gib` 和 `storage`；`storage` 包含十进制字符串 `amount`、原始 `unit`（`TiB` 或 `GiB`）及 `type=SSD`。不把 TiB 的数值当作 GiB，也不直接改成十进制 GB。

显式选择 `LAMBDA_SOURCE=api` 后，`capacity_regions` 才来自认证目录的容量响应；它不是逐地区价格，不能填入报价 `regions`。API `instance_price` 保留 USD 实例小时原价，`amount` 为按卡数分摊成本，`resources` 使用 `vcpus`、`memory_gib`、`storage_gib`、`architecture`。默认公开模式即使已有 API key 也不请求该目录。

UCloud 的 `instance_price` 为 CNY 整实例小时价，`amount` 为按请求 GPU 数量分摊的值。`resources` 使用 `vcpu_count`、`memory_mb`、`disks` 保留请求资源；`requested_configuration` 保留去掉 `ProjectId` 的请求配置。地区 / 可用区来自请求 target，`geographic_scope=requested_zone`；询价响应不回显这些条件，不能视为独立核验，更不证明有库存或规格可售。

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

错误区分未实现、未支持筛选、网络 / 超时、来源请求、页面 / 文档解析及其他可识别来源失败。仅可选 Lambda API / UCloud 缺凭据返回 `missing_credentials`；UCloud 内联目标缺失或无效分别返回 `missing_price_targets` / `invalid_price_targets`。FILE 读取 / 校验失败为全局 `ConfigurationError`，在来源采集前终止；公开免费路径不需要凭据。诊断不得回显 API key、Cookie、签名、会话内容或原始账号响应。

库不把错误表示成零元，不自动使用上次成功报价。换汇、数据过期、历史合并、价格变化、数据库和上传都由调用方处理；调用方应保存来源、单位和采样时刻，避免丢失价格语义。
