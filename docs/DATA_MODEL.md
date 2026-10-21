# 返回数据和价格口径

0.11.0 采集 Nebius、Lambda、Crusoe、AutoDL、UCloud、RunPod、DigitalOcean、Verda、Azure 九家。Python `collect_prices` 返回标准 dict；CLI stdout 默认是相同的 JSON。`prices_to_csv(result)` / `collect --format csv` 默认返回严格的 10 列地区每 GPU 小时比较表，`profile="full"` / `--csv-profile full` 保留原 51 列来源审计表。两种表头均默认英中双语，可选纯英文。库不存储、上传、换汇、补造库存或使用历史样本回退。

## 批次结果

- `schema_version=1`；`collected_at` 为当前批次的 UTC 时间。
- `status=success|partial|failed`；单个平台失败不抹掉其余平台成功结果。
- `prices` 是本次通过筛选的来源记录。
- `comparison.scope=verified_regional_gpu_hour`，`eligible_quote_count` / `excluded_quote_count` 说明其中符合 / 不符合默认比较条件的条数；来源采集成功不等于存在可比较报价。
- `provider_results` 记录来源 URL/类型、观察时间、抓取与返回数量、逐维度筛选反馈、结构化错误。
- `geographic_coverage` 只统计本次返回中的国家绑定、地区绑定、位置未知和平台覆盖条数，不表示整个市场覆盖率。
- `include_coverage=True` 或 `--coverage` 添加 GPU 型号族 `coverage`，仅索引返回记录，不合并硬件、币种或价格条件。

认证字段、签名、Cookie、账号项目 ID、原始账号响应、已有实例的 SSH 数据均不得进入结果。网络和解析错误不打印上游错误响应正文或凭据。

## CSV 投影

`prices_to_csv(result, profile="compact")` 接受 `collect_prices` 的批次结果，返回已包含 UTF-8 BOM 的字符串，行结束符为 CRLF；使用 Python 标准库，无额外表格依赖。它不更改原 dict，不执行抓取、文件写入、换汇或上传。

默认比较表的稳定英文列为 `gpu_model, provider, location, amount, currency, unit, pricing_conditions, availability, source_url, observed_at`，对应公开常量 `COMPACT_CSV_COLUMNS` / `COMPACT_CSV_HEADERS`。型号列合并明确硬件变体、显存、卡数及关键 CPU / RAM 配置；位置列只显示已核实国家和价格地区；条件列保留普通 / 会员、云档位、Spot、税费、账号适用范围、来源明确的整实例总 / 原价及生效时间。

`publishable_quote(quote)` 检查默认比较条件：`quote_status=quoted`、合法数值金额、`unit=gpu_hour`、`region_price_verified=true`，且 `price_scope` 为 `regional_quote` / `zone_quote` / `requested_region_quote` / `requested_zone_quote`，同时有非空有效 ISO 国家列表及 region。地区不完整、未知目录、仅平台覆盖、起步价、`gpu_component`、月包和 Contact sales 被排除；明确 `offline` / `ended` / `upcoming` / `unavailable` 也不进入比较表。来源明确的零值仍保留，未知金额不变成零。`availability=unknown` 只表示库存未知，不把有效地区挂牌说成现货。

`prices_to_csv(result, profile="full")` / CLI `--csv-profile full` 不执行上述比较筛选，保持原 51 列、全部来源记录及元数据。`CSV_COLUMNS` / `CSV_HEADERS` 继续定义完整审计表。国家 / 地区 / zone 数组及 `_json` 列使用紧凑 JSON，`collected_at` 与 `collection_status` 保留批次时间和状态；未知目录、覆盖、月价、组件、起价及下线记录均可审计。旧日期 examples 是当时的宽表来源证据，不能当作当前小时比较表。

`prices_to_csv(result, bilingual_headers=False)` 或 CLI `--csv-headers english` 使用所选 profile 的英文 ID；显式 `--csv-headers bilingual` 与默认一致。该选择只改变表头，JSON 与报价值不变。金额始终保留精确原币十进制字符串，时间保留原 ISO 表达，不按主机时区改写。可能被表格软件识别成公式的文本会加前导单引号，数值金额保持原样；不换汇，也不除以 720 将月价变成小时价。

`provider_results`、`geographic_coverage` 与型号 `coverage` 不作为 CSV 附表输出。默认比较 CSV 在 stderr 输出保留及排除条数；错误诊断也写 stderr。退出码由来源采集状态决定：成功 `0`、部分失败 `2`、失败 / 配置错误 `1`。来源成功但没有合格比较行时仅有表头且仍退出 `0`，不以错误行或零价伪造报价。需要完整来源状态与排除记录时保留 JSON 或 full 审计表。

## 单条价格

| 字段 | 含义 |
| --- | --- |
| `provider`、`product_type` | 九家平台标识及 GPU VM/容器等产品范围 |
| `gpu_model`、`gpu_variant`、`vram_gb` | 来源型号、硬件版本、显存；未知为空，不跨版本合并 |
| `raw_name`、`raw_sku` | 来源名称或规格标识 |
| `gpu_count` | 明确的实例 GPU 数量；目录单卡费率不代表实际整机卡数 |
| `amount`、`currency`、`unit` | 十进制字符串、原始币种、`gpu_hour`/`gpu_month`；未知金额为 null |
| `instance_price` | 完整实例/套餐总价及原始周期；不与每 GPU 金额混用 |
| `billing_mode` | `on_demand`/`spot`/`monthly` 等真实计费方式 |
| `price_basis` | `advertised_per_gpu`、`instance_total_allocated`、组件费率或起价等来源口径 |
| `quote_status` | `quoted`、`starting_at`、`contact_sales`；询价不得写为 0 |
| `pricing_tier`、`membership_required` | 普通/会员/账号市场等身份条件，不能覆盖彼此 |
| `cloud_tier` | RunPod 的 Secure / Community 云档位；不是会员身份，比较时必须保留 |
| `account_scope` | 公开目录、促销、认证目录、账号报价或合同报价，不假定账户价格对所有人适用 |
| `resources`、`requested_configuration` | CPU、RAM、磁盘、网络等可确认配置；保留 GB/GiB/TiB 等原单位 |
| `availability` | 来源明确的下线/结束/即将开始/可租状态，或 unknown；挂牌不保证可购 |
| `source_url`、`source_type`、`observed_at` | 可追溯来源及本次观察 UTC 时间 |
| `effective_from`、`effective_until` | 来源明确的价格生效/截止时间，不拿页面更新时间替代 |
| `source_snapshot_at` | Nebius 当前 Spot API 的源快照时间；与本次观察和单项生效时间分别保留 |
| `conditions`、`notes` | 资格、合同、组件范围、价格和库存限制 |

`normalization` 记录分摊公式和舍入。正金额不允许因舍入变为伪免费价。若分项不能组成整套实例总价，不能假装得到整机每卡价。小时和月份是不同单位，不假定一个月等于 720 小时。

## 地理证据

`regions`、`zones` 保留原始来源代码，`location` 保留可核对的名称及 `country_code`；`compute_countries` 仅为当前价格实际绑定的部署国家 ISO 两字母代码。供应商的官方国家归类按来源保留，不由代码前缀或总部改写。

`price_scope` 的含义：

| 值 | 含义 |
| --- | --- |
| `unlocated_catalog` | 价格已取到，但没有可关联的价格地区 |
| `platform_coverage` | 只有硬件平台机房覆盖，不证明逐地区价格 |
| `regional_quote` / `zone_quote` | 来源具体市场记录或套餐绑定地区/可用区 |
| `requested_region_quote` / `requested_zone_quote` | 官方估价/询价对明确位置及完整资源配置返回的账号金额；来源是否独立回显位置见验证字段和 notes |

`region_price_verified=false` 的记录不支持据此建立地区价格；不生成 `compute_countries`。Nebius 公开文档中的供给限制单独保存为 `coverage_regions` / `coverage_countries`，`coverage_location_source` 记录文档与官方国家映射依据；价格 `regions` / `compute_countries` 保持空。即使平台仅在单一 region 供给，也不据此变成一次独立地区询价。Nebius 匿名当前 Spot API 的 `region` 才是该条实际价格位置。Lambda API 的 `capacity_regions` 独立记录容量，不转换为价格地区。来源没有位置不证明全球统一价。

UCloud 的公开位置来自官方 `ListAllRegions`/`ListAllZones`，每套餐×可用区独立。认证 API 先核对目标 Region+Zone 与官方目录，再询价；响应不独立回显位置，范围明确标为请求上下文。Nebius API 先只读确认项目地区，再核对官方国家及 GPU 平台可用地区，不能仅相信调用者填写的国家。AutoDL 登录市场保留挂牌原始地区代码/名称；没有可核实国家或可用区时保持未知。Azure 的价格地区来自 Retail Prices 响应，国家来自官方地区目录的已核验代码映射，`location_source` 记录依据；未知国家保持空，不把地区代码前缀当证据。

## 筛选

`filters` 和每来源 `provider_filters` 均支持数组字段 `gpu_models`、`gpu_counts`、`currencies`、`billing_modes`、`regions`、`zones`、`compute_countries`、`coverage_regions`、`coverage_countries`、`sales_countries`。全局筛选逐字段覆盖每来源筛选。`sales_countries` 目前不支持。CLI `--country` / `--region` 只匹配实际价格位置；Nebius 文档的供给范围另用 `--coverage-country` / `--coverage-region`，不会与价格位置混合。

| 来源 | 地区 | 国家 | 可用区 | 卡数 |
| --- | --- | --- | --- | --- |
| Nebius public 当前 Spot | 当前 API 返回的价格地区 | 官方地区目录映射；未知为空 | 不支持 | 未公布 |
| Nebius public 文档 | 仅 `coverage_regions`，不当价格地区 | 仅 `coverage_countries`，不当价格国家 | 不支持 | 不支持 |
| Nebius api | 已验证项目地区的配置估价 | 官方映射 | 不支持 | 显式已核对预设 |
| Lambda public/api | 不支持地区差价筛选 | 不支持 | 不支持 | 来源明确的卡数 |
| Crusoe public | 不支持 | 不支持 | 不支持 | 不支持 |
| AutoDL public | 不支持 | 不支持 | 不支持 | 不支持 |
| AutoDL market | 具体市场地区 | 不支持 | 不支持 | 未选定实例卡数 |
| UCloud public/api | 来源套餐/目标配置 | 官方位置目录 | 来源套餐/目标配置 | 来源配置 |
| RunPod | 不支持 | 不支持 | 不支持 | 目录无完整实例卡数 |
| DigitalOcean | 不支持 | 不支持 | 不支持 | 来源明确的 1 / 8 卡 |
| Verda | 不支持 | 不支持 | 不支持 | 来源明确的 1 / 2 / 4 / 8 卡 |
| Azure | 价格返回的 ARM region | 官方地区目录已核验映射；未知为空 | 不支持 | 已核验固定 SKU 卡数 |

本应可支持但缺少元数据时返回 `unverifiable_filter`；整个来源不支持的维度返回 `unsupported_filter`；证据完整且无匹配为 `no_matches`。国家、地区、可用区要在同一报价记录上同时匹配，不能跨记录拼接。

## 各平台原始金额转换

- Lambda public：官网直接显示 USD/GPU/hour；乘明确卡数得到派生实例价。API：`price_cents_per_hour / 100` 得整实例美元小时价，再除以 `specs.gpus`。容量不是独立地区价格。
- Nebius public：文档的 GPU/CPU/RAM 组件、USD/ILS、生效列和起价原样保留，位置仅为供给覆盖；免费匿名 `GET /billing/v1alpha1/spot-price` 的当前实际费率按平台、region、原币、`GPU hour` 及 `effectiveTime` 核对，返回 `regional_quote`。采样时间、生效时间与 `snapshotTime` 分开，历史图表聚合点不作现价。可选账号 API：精确 `resourceCosts` 与 `totalCosts` 按响应聚合单位核对，固定整套资源费用分摊，合同价独立标记；缺完整 GPU 费用的月份不得当 GPU 月价。
- Crusoe：仅 GPU instances，排除模型 API/微调/托管推理；Contact sales 金额为 null。
- AutoDL public：普通和会员各自读取。market：按官网已选按量口径读取每 GPU 页面金额，保留每卡 CPU/RAM、区域、账号/会员条件和观察到的可租状态，不包含已有实例或 SSH 信息。
- UCloud public：`CurPrice`/`OriginalPrice` 分值除 100，整月套餐再按卡数分摊为 `gpu_month`。API：`RetCode=0` 且响应 ChargeType 与目标 Dynamic 一致才接受 CNY 实例小时价；HTTP 200 不等于业务成功。

- RunPod：`securePrice` / `communityPrice` 分别为对应已启用云档位的公开每 GPU 小时价，保留 `cloud_tier`；目录不是完整实例配置，价格为零 / 空不代表免费。
- DigitalOcean：文档金额为完整 GPU Droplet 实例小时价，按明确 1 / 8 卡数分摊；按需与 Spot、风冷 / 液冷变体分开；保留 `source_last_verified` 文档日期，不当生效日。
- Verda：USD / EUR 分别抓取且核验选中币种；表格与 JSON-LD 核对完整实例小时总价，按明确卡数分摊，原实例资源和金额保留；不混入 Reserved 等其他产品。
- Azure：固定四个 GPU SKU 的公开基础 VM `Consumption` 主计量地区 USD 费率；按明确 GPU 数分摊，保留 `azure_meter` 和 `effective_from`。分页完整后才解析，按需 / Spot 分开；国家仅由官方地区目录的明确映射关联，未知为空；不推断 zone。

有效账号询价及登录市场的成功联调情况以 [文档对照](DOCUMENT_COVERAGE.md) 为准，合成测试不代表实时取价成功。

Azure 国家映射并非完整：当相关记录仍有未知国家，单独请求国家会返回 `unverifiable_filter`；可联合已核验地区限定相关集合，例如 `--country US --region eastus`。未知位置不能静默当作无匹配。
