# Azure 公开地区小时报价

采集使用微软匿名 [Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)，不需要 Azure 账号或 API key，不创建资源。每个型号按精确 `armSkuName`、基础 VM `productName` 和 `Consumption` 条件请求；报价的地区直接来自该条 API 记录。

## 当前规格范围

程序支持下列 26 个整卡 VM 规格。CPU、内存、卡数取自链接中的微软规格表；不同 CPU / 内存配置保持独立记录。所有价格均每次请求 API 获取，没有将单卡价格乘算成未知多卡报价。这是已核实的整卡目录，不代表 Azure 所有历史、分卡和未公开计价规格。

| 官方系列与来源 | 精确 VM 规格（均以 `Standard_` 开头） | GPU 数量 | vCPU | RAM GiB |
| --- | --- | ---: | ---: | ---: |
| [T4 NCasT4 v3](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ncast4v3-series) | NC4as_T4_v3 | 1 | 4 | 28 |
| 同上 | NC8as_T4_v3 | 1 | 8 | 56 |
| 同上 | NC16as_T4_v3 | 1 | 16 | 110 |
| 同上 | NC64as_T4_v3 | 4 | 64 | 440 |
| [A100 PCIe 80 GB NC A100 v4](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nca100v4-series) | NC24ads_A100_v4 | 1 | 24 | 220 |
| 同上 | NC48ads_A100_v4 | 2 | 48 | 440 |
| 同上 | NC96ads_A100_v4 | 4 | 96 | 880 |
| [A100 40 GB ND A100 v4](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ndasra100v4-series) | ND96asr_v4 | 8 | 96 | 900 |
| [A100 80 GB NDm A100 v4](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ndma100v4-series) | ND96amsr_A100_v4 | 8 | 96 | 1,900 |
| [H100 NVL 94 GB NCads H100 v5](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ncadsh100v5-series) | NC40ads_H100_v5 | 1 | 40 | 320 |
| 同上 | NC80adis_H100_v5 | 2 | 80 | 640 |
| [H100 80 GB ND H100 v5](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ndh100v5-series) | ND96isr_H100_v5 | 8 | 96 | 1,900 |
| [MI300X ND MI300X v5](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ndmi300xv5-series) | ND96isr_MI300X_v5 | 8 | 96 | 1,850 |
| [A10 NVadsA10 v5](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nvadsa10v5-series) | NV36ads_A10_v5 | 1 | 36 | 440 |
| 同上 | NV36adms_A10_v5 | 1 | 36 | 880 |
| 同上 | NV72ads_A10_v5 | 2 | 72 | 880 |
| [GB200 ND GB200 v6](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nd-gb200-v6-series) | ND128isr_NDR_GB200_v6 | 4 | 128 | 900 |
| [H200 141 GB ND H200 v5](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nd-h200-v5-series) | ND96isr_H200_v5 | 8 | 96 | 1,850 |
| [H100 NVL 94 GB 机密 VM](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nccadsh100v5-series) | NCC40ads_H100_v5 | 1 | 40 | 320 |
| [V100 NVLink 32 GB NDv2](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/ndv2-series) | ND40rs_v2 | 8 | 40 | 672 |
| [RTX PRO 6000 Blackwell Server Edition 96 GB](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nc-rtxpro6000-bse-v6-series) | NC144ds_xl_RTXPRO6000BSE_v6 | 1 | 144 | 516 |
| 同上 | NC288ds_xl_RTXPRO6000BSE_v6 | 2 | 288 | 1,032 |
| 同上，计算优化配置 | NC144lds_xl_RTXPRO6000BSE_v6 | 1 | 144 | 264 |
| 同上，计算优化配置 | NC288lds_xl_RTXPRO6000BSE_v6 | 2 | 288 | 516 |
| [AMD Radeon PRO V710 24 GB](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nvadsv710-v5-series) | NV24ads_V710_v5 | 1 | 24 | 128 |
| 同上 | NV28adms_V710_v5 | 1 | 28 | 160 |

A10 的 1/6、1/3、1/2 分卡规格不混入整卡对比；整卡 A10 记录标明包含 NVIDIA GRID 许可证。MI300X 的 `vram_gb=192` 来自官方单加速器标称规格，官方 VM 总量表另列 1,535 GB，程序不把这两个不同口径混算。当前没有核实 Azure B200 的精确 VM SKU 与公开零售计价记录，未将 GB200 冒充 B200。

2026-10-27 核查发现此前的 17 个规格白名单漏了上述 9 个已有公开零售价的规格，现已补入。H200、V100、RTX PRO 6000 和 Radeon PRO V710 保留各自型号，不与 H100、RTX 6000 Ada 或 GB200 合并。机密 H100 的 `conditions.confidential_vm=true` 与精确 SKU 一起保留。RTX PRO 6000 BSE、V710 的分卡配置仍不作为整卡报价。

[GB300 官方规格页](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nd-gb300-v6-series)已经列出 `Standard_ND128isr_GB300_v6`、`Standard_ND128isrG5_GB300_v6`；本次分别按精确 `armSkuName` 请求及按 `productName` 含 GB300 搜索，公开 Retail Prices API 均返回 `Count=0`、`NextPageLink=null`。因此没有生成 GB300 数字报价，也没有借用 GB200/B300 的价格。该结果只证明本次公开零售目录未返回这两项，不代表登录订阅或销售渠道一定没有价格。

## 地区、计费与可靠性

- `instance_price` 保留 API 原始整机 USD / 小时价格，`amount` 为其除以官方卡数所得 USD / GPU-hour，CPU 与内存仍属于完整 VM 配置。
- 按需和 Spot 独立输出。只保留已经生效的主计价项；旧版本、新未来生效价格、Windows 产品、Low Priority、预留实例和嵌套 Savings Plan 不混入按需价。
- 国家只从官方地区文档与精确地区标识的已核实映射读取，保留 `location_source`。未知地区仍在完整审计中，但不会进入严格地区 CSV；不能根据标识前缀推测国家。
- 公开零售价不证明账户配额、当前库存或区域可购买性。托管磁盘、网络等另外收费，也不推测税费。整机包含的本地硬件以官方规格页为准。
- 每个 SKU 最多读取 5 页、每页最多 1,000 条；续页只能回到固定微软域名并保持原查询条件。某个 SKU 无有效报价或分页不完整时明确报错，不补历史价或返回不完整集合冒充成功。

## 限流、重试与运行预算

常规定时采集按 SKU 顺序读取，两个 SKU 之间至少等待 1 秒，避免短时间集中请求。某页收到 HTTP 429 时只重试该页，每次先完整等待 60 秒；每页最多额外重试两次，并受 `Settings.max_retries` 的较小值限制。已经完成的 SKU 和分页不会重新扫描，不更换 IP、账号或请求域名绕过限流。这个间隔是采集程序的保守策略，不代表微软承诺的请求配额。

Azure 完整采集另设最多 300 秒的整批预算。`Settings.timeout_seconds` 仍表示单次 HTTP 超时，默认 30 秒，不会把包含 25 次 SKU 间隔的整批任务限制到 30 秒。每次请求的超时不超过剩余整批预算；调用 `collect_quotes(..., budget_seconds=...)` 可以明确设置更短的整批预算。时间不足以完整等待冷却时，直接以 `timeout` 失败，不缩短 60 秒等待后继续请求。

底层 HTTP 自动重试在 Azure 请求中关闭，防止一次限流叠加多层快速重试。网络超时、连接错误和可重试服务端错误仍按调用方的 `max_retries` 使用 1、2、4、最多 8 秒的短退避，且受同一整批预算约束；无效 JSON、字段结构、金额和分页错误不重试。

超过重试次数仍限流时返回 `rate_limited`；超出整批预算返回 `timeout`。两种情况都不会返回先前成功 SKU 构成的不完整集合。网站同步应将 Azure 标为本轮失败、保留其最后成功数据及原时间，其他平台继续更新；不能把保留的 Azure 报价标记为本轮新采集。

回归测试使用虚拟时钟验证：只重试失败续页、不重复已经完成的 SKU、完整冷却、重试上限、调用方关闭重试、预算耗尽、默认 30 秒单请求超时允许超过 30 秒的完整批次，以及结构／价格错误不重试。以下历史实采耗时仍仅代表对应日期的验证运行，不能用于推断当前节流策略的耗时。

2026-10-27 对上述策略进行了单轮匿名实采验收：26 个 SKU 均成功，26 次 HTTP 请求，共取得 1,266 条报价、10 个 GPU 型号，耗时 55.0 秒；本轮没有触发 429。该结果证明新节流策略可以完成当前目录读取，不能保证后续不会限流；429 冷却分支由虚拟时钟回归测试验证，没有向官网故意制造限流。

## 2026-10-23 实际验证

17 个 SKU 均请求成功，共 954 条小时报价：485 条按需、469 条 Spot，覆盖 54 个地区。其中 950 条具备国家证据，覆盖 27 个国家/地区；`sgxsingapore1` 的 4 条报价缺少已经核实的国家映射，严格地区表排除。实采验证使用最多 3 并发、180 秒预算，实际约 6.5 秒完成；这仅描述本次运行，不是后续数量或延迟保证。

例如美国 `westus3`：8 卡 MI300X 整机 $48 / 小时、分摊 $6 / GPU-hour；8 卡 H100 整机 $98.32 / 小时、分摊 $12.29 / GPU-hour。这些只是本次 API 观测，不是代码中的备用价格。

## 2026-10-27 扩容后的实际验证

26 个精确 SKU 均完成固定查询和分页校验，取得 1,266 条小时报价（641 条按需、625 条 Spot），覆盖 56 个地区；其中新增 9 个 SKU 带来 312 条报价。新增型号包括 H200、V100、RTX PRO 6000 Blackwell Server Edition、AMD Radeon PRO V710，另补了机密 H100 配置。并发数为 3，本次用时约 18 秒。`eastus3` 已由微软托管代理文档中的 `USGeographyRegions` 精确列表确认属于美国。`southcentralus2`、`sgxsingapore1` 保留 API 原始地区代码，国家未核实，因此不冒填国家。

本次 H200 的澳大利亚 `australiaeast` 按需记录为 8 卡 VM 整机 $122.96 / 小时，分摊 $15.37 / GPU-hour；这条价格来自该 SKU 自己的零售记录。回归测试保留新增 SKU 的真实公开响应片段；运行时仍重新请求官网 API，不读取测试响应兜底。

```sh
gpu-price-monitor collect --providers azure --pretty > azure.json
gpu-price-monitor collect --providers azure --format csv --csv-profile compact > azure.regional.csv
```

Python 使用 `gpu_price_monitor.providers.azure.collect_quotes(settings=Settings(), observed_at=...)` 或项目统一采集接口。输出带精确 SKU、硬件来源、计价记录 ID、观测时间和价格生效时间，便于逐条回查。
