# 返回数据和价格口径

0.13.0 推荐原文档五家：**Nebius、Lambda、Crusoe、AutoDL、UCloud**。Python `collect_prices` 返回标准 dict，CLI 默认输出同样的 JSON。默认 CSV 为 10 列 `market` 小时报价表；`compact` 保留严格地区表，`full` 保留原 51 列全部审计记录。库不存储、上传、换汇或使用历史样本回退。另四家适配器仍可显式选择。

## 批次与来源状态

| 字段 | 含义 |
| --- | --- |
| `schema_version` / `collected_at` | 返回结构版本与本次批次 UTC 时间 |
| `status` | `success`、`partial`、`failed`；单个平台失败不抹掉其余成功结果 |
| `execution` | `runtime=python`、`parsing=deterministic_rules`、`uses_llm=false`、所选 `source_policy` |
| `prices` | 本次经过筛选的原始来源记录；不等同于所有记录都符合比较资格 |
| `market_comparison` | 有效每 GPU 小时目录 / 地区报价数量，及其中地区价、目录价、排除记录和有有效报价的平台 |
| `comparison` | 兼容保留严格地区口径 `scope=verified_regional_gpu_hour`；`eligible_quote_count` / `excluded_quote_count` |
| `provider_results` | 来源、方法、选择理由、观察时间、请求 / 返回数量、筛选状态及错误；`market_quote_count` 为有效小时目录 / 地区价，`regional_hourly_quote_count` 为严格地区价 |
| `geographic_coverage` | 本批报价的位置证据摘要，不是全市场覆盖率或库存报告 |
| `coverage` | `include_coverage=True` / `--coverage` 生成的型号族索引；不合并硬件、币种或价格条件 |

`market_comparison.eligible_quote_count` 是默认 CSV 行数依据；`regional_quote_count` / `catalog_quote_count` 区分严格地区记录与其余有效小时记录。`comparison` 保持原有地区统计，不能继续把它当默认 market 总条数。

`source_type` 保留实际接口、公开网页、文档、授权市场或 `official_website_json` 来源。`collection_method` 可为 `http_json`、`http_html`、`http_document`、`browser_dom`，兼容混合源为 `hybrid_http`；`selection_reason` 和适用时的 `fallback_reason` 解释请求前的选择。网页或网站 JSON 不冒充正式价格 API，已选中接口失败不触发另一来源。

认证字段、签名、Cookie、账号项目 ID、原始账号响应、SSH 数据不得进入结果。网络与解析错误不回显上游响应正文或凭据。

## CSV 三种投影

| Profile | 行资格 | 列与用途 |
| --- | --- | --- |
| `market`（默认） | 实际 GPU / 容器小时租价；允许目录或账号目录未标明价格地区 | 10 列，日常五家报价；适用范围如实标注 |
| `compact` | 在 market 合格记录基础上，国家与实际价格 region 均已核实 | 10 列，严格地区比较；兼容 0.11 / 0.12 的默认规则 |
| `full` | 不执行比较资格筛选，保留所有本次来源记录 | 原 51 列，审计起价、组件、询价、月包和下线记录 |

稳定英文列为 `gpu_model, provider, location, amount, currency, unit, pricing_conditions, availability, source_url, observed_at`。`MARKET_CSV_COLUMNS` / `MARKET_CSV_HEADERS` 定义默认表，`COMPACT_CSV_*` 定义严格地区表，`CSV_*` 定义完整审计表。表头默认英中双语；`bilingual_headers=False` / `--csv-headers english` 仅改变列名，不改变值。

`market_eligible_quote(quote)` 要求有效型号、GPU VM / 容器产品、`quote_status=quoted`、合法原币数值、`unit=gpu_hour`、实际每卡或明确整机分摊的租用价口径。起步价、单独 GPU 组件、月包、Contact sales、特殊优惠资格未核实及明确 `offline` / `ended` / `upcoming` / `unavailable` 不进入 market。`availability=unknown` 表示库存未核实，不把挂牌当现货。

`publishable_quote(quote)` 保持严格地区检查：还需 `region_price_verified=true`、非空有效国家和 region，以及 `regional_quote` / `zone_quote` / `requested_region_quote` / `requested_zone_quote` 范围。位置缺失只影响严格地区资格，不应掩盖来源明确的有效目录价。`market` 的位置列清楚标为“公开目录报价；适用地区未标明”等范围，不填全球，也不从平台覆盖推断价格地区。

型号列保留明确变体、显存、卡数及关键 CPU / RAM；条件列保留普通 / 会员、Spot、税、账号资格、生效时间、来源实例总价和产品线。UCloud CompShare 与 UHost 必须分开标明，不能合并成相同规格。资格未核实的 `PriceDetails` 不覆盖普通原价。

所有 profile 返回文本而不写文件，采用 UTF-8 BOM / CRLF；调用方用 `encoding="utf-8", newline=""` 保存即可。full 的数组与 `_json` 列为紧凑 JSON，保留批次时间 / 状态；CSV 不附来源状态或 coverage 表。可能被表格识别成公式的文本加前导单引号，真实金额保持数值字符串。月价不除以 720，CNY / ILS / EUR 不换成 USD，时间不按主机时区改写。

CLI stdout 只含所选 JSON / CSV，计数与诊断写 stderr。成功 `0`、部分失败 `2`、失败 / 配置错误 `1`；来源成功但 profile 没有合格行时只输出表头且仍返回 `0`。调用方需同时检查来源状态与行资格，再决定发布。

## 单条价格

| 字段 | 含义 |
| --- | --- |
| `provider` / `product_type` | 平台及 GPU VM / 容器产品范围；产品线另保留在条件中 |
| `gpu_model` / `gpu_variant` / `vram_gb` | 来源型号、硬件版本、单卡显存；未知为空 |
| `raw_name` / `raw_sku` | 官方原名与实际存在的规格标识；不为网站行猜造云 API SKU |
| `gpu_count` | 明确实例卡数；每 GPU 费率本身不证明整机有几张卡 |
| `amount` / `currency` / `unit` | 原币十进制字符串、币种、`gpu_hour` / `gpu_month`；未知金额 null |
| `instance_price` | 来源完整实例 / 套餐总价及单位，与每卡价分开 |
| `billing_mode` / `price_basis` / `quote_status` | 计费方式、每卡 / 分摊 / 组件 / 起价口径、数值 / 起价 / 联系销售 |
| `pricing_tier` / `membership_required` / `account_scope` | 普通 / 会员及账号适用条件，不假定所有人都有折扣 |
| `resources` / `requested_configuration` | 可确认 CPU、RAM、磁盘与单位；GB 不改称 GiB，范围不选成某个具体预设 |
| `availability` | 来源明确的下线 / 结束 / 可租标记，或 unknown；不保证购买资格 |
| `source_url` / `source_type` / `api_endpoint` | 来源页面 / 接口类型及实际网站 JSON 路由；不包含签名请求或凭据 |
| `observed_at` / `effective_from` / `effective_until` | 本次观察和来源明确生效范围；缺失生效日期不伪造 |
| `source_snapshot_at` | Nebius 当前 Spot 源快照，与本次观察及单项生效时间分别记录 |
| `conditions` / `notes` / `normalization` | 资格、产品线、费用范围、分摊与舍入公式及未核实事项 |

若分项无法组成完整实例，不能假装得到整机每卡价。明确整机小时总价只按来源卡数分摊；正价不能舍入成伪免费价。

## 地理证据和筛选

`regions` / `zones` 是价格绑定代码，`location` 保留可核对名称及国家，`compute_countries` 为部署国家 ISO 两字母代码。`unlocated_catalog` 表示已取到价格但无价格地区；`platform_coverage` 只有平台供给范围；`regional_quote` / `zone_quote` 为来源实际地区价；`requested_*_quote` 为完整请求配置在指定位置的询价，不表示响应独立回显全部部署条件。

0.16 的 Lambda console 另有已核查的共享目录价范围：`price_applicability.locations` 给出该 SKU 当前可选国家、中文地区和 region code，`applicable_countries` / `applicable_regions` 供程序读取；`catalog_applicability` 汇总本批可选国家地区。官方标准控制台在这些地区共用同一 SKU 目录单价，不产生多条独立询价，`region_price_verified` 等严格字段保持原义。运行时控制台入口脚本指纹必须匹配已审版本；变更时不沿用共享结论，原价保留为审计，主表排除。空库存、未知国家和私有地区也只留完整目录。详见 [Lambda 说明](lambda-console.md)。

Nebius 当前 Spot API 的 region 是价格位置；官网 JSON 目录没有价格地区，不拼接文档覆盖。Lambda `capacity_regions` 仅为容量；AutoDL 首页无位置，授权市场保留原始 region，不猜国家。UCloud CompShare 的配置位置和已核验国家映射随请求 / 来源保留，UHost 认证询价核对官方位置目录；不同产品的地区与配置不能互相套用。未知国家不按前缀、总部、币种或 IP 补齐，也不宣称全球统一。

筛选字段包括数组 `gpu_models`、`gpu_counts`、`currencies`、`billing_modes`、`regions`、`zones`、`compute_countries`、`coverage_regions`、`coverage_countries`。国家 / region / zone 必须在同一条报价内成立；全局筛选逐字段覆盖每来源筛选。销售国家 `sales_countries` 当前不支持。

`--country` / `--region` / `--zone` 仅筛实际价格位置，文档供给另用 `--coverage-country` / `--coverage-region`。来源整体不支持维度报 `unsupported_filter`；相关记录本应支持却缺证据报 `unverifiable_filter`；证据完整且无匹配为 `no_matches`。开启地区筛选后，未知地区目录不能被强行当成该地区价格。

例外是上述已核查的 Lambda console 共享目录价：`--country` / `--region` 筛该价的可选适用位置，两项联合时必须属于同一个位置条目。筛选状态会标明共享目录适用范围，不把结果计入独立地区报价数量。`--zone` 仍不支持。

## 五家金额来源

- **Nebius**：Spot API 读取实际 `GPU hour`、币种、region 和生效时间；网站 Next.js JSON 补普通 on-demand 目录，CPU / RAM 按表中 GB 保留，未公布卡数和显存不猜。From 和 Contact us 留审计。兼容文档的 L40S GPU 组件不当整机。账号估价必须核对整套资源和聚合单位。
- **Lambda**：网页每卡价原样读取；API `price_cents_per_hour / 100 / specs.gpus` 分摊，整实例原值保留，容量不补成地区价。
- **Crusoe**：仅 GPU instances 区块；数值普通报价与 Contact sales 分开，不混入账单 / 模型部署。
- **AutoDL**：首页普通 / 会员各自读取；授权市场按显示金额和小时单位解析，保留资格与地区，不取已有实例或 SSH 数据。
- **UCloud**：CompShare 实际 `GetCompShareInstancePrice` 询价的 `OriginalPriceDetails` 提供普通原价；优惠 `PriceDetails` 资格未核实，仅审计。按实际 GPU 数分摊完整配置小时费，产品线及配置保留。显式签名 UHost 需业务成功与单位核对；旧匿名 UHost 月包仅在兼容来源中保留月单位，不换算小时。

其他四家和具体请求 / 认证边界见 [PROVIDERS.md](PROVIDERS.md)。合成测试不能证明有效账号成功联调，历史样本不能作为现价。

## 完整目录模式（0.14）

`catalog_scope=complete` 返回 `catalog_audit`：将数值记录、需询价项、起价、派生配置和源费率数量分别计数。`all_prices_complete=false` 表示所选公开来源的成功不证明所有合同、账号折扣与配置均已取得。源费率、配置行和 GPU 平台不能相加成独立报价总数。

Nebius `quote_origin=published_tariff_preset_calculation` 表示按官方 GPU / CPU / RAM 费率计算明确 preset，`regional_spot_preset_calculation` 表示当前地区 Spot 单价应用于明确 preset。两者都有 `rate_derivation.independent_provider_quote=false`、源分项和公式；`instance_price.scope` 是计算资源费用，磁盘与网络等附加费另计。覆盖地区仍不成为独立价格地区。

Lambda 预留集群为 `product_type=gpu_cluster`，每 GPU 小时价和按周结算并存。`gpu_count=null` 不猜单机卡数，集群总数量在 `selected_configuration.cluster_gpu_count`，`cluster_gpu_count_relation=minimum` 表示下限；预留期限和是否联系销售保留。

Crusoe 可选账号 reservations 放在 `provider_results.contract_records`，范围为私有账号审计，不进入 `prices` 或小时报价 CSV。响应缺少结构化币种、GPU 产品及小时单位证据时不得自行补成美元每卡小时价。该私有数据不应直接进入公开网站或仓库。

`prices_to_csv(result, profile="catalog")` 保留 10 列目录及标明状态的起价 / 销售询价项，销售金额为空；`full` 中的 `extra_metadata_json` 保留新增口径和推导字段。其他 profile 的价格资格要求不因完整目录模式而放宽。
