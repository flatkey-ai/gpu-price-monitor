# 返回数据口径与契约

UCloud 报价另带 `target_index`：对应调用方 `UCLOUD_PRICE_TARGETS_JSON` 原数组的零起始下标，用于在过滤后关联原始目标。项目 ID 不写入报价返回；不同项目即使硬件配置相同，也可通过下标区分。

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
| `account_scope` | Nebius / Crusoe 为 `public_catalog`，Lambda 为 `authenticated_catalog`，UCloud 为 `account_quote` |
| `tax_scope` | 来源可确认时 `excluded`，未知时 `unspecified`；未知值不能视作含税 |
| `observed_at` | UTC 采样时间 |
| `effective_from`、`effective_until` | 可确认的 ISO 生效日期，未知为 `null` |
| `source_url`、`source_type` | 官方来源链接和来源类型；Lambda 为 `official_api`，UCloud 为 `official_quote_api` |
| `availability` | 公开页面 / UCloud 为 `unknown`；Lambda 按容量报告为 `capacity_reported` 或 `no_capacity_reported`，不保证下单成功 |
| `notes` | 价格限制、承诺期、购买条件等来源说明数组 |

Nebius L40S 等拆分报价可额外返回 `components`，说明资源分项。Lambda / UCloud 在 `amount` 返回整实例价按 GPU 数量分摊的每卡小时成本，同时用 `instance_price` 保留原始整实例小时价格。该分摊数值包含实例资源包，不等于可独立购买的 GPU 价格。

`instance_price` 包含十进制字符串 `amount`、`currency`（USD 或 CNY）和 `unit=instance_hour`。UCloud 还可包含白名单金额字段 `original_amount`、`details`、`original_details`；不返回原始账号响应。UCloud `normalization` 明确记录公式 `instance_price.amount / gpu_count`、保留 12 位小数及 `ROUND_HALF_UP` 舍入。

Nebius GPU / CPU / RAM 分项价格不等于整实例租价。Crusoe 的 Contact sales 不能生成数值；公开挂牌不代表库存充足或支持自助购买。起价与确定报价需要分别处理，不能无条件进入确定价比较。

若来源提供多组历史或未来生效价格，不能把任意数字当当前价格；保留可确认的适用日期。未采样的历史价格不能由本库还原。

## 筛选

Python `filters` 接受数组字段：`gpu_models`、`currencies`、`billing_modes`、`regions`、`compute_countries`、`sales_countries`、`zones`、`gpu_counts`。

| 筛选 | Nebius | Crusoe | Lambda | UCloud |
| --- | --- | --- | --- | --- |
| GPU 型号、币种、计费方式 | 支持 | 支持 | 支持 | 支持 |
| 地区 | 依据官方地区范围核对 | `unsupported_filter` | `unsupported_filter` | 根据请求 target 本地筛选 |
| 可用区 | 不支持 | 不支持 | 不支持 | 根据请求 target 本地筛选 |
| 卡数 | 不支持 | 不支持 | 支持 | 支持 |
| 服务 / 销售国家 | 无可靠映射，结构化错误 | 无可靠映射，结构化错误 | 无可靠映射，结构化错误 | 无可靠映射，结构化错误 |

配置格式支持字段不代表来源支持应用。返回的每来源信息记录请求条件及应用 / 不支持情况，不静默忽略。对来源未说明地区的价格不能标注为指定地区报价，也不能由币种、网页语言或访问 IP 猜测国家。

若 Nebius 的相关报价缺少地区说明，地区筛选返回 `unverifiable_filter`，而不是把未知地区当成确定的 `no_matches`。来源不提供该维度时返回 `unsupported_filter`。

Lambda 的 `capacity_regions` 来自目录响应中的可用容量地区，不是逐地区价格；其 `regions` 不根据容量地区生成，所以按地区或国家筛选返回 `unsupported_filter`。`instance_price` 保留 USD 实例小时原价，`amount` 为除以 GPU 数量后的分摊价。

Lambda `resources` 使用 `vcpus`、`memory_gib`、`storage_gib`、`architecture` 保存目录资源。

UCloud 的 `instance_price` 为 CNY 整实例小时价，`amount` 为按请求 GPU 数量分摊的值。`resources` 使用 `vcpu_count`、`memory_mb`、`disks` 保留请求资源；`requested_configuration` 保留去掉 `ProjectId` 的请求配置。地区 / 可用区来自请求 target，`geographic_scope=requested_zone`；询价响应不回显这些条件，不能视为独立核验，更不证明有库存或规格可售。

## 错误和调用方责任

错误区分未实现、未支持筛选、网络 / 超时、来源请求、页面 / 文档解析及其他可识别来源失败。Lambda / UCloud 缺凭据返回 `missing_credentials`；UCloud 目标缺失或无效分别返回 `missing_price_targets` / `invalid_price_targets`。诊断不得回显 API key、Cookie、签名、会话内容或原始账号响应。

库不把错误表示成零元，不自动使用上次成功报价。换汇、数据过期、历史合并、价格变化、数据库和上传都由调用方处理；调用方应保存来源、单位和采样时刻，避免丢失价格语义。
