# 原始 Word 需求与当前实现对照

对照版本：0.12.0，日期：2026-10-21。需求来源为用户提供的《GPU云算力_价格入口与API核查_2026-10-10.docx》（报告日期 2026-10-10）。该文件只核查 **Nebius、Lambda、Crusoe、AutoDL、UCloud** 五家。0.7.0 曾按该范围实现；根据用户随后扩大平台的要求，0.8.0 在保留这五家的基础上新增 RunPod、DigitalOcean、Verda、Azure，`all` 当前共九家。新增平台不是原 Word 已核查事项，依据与限制另列。文档里的接入建议用于明确需求与验证边界，不将其中的接口示例值或错误响应当成真实报价。

原需求：监控 GPU 云主机 / 容器价格，支持 API 与页面来源，地区 / 国家变化时保留筛选条件，向调用方返回可追溯价格。后续用户明确要求纯免费默认、开源可 clone、Python 调用及 CLI JSON，0.9.0 新增可选 CSV，0.11.0 将默认 CSV 收紧为 10 列真实地区 GPU 小时比较表，原 51 列通过 full profile 审计。0.12.0 按用户要求优先调用接口，由代码完成采集，不依赖 Codex 或 LLM；用户允许 Crusoe / AutoDL 用程序解析官网补齐。调度、存储、上传、换汇和比价属于调用方，未放入本库。

## 五家执行方式与 API 边界

推荐独立命令：

```bash
gpu-price-monitor collect --providers nebius,lambda,crusoe,autodl,ucloud --source-policy api_preferred --pretty
```

Python 对应 `collect_prices(["nebius", "lambda", "crusoe", "autodl", "ucloud"], settings=Settings(source_policy="api_preferred"))`。环境变量 `GPU_PRICE_MONITOR_SOURCE_POLICY=api_preferred` 可通过 `Settings.from_env()` 或 CLI `--env-file` 显式加载。可 `cp .env.five.example .env.five.local` 后使用 `--env-file .env.five.local`，无需覆盖已有 `.env`。没有模型调用、模型 API Key 或 Codex 运行时依赖；AutoDL 的固定 DOM 采集需要免费的本地 Chromium。

| 五家 | `api_preferred` 选择 | 不能据此宣称的能力 |
| --- | --- | --- |
| Nebius | public 只调用匿名当前 Spot API；显式 `api` 走账号完整配置估价 | Spot 不等于普通按需；仅配置 token 不自动启用估价，也不枚举全 SKU |
| Lambda | 有 `LAMBDA_API_KEY` 用官方 instance-types API；无 key 选公开页固定规则 | API 的容量地区不等于地区价格；没有有效 key 的离线测试不等于认证实采 |
| Crusoe | 固定 HTML 规则读取官方 GPU instances 区块 | 仍未找到可核实的公共 GPU VM 价目 API；账单、预留合同和 Foundry 模型部署不是该价目 |
| AutoDL | Playwright 固定 DOM 规则读取普通 / 会员价；显式 market 保留授权市场 | Pro / 弹性部署的已有资源价格不等于市场价；首页不提供完整价格位置 |
| UCloud | 任一公私钥有配置时要求完整账号询价；无账号密钥用匿名活动 API | 匿名月包不变成小时价；无完整双密钥和 targets 不宣称小时询价成功 |

`source_policy=configured` 为兼容默认，保持各 `*_SOURCE` 配置，不自动切换账号分支；`api_preferred` 才采用上表策略。`api_only` 仅允许价格接口，Crusoe / AutoDL 等页面来源明确返回 `api_price_source_unavailable`，不静默抓网页。显式 API 的配置、鉴权和响应格式错误都直接失败，不用公开页、旧快照或示例数字兜底。

结果顶层 `execution` 明确 Python / 固定规则 / 不使用 LLM / 所选策略；每个来源返回实际 `source_type`、`collection_method`、`selection_reason` 及适用时的 `fallback_reason`，区分 JSON 接口、HTTP 页面 / 文档和浏览器 DOM。兼容策略 Nebius 的文档 / API 混合路径单独标 `hybrid_http`。**五家有原始采集路径，不代表五家都有合格的地区每 GPU 小时报价**；比较 CSV 仍按下述位置、单位及状态规则筛选。

## 已真实采集到什么

**0.11.0 于 2026-10-21T08:45:38.349457Z** 九家匿名实采得到 845 条来源记录，其中 **224 条满足默认地区 GPU 小时比较条件**：Nebius 当前 Spot 12、Azure 212，见 [10 列原币比较样本](../examples/regional-hourly-2026-10-21.csv)。其他七家该批免费来源缺少完整价格位置或仅有下线月包，未进入比较表。采集成功、比较条件成立和即时可购是不同事实；该历史批次不能证明新策略的认证路径已成功联调。

[nine-providers-2026-10-21.json](../examples/nine-providers-2026-10-21.json) 是 0.10.0 于北京时间 15:12:56 取得的 833 条历史宽表来源记录，尚未包含新增 Nebius 当前地区 Spot API；当时 Azure 国家映射仍有 14 条未知。0.11.0 已扩充核验映射，当前 214 条 Azure 中仅 `sgxsingapore1` 两条国家未知。这份旧 JSON 不代表当前比较结果，以下五家表也仅保留原 Word 范围的历史验收证据。

[five-providers-2026-10-21.json](../examples/five-providers-2026-10-21.json) 是原五家公开来源的历史真实返回，`collected_at=2026-10-21T06:35:03.737019+00:00`，即北京时间 **2026-10-21 14:35:03**。这表示本次请求观察时间，不是五家页面的发布或价格生效时间。

| 平台 | 记录数 | 原始价格口径 | 地理证据与可用性 |
| --- | ---: | --- | --- |
| Nebius | 36 | USD / ILS，GPU 小时组件价，按需 / Spot，CPU / RAM 另列 | 36 条仅平台覆盖 `platform_coverage`；不是各国家独立价，库存未知 |
| Crusoe | 24 | USD / GPU / 小时；含 Contact sales 空金额 | 价格地区未公布；不保证库存或购买资格 |
| Lambda | 22 | USD / GPU / 小时，保留 1 / 2 / 4 / 8 卡完整配置 | 价格地区未公布，库存未知 |
| AutoDL | 24 | CNY / GPU / 小时，普通 / 会员各 12 条 | 首页目录未公布价格地区，会员资格未验证 |
| UCloud | 374 | CNY 月套餐，保留整机月价与每卡月价 | 官方目录绑定中国 / region / zone；374 条均为 `offline` |

总计 480 条；其中 374 条有明确中国位置但已下线，36 条只有平台覆盖，70 条没有价格位置。不能把全部记录称为“全地域最新可购价”，也不能将询价条目、会员价、GPU 分项或月包直接放在同一小时最低价榜。

## 按原文逐家对照

| Word 核查事项 | 当前实现 | 实际验证边界 |
| --- | --- | --- |
| Nebius 公开页；Estimate Batch 需要完整资源、币种、聚合单位、offerTypes 与 Bearer token | 接口优先的 public 只取免费当前地区 Spot API；兼容策略仍合并文档。可选 `api` 核验项目地区、国家、完整配置和金额 / 单位 | Spot API 已匿名实采；账号估价只有合成测试，未取得有效 token 的真实成功返回 |
| Lambda instance-types 的美分整机价应按 GPU 数分摊；容量地区不能当价格地区 | 接口优先时有 key 走 API，无 key 用已实采公开页；保留整实例价、卡数及 `capacity_regions` | API 离线样本验证；尚未成功认证联调。原报告的匿名 401 是失败证据，不是报价 |
| Crusoe VM types 无价格；Billing / 托管推理报价不能当公共 VM 租价 | 程序固定规则采 GPU instances 独立区块，按需 / Spot、起价及 Contact sales 分开；严格 API 模式明确不支持 | 2026-10-21 重新核查官方 OpenAPI 170 路径，未发现合适公共 VM 租价 API；没有将账单或模型部署价格代替 |
| AutoDL 已有资源 API 与完整市场不同，单位不明不能硬换算 | 固定 DOM 采首页普通 / 会员价；授权 `market` 读取显示的价格 / 单位及地区，未接已有资源快照接口 | 市场有合成测试，需有效 storage state，尚未成功登录实抓。首页成功不证明市场已实测 |
| UCloud 签名配置询价，完整 CPU / RAM / 磁盘 / GPU / 地区；RetCode 才判业务成功 | 接口优先有密钥时要求完整账号小时 targets；无密钥走已实采匿名月包 API。每次询价核验官方位置目录 | 账号询价有离线样本测试，尚未成功认证询价。原报告的 HTTP 200 / RetCode 170 不是价格成功 |

官方入口和实现细节见 [PROVIDERS.md](PROVIDERS.md)。

## 国家 / 地区能力没有被“填齐”

| 来源模式 | 国家筛选 | 地区筛选 | 可用区筛选 | 返回的范围 |
| --- | --- | --- | --- | --- |
| Nebius public 文档 | 仅 `coverage_countries` | 仅 `coverage_regions` | 不支持 | `platform_coverage`，不参与真实地区价格结论 |
| Nebius public 当前 Spot | 官方目录映射；未知不补 | 当前 API 返回的实际 region | 不支持 | `regional_quote`，保留原币与生效时间 |
| Nebius api | 项目地区 + 官方国家映射核验 | 目标与项目地区必须一致 | 当前不支持 | `requested_region_quote`，账号配置估价 |
| Lambda public / api | 不支持 | 不支持 | 不支持 | 未定位目录；API 容量地区另存 |
| Crusoe public | 不支持 | 不支持 | 不支持 | 未定位目录 |
| AutoDL public | 不支持 | 不支持 | 不支持 | 未定位普通 / 会员目录 |
| AutoDL market | 不支持 | 市场原始地区代码 | 不支持 | 地区市场挂牌，登录态与真实成功验证仍缺 |
| UCloud public | 官方国家代码 | 官方地区 | 官方可用区 | 具体促销套餐，保留下线状态 |
| UCloud api | 官方目录核验 | 指定完整配置地区 | 指定配置 zone | `requested_zone_quote`，账号配置询价 |
| RunPod public | 不支持 | 不支持 | 不支持 | 未定位云档位目录 |
| DigitalOcean public | 不支持 | 不支持 | 不支持 | 未定位完整实例表 |
| Verda public | 不支持 | 不支持 | 不支持 | 未定位双原币完整实例表 |
| Azure public | 官方目录已核验映射；未知为空 | 价格响应 ARM region | 不支持 | 四固定 SKU 的 `regional_quote` |

`compute_countries` 是部署国家，不是销售国家；当前不支持 `sales_countries`。国家 / 地区 / zone 组合要在同一条报价内匹配。不支持的维度报 `unsupported_filter`；支持但无足够证据报 `unverifiable_filter`。未知位置保持未知，不补成 global；不由币种、IP、平台总部或容量列表推断国家。`--country` / `--region` 只筛实际价格位置，文档覆盖另用 `--coverage-country` / `--coverage-region`；缺少地区字段不证明全球统一价。

## 原文强调的价格口径如何保留

| 要求 | 实现约定 |
| --- | --- |
| 实例价与每 GPU 价 | `price_basis` 标明公开每卡、GPU 组件或整机分摊；来源整机价保留 `instance_price`，不把多卡实例总价误作单卡价 |
| 原始币种与计费周期 | `amount` 字符串、`currency`、`unit`、`billing_mode` 分开；保留 `gpu_hour` / `gpu_month`，无自动 USD 或 720 小时换算 |
| 配置与规格 | 原始 GPU 名称 / SKU、卡数、显存与硬件变体、CPU / 内存 / 磁盘及单位在来源提供时保存；未知字段不猜测 |
| 折扣和购买条件 | 普通 / 会员、账号合同、Spot 起价、促销限购、原价、资格与续费说明单列；不把试用当通用牌价 |
| 发布时间、生效时间和采样时间 | `observed_at` / `collected_at` 记录采样；仅来源明确时填写 `effective_from` / `effective_until`；Nebius 按明确日期区间取适用价，其余缺失不伪造 |
| 询价与不可用 | Contact sales 保持空金额；`offline` 保留；挂牌和认证估算不证明库存、配额、账号购买资格或最终结算总价 |
| 请求失败 | 无效结构、单位、币种、配置与鉴权错误结构化返回；不以 0 或旧样本兜底，单平台失败不抹去其他平台成功结果 |
| 使用者可自行部署 | 源码安装、Python API、默认 CLI JSON / 可选严格 10 列 CSV；`prices_to_csv(result, profile="full")` / `--csv-profile full` 保留原 51 列审计表；显式 `.env` 与 targets，不内置业务上传目标或凭据 |

## 凭据与尚不能验证的部分

公开九家采集不需要凭据；AutoDL 的浏览器依赖是本地免费软件。`api_preferred` 会根据 Lambda / UCloud 的已配置密钥选择认证来源；只有一把 UCloud 密钥时不会静默降级。账号模式需要调用者自行拥有供应商权限，配置见 [.env.example](../.env.example)：

- Nebius：`NEBIUS_SOURCE=api`、IAM access token、1–20 项完整 targets。只支持已核验平台 / 预设映射，小时 / 月聚合与公开 / 合同口径分开；不枚举全市场，也不自动续 token。
- Lambda：API key，搭配 `api_preferred` 或显式 `LAMBDA_SOURCE=api`；目录的 capacity 只说明容量，不能补出逐国家价。
- UCloud：公私钥及 1–20 项完整小时 targets，搭配 `api_preferred` 或显式 `UCLOUD_SOURCE=api`。当前目标限定 GPU 云主机、单台、Dynamic；不是包月 / 包年 / 裸金属全规格采集器。官方位置目录核验不等于响应回显了全部部署条件或现货。
- AutoDL：`AUTODL_SOURCE=market` 与授权 `AUTODL_STORAGE_STATE_PATH`。只读按量市场；不创建实例，不用已有资源 API 凑市场价格。会话失效会报错而非退回首页。

这些分支的合成测试证明解析、配置与失败路径，不证明服务商已允许当前账号调用。现阶段不能承诺九家全国家、全配置、全会员 / 合同、全库存覆盖。需要有效账号的只读成功响应才能进一步核验账号价与真实市场结构；本次未为取价购买 GPU、创建资源或读取私钥文件。

Crusoe 当前没有可配置后即可取到公共 GPU VM 地区价的已核实接口，AutoDL `AUTODL_TOKEN` 也不会将已有资源 API 变成市场价目。不能以“已实现适配器”代替有效账号的真实成功返回。

日期 JSON 是固定历史证据，不是持续更新价目表或运行时缓存。其他版本更大范围的旧样本见 [examples/README.md](../examples/README.md)，不代表当前版本支持旧版全部适配器。


## 原 Word 之外的 0.8.0 扩展

| 新增平台 | 免费来源与金额口径 | 位置与范围限制 |
| --- | --- | --- |
| RunPod | 匿名官方 GraphQL GPU Pods；Secure / Community 分开，USD / GPU / 小时 | 无价格绑定地区；未报价、禁用档位、MIG / vGPU 不当完整 GPU 价格 |
| DigitalOcean | 官方 GPU 文档；按需 / Spot 整实例价按明确 1 / 8 卡数分摊 | 未给价格地区或显存；B300 Spot 不当普通价，文档核验日期不是价格生效日期 |
| Verda | 分别请求 USD / EUR GPU instances 表；JSON-LD 核对整实例单位，按需 / Spot 分开 | 未给价格地区；不是库内换汇，不采 Reserved / Instant clusters 等其他条款 |
| Azure | 匿名 Retail Prices API；已生效的基础 VM USD 按需 / Spot 地区费率 | 当前四固定 SKU（T4 / GB200 / H100 NVL / A100 PCIe）；全部分页核验完成，国家仅用官方地区目录已核验映射，不推断 zone 或实时容量 |

新增平台均不需要账号凭据或资源购买；实际观察证据见九家 JSON，官方链接和完整解析限制见 [PROVIDERS.md](PROVIDERS.md)。这些扩展不改变原五家可选认证路径尚缺有效账号成功验证的结论。


## 0.11.0 比较验收

默认比较表要求实际 quoted 数值、每 GPU 小时单位、已核实价格范围、非空国家与 region；未知地区、文档覆盖、起步价、GPU 组件、月包、询价与明确不可用项不进入比较表。原记录仍在 JSON / full 审计表中；不按 720 小时换算月价，不换汇，不上传。CLI stderr 提示保留 / 排除条数，来源成功但没有合格报价时仅表头，退出码仍反映来源状态。

Nebius 2026-10-21 08:00 UTC 截图中 B200 `me-west1` 4.10 与 `us-central1` 1.90 USD/GPU/hour 是历史 Spot 最后价，不是普通按需或固定现价；当前匿名接口提供实际地区价格与生效时间，截图数值不硬编码。官方依据见 [Spot 获取与历史聚合说明](https://docs.nebius.com/signup-billing/spot-prices)。
