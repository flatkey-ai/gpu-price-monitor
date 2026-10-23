# Nebius 与 Crusoe：价格和地区的证据

库运行时只用 Python HTTP 与固定规则，不调用 Codex 或其他模型，不启动或购买资源。

## Nebius

### 免费公开的当前 Spot 地区费率

```bash
gpu-price-monitor collect --providers nebius --nebius-source spot_api --source-policy api_only --format csv --csv-profile compact > nebius-regional.csv
```

金额来自 [当前 Spot API](https://api.nebius.cloud/billing/v1alpha1/spot-price)，每条包含平台、地区、生效时间、当前快照时间、币种和 GPU 小时单位。国家与地区名称由运行时读取的[官方地区目录](https://docs.nebius.com/overview/regions)校验。新地区无法核实国家时保留原始记录，排除完整地区主表；不从地区代码前缀猜国家。

Spot 是可抢占资源的动态费率，不能当作普通按需价。API 中的原始费率条数和按 preset 展开的计算行分别计数，不把计算行称为新增独立报价。

### 自动发现账号可访问的 GPU 规格后估价

复制 `.env.nebius.example` 为 `.env.nebius.local`，填写已有账号的 `NEBIUS_ACCESS_TOKEN`：

```bash
gpu-price-monitor collect --env-file .env.nebius.local --pretty > nebius-account.json
gpu-price-monitor collect --env-file .env.nebius.local --format csv --csv-profile compact > nebius-account.csv
```

Python 调用：

```python
from gpu_price_monitor import Settings, collect_prices, prices_to_csv

settings = Settings.from_env(env_file=".env.nebius.local")
result = collect_prices(settings=settings)
csv_text = prices_to_csv(result, profile="compact")
```

`NEBIUS_SOURCE=catalog_api` 按分页读取已有 tenant、project 和 platform/preset，再请求 [EstimateBatch](https://docs.nebius.com/rest-api/billing/v1/calculator/estimate-batch)。只估价，不调用项目、实例、磁盘、合同或密钥的创建接口。项目地区由官方返回值验证；只覆盖账号已有且有权限访问的项目。缺少项目的地区明确列为缺口，不复用其他地区金额。

主金额是 preset 的 **GPU / CPU / RAM 计算费 ÷ GPU 数量**，单位为每 GPU 每小时。默认另估 **40 GiB SSD**，可用 `NEBIUS_CATALOG_BOOT_DISK_GIB` 调整。同一个 EstimateBatch 中明确请求 VM 与独立磁盘资源，校验分项和聚合总价后分别返回：

- `amount`：每 GPU 小时计算费；`instance_price`：整实例计算费，范围为 `compute_resources_only`。
- `storage_quote`：磁盘每小时费用，未混入主 GPU 价格。
- `full_configuration_price`：该 VM 计算资源加一块指定磁盘的每实例小时合计。

磁盘、网络及税费不能默认为包含在主价中。官方估价不返回正数计算费、分项总和不一致或出现重复计费 SKU 时保留错误与缺口，不用磁盘费或零填成 GPU 价格。默认 `NEBIUS_CATALOG_CURRENCY=usd`，也支持 `ils`；库不做外汇换算。

**2026-10-22 14:21（北京时间）账号实采**：读取 9 个已有项目、9 个地区的 37 个 GPU preset，得到 36 条正数地区按需计算报价。GB300 NVL72 的计算 SKU 返回零，仅磁盘有费用，列为 `compute_tariff_unavailable`，不解释为免费 GPU。CPU preset 的零 GPU 数可以由 protobuf JSON 省略；程序明确排除 CPU，不把它们当漏抓的 GPU。

B300 的账号 API 返回单卡 270 GB，GB300 NVL72 返回 279 GB。程序以[官方 B300 产品页](https://nebius.com/self-service)和[GB300 产品页](https://nebius.com/compute/gb300)、官方规格样例交叉核对。旧 VM types 表的 B300 288 GB 与 API 不一致，冲突记录在 `identity_evidence.documentation_discrepancy`，不静默覆盖。发现新型号或新字段不代表可以直接套用旧规格。

**2026-10-23 14:11–14:19（北京时间）复核**：账号当前返回 39 个 GPU preset，已对全部 39 个配置执行估价，36 个得到正数计算报价。新增的西班牙 `eu-south1` 平台 `gpu-b300-sxm-a` 尚未列入公开规格表，但当前 [Platform API](https://docs.nebius.com/rest-api/compute/v1/platforms/list)明确返回 B300 NVLink SM、270 GB 显存和两档配置（1 卡 / 24 vCPU / 464 GiB RAM；8 卡 / 192 vCPU / 3712 GiB RAM）。采集器按 API 的明确身份和数量核验，不套用旧 B300 的 346 / 2768 GiB RAM，不以文档地区名单限制当前项目返回的配置；证据标记为 `official_project_platform_api`、`platform_variant_not_listed`。两档新配置的估价均返回零计算费，和 GB300 一样保留 `compute_tariff_unavailable`，不能填成零元价或套用其他地区价格。

标准用户可用[官方 CLI 的 OAuth 流程](https://docs.nebius.com/cli/install)取得短期 access token，再通过 `nebius iam get-access-token` 刷新。[认证文档](https://docs.nebius.com/rest-api/authentication)列明用户 token 通常有效 12 小时；token 继承用户权限，本身不是只读凭证。token 刷新由调用方负责；库不保存浏览器 Cookie 或刷新凭据。实采只证明当次账号有权限访问的项目与费率，不证明库存、其他账号合同或全部私有地区。

无人值守运行应由调度端取得新 token，而非把这次用户 token 当作永久密钥。官方提供两条可选路径：

- 已配置服务账号的 [authorized key](https://docs.nebius.com/iam/service-accounts/authorized-keys)；[Python SDK](https://github.com/nebius/pysdk#initialize-with-the-private-key-file)支持私钥或 credentials 文件及自动续期。AWS 兼容服务的 access key 不是本接口所需的 authorized key。
- 已配置 [OIDC federated credentials](https://docs.nebius.com/terraform-provider/reference/resources/iam_v1_federated_credentials) 的服务账号；信任关系把外部 issuer 和精确 JWT `sub` 绑定到服务账号。官方 [SDK 实现](https://github.com/nebius/gosdk/blob/main/auth/federated_credentials.go)使用服务账号 ID 作为 `subject_token`、外部 JWT 作为 `actor_token` 交换短期 token。CI 每次运行应取得新的 OIDC JWT；只配置工作流而没有云端信任绑定不能完成鉴权。

[角色文档](https://docs.nebius.com/iam/authorization/roles)列出 `viewer` 的只读资源权限和价格查看权限，但没有明确逐项列出本工具所用租户 / 项目 / Platform / EstimateBatch 的最小授权组合。应将服务账号限定到目标项目并实测这些只读接口，不直接授予 `editor` 或 `admin`。上述机制尚未替当前账号创建任何服务账号、密钥或权限，也不代表云端自动续期已部署。

## Crusoe

```bash
gpu-price-monitor collect --env-file .env.crusoe.example --pretty > crusoe.json
gpu-price-monitor collect --env-file .env.crusoe.example --format csv --csv-profile catalog > crusoe-catalog.csv
```

完整公开目录模式独立读取三个官方来源：

- [GPU 价格表](https://www.crusoe.ai/cloud/pricing)：全部 GPU 型号和按需 / Spot 单元格，销售询价不填金额。
- [GPU VM 规格](https://docs.crusoecloud.com/compute/virtual-machines/overview/)：准确 SKU、GPU 数量、单卡显存、CPU、RAM 与部署区。
- [数据中心](https://docs.crusoecloud.com/locations/)：部署区对应的国家和地点。

JSON 的 `provider_results[].catalog_coverage.availability_catalog` 返回完整部署规格，`location_catalog` 返回位置目录。每条价格的 `documented_vm_configurations`、`coverage_*` 仅说明相符硬件的部署地点，不是该价格的地区报价。可用 `--coverage-region` / `--coverage-country` 查询部署覆盖；不能用这些字段冒充 `--region` / `--country` 价格筛选。

当前公开价格表没有把金额绑定到部署地区，也没有明示全球统一价。因此 `price_applicability.status=unverified`，不标“全国 / 全球统一”。`compact` 地区主表不会收录这些未核实地区的报价，`catalog` 导出保留官网目录供核对，`full` 保留所有审计字段。

[账单](https://docs.crusoecloud.com/usage-billing/viewing-billing/)是已发生的消费，[预留合同](https://docs.crusoecloud.com/usage-billing/reservations/overview/)是已有账号协议，模型部署计费是另一产品。它们不能替代市场 VM 报价。当前公开 OpenAPI 与控制台客户端未找到可验证的完整 GPU 租价接口；登录账号不保证得到未公开或销售定制的报价。若后续取得官方地区报价依据，再增加对应价格绑定。

2026-10-22 登录账号核查：会话有效，账号可读取项目和 35 条 VM types，但该接口未含价格字段。实例配置入口要求先完成付款资料，账号还提示暂无基础设施配额；未提交付款资料、申请配额或创建资源。官网同日下午实采仍是 7 条数值、17 条销售询价格。不能据此宣称拿到登录账号的全部地区报价。

2026-10-23 公开页核查：官网 GPU 实例表改为型号、按需和 Spot 三列独立 CMS 列表，旧的逐行解析不再适用。采集器现按该页面的显式型号排序与三列对应关系解析，要求列数、行数、型号和顺序均可校验；缺失单元格或排序歧义会报错，不错位套用价格，也不读取相邻的托管推理报价。当前 12 个型号/显存/变体条目共有 24 个价格格，其中 7 个有金额、17 个为销售询价；B300 HGX 为 $8.96/GPU-hour。这些仍是未绑定价格地区的官网目录价，不能视为全部地区的统一报价。
