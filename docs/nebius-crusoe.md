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

配置明确包含 preset 的 GPU / CPU / RAM 和默认 **40 GiB SSD 启动盘**，可用 `NEBIUS_CATALOG_BOOT_DISK_GIB` 调整。保留整机金额、分项费用及单 GPU 每小时折算，不能把整机总额当作单卡价。默认 `NEBIUS_CATALOG_CURRENCY=usd`，也支持 `ils`；库不做外汇换算。

标准用户可用[官方 CLI 的 OAuth 流程](https://docs.nebius.com/cli/install)取得短期 access token，再通过 `nebius iam get-access-token` 刷新。[认证文档](https://docs.nebius.com/rest-api/authentication)列明用户 token 通常有效 12 小时；token 继承用户权限，本身不是只读凭证。token 刷新由调用方负责；库不保存浏览器 Cookie 或刷新凭据。仅填写密钥或离线测试不代表已完成账号实采。

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
