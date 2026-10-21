# 原始 Word 需求与当前实现对照

对照版本：0.8.0，日期：2026-10-21。需求来源为用户提供的《GPU云算力_价格入口与API核查_2026-10-10.docx》（报告日期 2026-10-10）。该文件只核查 **Nebius、Lambda、Crusoe、AutoDL、UCloud** 五家。0.7.0 曾按该范围实现；根据用户随后扩大平台的要求，0.8.0 在保留这五家的基础上新增 RunPod、DigitalOcean、Verda、Azure，`all` 当前共九家。新增平台不是原 Word 已核查事项，依据与限制另列。文档里的接入建议用于明确需求与验证边界，不将其中的接口示例值或错误响应当成真实报价。

原需求：监控 GPU 云主机 / 容器价格，支持 API 与页面来源，地区 / 国家变化时保留筛选条件，向调用方返回可追溯价格。后续用户明确要求纯免费默认、开源可 clone、Python 调用及 CLI JSON；调度、存储、上传、换汇和比价属于调用方，未放入本库。

## 已真实采集到什么

**2026-10-21 15:12:56（北京时间）九家公开实抓成功，共 833 条**：Nebius 36、Crusoe 24、Lambda 22、UCloud 374、AutoDL 24、RunPod 68、DigitalOcean 19、Verda 52、Azure 214。574 条有已核验国家关联，588 条有价格地区 / 可用区，其中 UCloud 374 条全部下线；36 条仅平台覆盖，209 条未定位目录。Azure 214 条覆盖 45 个价格地区，其中 14 条国家未知。以上不是全地域可购库存。 当前九家公开采样见 [nine-providers-2026-10-21.json](../examples/nine-providers-2026-10-21.json)。以下五家表保留为原 Word 范围的历史验收证据，不能当成 0.8.0 全量条数。

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
| Nebius 公开页；Estimate Batch 需要完整资源、币种、聚合单位、offerTypes 与 Bearer token | 默认公开文档已实抓；可选 `api` 估价适配器已实现项目地区 GET 核验、国家映射、完整配置和金额 / 单位核对 | 新 API 分支 14 项合成测试；未取得有效 token 的真实成功返回，不保证模板配置在账号中可售 |
| Lambda instance-types 的美分整机价应按 GPU 数分摊；容量地区不能当价格地区 | 默认公开页已实抓；可选 API 保留原实例价、卡数与 `capacity_regions`，不填逐地区价 | API 离线样本验证；尚未成功认证联调。原报告的匿名 401 是失败证据，不是报价 |
| Crusoe VM types 无价格；Billing / 托管推理报价不能当公共 VM 租价 | 已采 GPU instances 独立区块，按需 / Spot、起价及 Contact sales 分开 | 公开页实抓成功；没有确认或实现公共 VM 全价格 API，也未读取账号账单 |
| AutoDL 已有资源 API 与完整市场不同，单位不明不能硬换算 | 免费首页已实抓普通 / 会员价；新增授权 `market` 读取市场显示的价格 / 单位及地区，未接已有资源快照接口 | 市场 8 项合成测试；需用户有效 storage state，尚未成功登录实抓。首页结果不证明市场已实测 |
| UCloud 签名配置询价，完整 CPU / RAM / 磁盘 / GPU / 地区；RetCode 才判业务成功 | 默认匿名月包已实抓；可选 `api` 完整小时目标、客户端签名、整实例分摊；每次采集核验官方位置目录，已开放国家筛选 | API 离线样本验证，尚未成功认证询价。原报告的 HTTP 200 / RetCode 170 不是价格成功 |

官方入口和实现细节见 [PROVIDERS.md](PROVIDERS.md)。

## 国家 / 地区能力没有被“填齐”

| 来源模式 | 国家筛选 | 地区筛选 | 可用区筛选 | 返回的范围 |
| --- | --- | --- | --- | --- |
| Nebius public | 不支持 | 来源覆盖代码 | 不支持 | `platform_coverage`，不参与真实地区价格结论 |
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

`compute_countries` 是部署国家，不是销售国家；当前不支持 `sales_countries`。国家 / 地区 / zone 组合要在同一条报价内匹配。不支持的维度报 `unsupported_filter`；支持但无足够证据报 `unverifiable_filter`。未知位置保持未知，不补成 global；不由币种、IP、平台总部或容量列表推断国家。

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
| 使用者可自行部署 | 源码安装、Python API、CLI JSON、显式 `.env` 与 targets；不内置 Flatkey 专属上传目标或用户凭据 |

## 凭据与尚不能验证的部分

公开九家采集不需要凭据；AutoDL 的浏览器依赖是本地免费软件。可选认证模式需要调用者自行拥有供应商账号权限，配置见 [.env.example](../.env.example)：

- Nebius：`NEBIUS_SOURCE=api`、IAM access token、1–20 项完整 targets。只支持已核验平台 / 预设映射，小时 / 月聚合与公开 / 合同口径分开；不枚举全市场，也不自动续 token。
- Lambda：`LAMBDA_SOURCE=api` 与 API key；目录的 capacity 只说明容量，不能补出逐国家价。
- UCloud：`UCLOUD_SOURCE=api`、公私钥及 1–20 项完整小时 targets。当前目标限定 GPU 云主机、单台、Dynamic；不是包月 / 包年 / 裸金属全规格采集器。官方位置目录核验不等于响应回显了全部部署条件或现货。
- AutoDL：`AUTODL_SOURCE=market` 与授权 `AUTODL_STORAGE_STATE_PATH`。只读按量市场；不创建实例，不用已有资源 API 凑市场价格。会话失效会报错而非退回首页。

这些分支的合成测试证明解析、配置与失败路径，不证明服务商已允许当前账号调用。现阶段不能承诺九家全国家、全配置、全会员 / 合同、全库存覆盖。需要有效账号的只读成功响应才能进一步核验账号价与真实市场结构；本次未为取价购买 GPU、创建资源或读取私钥文件。

日期 JSON 是固定历史证据，不是持续更新价目表或运行时缓存。其他版本更大范围的旧样本见 [examples/README.md](../examples/README.md)，不代表 0.8.0 支持旧版全部适配器。


## 原 Word 之外的 0.8.0 扩展

| 新增平台 | 免费来源与金额口径 | 位置与范围限制 |
| --- | --- | --- |
| RunPod | 匿名官方 GraphQL GPU Pods；Secure / Community 分开，USD / GPU / 小时 | 无价格绑定地区；未报价、禁用档位、MIG / vGPU 不当完整 GPU 价格 |
| DigitalOcean | 官方 GPU 文档；按需 / Spot 整实例价按明确 1 / 8 卡数分摊 | 未给价格地区或显存；B300 Spot 不当普通价，文档核验日期不是价格生效日期 |
| Verda | 分别请求 USD / EUR GPU instances 表；JSON-LD 核对整实例单位，按需 / Spot 分开 | 未给价格地区；不是库内换汇，不采 Reserved / Instant clusters 等其他条款 |
| Azure | 匿名 Retail Prices API；已生效的基础 VM USD 按需 / Spot 地区费率 | 当前四固定 SKU（T4 / GB200 / H100 NVL / A100 PCIe）；全部分页核验完成，国家仅用官方地区目录已核验映射，不推断 zone 或实时容量 |

新增平台均不需要账号凭据或资源购买；实际观察证据见九家 JSON，官方链接和完整解析限制见 [PROVIDERS.md](PROVIDERS.md)。这些扩展不改变原五家可选认证路径尚缺有效账号成功验证的结论。
