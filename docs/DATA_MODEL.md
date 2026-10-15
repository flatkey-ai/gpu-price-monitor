# 返回数据口径与契约

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
| `price_basis` | `advertised_per_gpu`、`gpu_component` 或 `starting_price` |
| `quote_status` | `quoted`、`starting_at` 或 `contact_sales` |
| `regions`、`geographic_scope` | 来源原始地区列表；范围为 `regions` 或 `unspecified` |
| `account_scope` | 当前公开来源为 `public_catalog` |
| `tax_scope` | 来源可确认时 `excluded`，未知时 `unspecified`；未知值不能视作含税 |
| `observed_at` | UTC 采样时间 |
| `effective_from`、`effective_until` | 可确认的 ISO 生效日期，未知为 `null` |
| `source_url`、`source_type` | 官方来源链接和来源类型 |
| `availability` | 当前公开目录不证明库存，返回 `unknown` |
| `notes` | 价格限制、承诺期、购买条件等来源说明数组 |

Nebius L40S 等拆分报价可额外返回 `components`，说明资源分项。后续来源若提供整实例价或不同计费单位，需要明确扩展数据契约，不能将其伪装为当前 `gpu_hour` 报价。

Nebius GPU / CPU / RAM 分项价格不等于整实例租价。Crusoe 的 Contact sales 不能生成数值；公开挂牌不代表库存充足或支持自助购买。起价与确定报价需要分别处理，不能无条件进入确定价比较。

若来源提供多组历史或未来生效价格，不能把任意数字当当前价格；保留可确认的适用日期。未采样的历史价格不能由本库还原。

## 筛选

Python `filters` 接受数组字段：`gpu_models`、`currencies`、`billing_modes`、`regions`、`compute_countries`、`sales_countries`、`zones`、`gpu_counts`。

| 筛选 | Nebius | Crusoe |
| --- | --- | --- |
| GPU 型号、币种、计费方式 | 支持对解析结果筛选 | 支持对解析结果筛选 |
| 地区 | 依据官方地区范围核对 | `unsupported_filter` |
| 服务 / 销售国家、可用区、卡数 | 当前无法可靠验证，结构化错误 | 当前无法可靠验证，结构化错误 |

配置格式支持字段不代表来源支持应用。返回的每来源信息记录请求条件及应用 / 不支持情况，不静默忽略。对来源未说明地区的价格不能标注为指定地区报价，也不能由币种、网页语言或访问 IP 猜测国家。

若 Nebius 的相关报价缺少地区说明，地区筛选返回 `unverifiable_filter`，而不是把未知地区当成确定的 `no_matches`。来源不提供该维度时返回 `unsupported_filter`。

后续 Lambda 等来源可能提供一份目录价和多个容量地区，容量和价格范围必须分别表达，不能凭库存列表复制逐地区报价。

## 错误和调用方责任

错误区分未实现、未支持筛选、网络 / 超时、来源请求、页面 / 文档解析及其他可识别来源失败。诊断不得回显 API key、Cookie、签名、会话内容或原始账号响应。

库不把错误表示成零元，不自动使用上次成功报价。换汇、数据过期、历史合并、价格变化、数据库和上传都由调用方处理；调用方应保存来源、单位和采样时刻，避免丢失价格语义。
