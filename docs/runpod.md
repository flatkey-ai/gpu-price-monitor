# RunPod 公开报价与地区查询

采集不需要登录、API key 或付费，不创建实例。价格接口是官方匿名 GraphQL：
[`https://api.runpod.io/graphql`](https://graphql-spec.runpod.io/)，官网对照页为
[GPU pricing](https://www.runpod.io/pricing)。程序执行固定只读 query，不调用大模型。

## 两种范围

- `standard`：读取 GPU Pods 的 Secure / Community 按需目录。只保留启用云档位、正数费率和整卡，地区与库存保持未知。
- `complete`：保留目录，并为国家已经核实的每个数据中心查询 **1 GPU** 的 `lowestPrice`。Secure 和 Community 独立查询，不把目录价格复制到机房。

从 0.26.5 起，目录的同一次匿名请求还读取 Secure / Community 各自的全局单卡 `lowestPrice`。只有该档位返回正数价格、`Low` / `Medium` / `High` 库存，且价格与同一响应中的目录价精确相等时，才给该目录行附加 `resources.resource_basis=minimum`、已提供的 `vcpus` / `memory_gb`，并明确 `gpu_count=1`。`conditions.quote_request` 保存 `gpuCount=1` 和 `secureCloud`；CPU/RAM 是这个单卡请求的独立最低值，不是某台已选中机器的确定配置，也不代表可乘卡数。

这项补充不替换目录价格，不提升目录的 `availability=unknown`，也不创建新的机器报价或地区绑定。差价、空价格、无货或缺最低硬件时，原目录行保持未知；不得把 Secure 的硬件填到 Community，或把新读取的硬件拼到历史价格上。存储不在该响应中，保持未提供；不采用创建默认容量。地区起价继续使用自己的请求与最低硬件，不能继承全局参考值。

下游聚合必须保留同一原生 SKU 的云档位和卡数边界；例如不同档位同名 GPU 的最低价格与硬件不能拼成一台不存在的机器。只读取目录的页面无需新增逐行实时查询。

Python 示例：

```python
from datetime import datetime, timezone
from gpu_price_monitor.providers.runpod import collect_result
from gpu_price_monitor.settings import Settings

result = collect_result(
    settings=Settings(providers=("runpod",), catalog_scope="complete"),
    observed_at=datetime.now(timezone.utc).isoformat(),
)
```

CLI 可在 env 中设置 `GPU_PRICE_MONITOR_CATALOG_SCOPE=complete`，然后执行：

```sh
gpu-price-monitor collect --providers runpod --pretty > runpod.json
gpu-price-monitor collect --providers runpod --format csv --csv-profile full > runpod.audit.csv
```

## 国家和价格证据

`dataCenters { id name location }` 来自 [RunPod 官方 CLI 的公开查询实现](https://github.com/runpod/runpodctl/blob/dd55bcff14ef1faadeb27c8f08edfeb8795e026f/internal/api/gpu.go)。程序只把 `location` 的明确国家名称映射为 ISO 国家码。例如 `India` → `IN`；不会根据 `AP-IN-1` 等代码猜国家。`Europe`、`SE Asia` 等洲级信息在 `coverage.country_unverified_data_centers` 中列为排除项。

每个机房的查询明确绑定 `dataCenterId`、`gpuCount=1`、`secureCloud`，原请求保存在 `conditions.quote_request`。返回的 `countryCode` 若与数据中心国家冲突，则拒收该机房结果；返回空值不会删除已核实的请求绑定。国家证据保存在 `location_source`。

`lowestPrice` 是该范围的最低可用起价，不是完整机器配置报价。程序设置 `quote_status=starting_at`、`price_basis=starting_price`，保留来源的最低 CPU / RAM 字段，不把这些独立最小值当作某台机器的精确配置。地区起价进入完整审计 JSON / CSV；要求确定报价的 compact / market 表不会把它混入普通价最低值。

## 2026-10-23 实采

本轮发现 52 个数据中心，其中 38 个返回明确国家，覆盖 6 个国家；38 个均已查询，另 14 个只有洲级位置，明确排除。取得 **67 条目录报价及 34 条地区起价**；2,512 个机房 / SKU / 云档位组合没有报价，不解释为免费、下线或全球统一价。

- B300 Secure：美国 `US-WA-2`，$8.99 / GPU-hour。
- H200 SXM Secure：日本 `AP-JP-1`、法国 `EU-FR-1` 及部分美国机房，$5.29 / GPU-hour。
- H200 SXM 目录的 Community $3.59 与 Secure $5.29 是不同云档位；Community 不代表会员价。

以上是该次观测，不是运行时备用价格。实际费率、库存和机房列表均在每次运行时读取。

## 范围与失败处理

只查询 GPU Pods 按需整卡，不包含 MIG、Serverless、集群、Spot、预付 Savings Plans 或未公布合同。完整模式只询单卡最低可用价，不宣称遍历全部多卡配置。存储另外收费。官方 [Pod 计费文档](https://docs.runpod.io/pods/pricing)列出的 Savings Plans 是 3 / 6 月预付承诺，不能当作会员折扣。

完整模式最多接受 64 个数据中心；每中心一次请求，同时查询两个云档位，加两次目录发现请求。每次 HTTP 最多 20 秒、无自动重试，总预算 180 秒；429 会停止后续查询。失败时 `collect_result` 保留已验证结果并返回 `partial`、`errors` 和覆盖计数，不回填旧价格。`collect_quotes` 在完整模式遇到部分失败会抛错，避免只返回价格列表时隐藏缺口。

新版 [REST 数据中心 API](https://docs.runpod.io/api-reference-v2/catalog/list-data-centers)需要认证，本实现不调用它，也不读取任何其他厂商凭据。

## 完整配置核查的边界

2026-10-23 读取[官方部署页](https://console.runpod.io/deploy?gpu=H200+SXM)发布的客户端查询后，确认其 `FullSecureGpuTypes`、`FullCommunityGpuTypes`、`GetGpuPrice` 也使用 `gpuTypes.lowestPrice`。查询会带卡数、云档位、数据中心及最低 CPU / 内存条件；结果包含最低 CPU / 内存、可用卡数和机房信息，没有可枚举的市场机器清单或完整确定规格。因此，本实现的 101 条目录 / 起价不能宣称为所有可选配置的确定报价。

同日 07:14 UTC 对法国 `EU-FR-1` 的 H200 SXM 使用该部署页原始 `GetGpuPrice` 只读查询：1 卡返回 $5.29 / 小时，最低 24 vCPU / 377 GB 内存；2、4、8 卡均返回空价格并标为不可用。空结果不会用 1 卡价格乘卡数补齐，最低硬件字段也不当作完整配置。该实测仅核查公开查询的行为，不增加运行时样例价格。

若后续继续核查登录视角，需要用户授权单独的 RunPod 登录会话或只读 API key。入口为 [Credentials](https://console.runpod.io/user/credentials)，在 API Keys 中创建 `Read Only`，或按[官方凭据说明](https://docs.runpod.io/get-started/credentials)选择最小只读权限。登录和 API key 可能让产品页读取更多账号可见信息，但官方 [GPU catalog API](https://docs.runpod.io/api-reference-v2/catalog/list-gpu-types)文档仍是型号价格与可用性目录；不能事先承诺它会提供完整机器报价。不得为取价启动 Pod。
