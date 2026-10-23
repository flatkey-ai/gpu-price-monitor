# Azure 公开地区小时报价

采集使用微软匿名 [Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)，不需要 Azure 账号或 API key，不创建资源。每个型号按精确 `armSkuName`、基础 VM `productName` 和 `Consumption` 条件请求；报价的地区直接来自该条 API 记录。

## 当前规格范围

程序支持下列 17 个整卡 VM 规格。CPU、内存、卡数取自链接中的微软规格表；不同 CPU / 内存配置保持独立记录。所有价格均每次请求 API 获取，没有将单卡价格乘算成未知多卡报价。

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

A10 的 1/6、1/3、1/2 分卡规格不混入整卡对比；整卡 A10 记录标明包含 NVIDIA GRID 许可证。MI300X 的 `vram_gb=192` 来自官方单加速器标称规格，官方 VM 总量表另列 1,535 GB，程序不把这两个不同口径混算。当前没有核实 Azure B200 的精确 VM SKU 与公开零售计价记录，未将 GB200 冒充 B200。

## 地区、计费与可靠性

- `instance_price` 保留 API 原始整机 USD / 小时价格，`amount` 为其除以官方卡数所得 USD / GPU-hour，CPU 与内存仍属于完整 VM 配置。
- 按需和 Spot 独立输出。只保留已经生效的主计价项；旧版本、新未来生效价格、Windows 产品、Low Priority、预留实例和嵌套 Savings Plan 不混入按需价。
- 国家只从官方地区文档与精确地区标识的已核实映射读取，保留 `location_source`。未知地区仍在完整审计中，但不会进入严格地区 CSV；不能根据标识前缀推测国家。
- 公开零售价不证明账户配额、当前库存或区域可购买性。托管磁盘、网络等另外收费，也不推测税费。整机包含的本地硬件以官方规格页为准。
- 每个 SKU 最多读取 5 页、每页最多 1,000 条；续页只能回到固定微软域名并保持原查询条件。某个 SKU 无有效报价或分页不完整时明确报错，不补历史价或返回不完整集合冒充成功。

## 2026-10-23 实际验证

17 个 SKU 均请求成功，共 954 条小时报价：485 条按需、469 条 Spot，覆盖 54 个地区。其中 950 条具备国家证据，覆盖 27 个国家/地区；`sgxsingapore1` 的 4 条报价缺少已经核实的国家映射，严格地区表排除。实采验证使用最多 3 并发、180 秒预算，实际约 6.5 秒完成；这仅描述本次运行，不是后续数量或延迟保证。

例如美国 `westus3`：8 卡 MI300X 整机 $48 / 小时、分摊 $6 / GPU-hour；8 卡 H100 整机 $98.32 / 小时、分摊 $12.29 / GPU-hour。这些只是本次 API 观测，不是代码中的备用价格。

```sh
gpu-price-monitor collect --providers azure --pretty > azure.json
gpu-price-monitor collect --providers azure --format csv --csv-profile compact > azure.regional.csv
```

Python 使用 `gpu_price_monitor.providers.azure.collect_quotes(settings=Settings(), observed_at=...)` 或项目统一采集接口。输出带精确 SKU、硬件来源、计价记录 ID、观测时间和价格生效时间，便于逐条回查。
