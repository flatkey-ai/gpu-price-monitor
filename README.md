# GPU Price Monitor

**GPU 云算力价格采集库**：从官方来源抓取报价，通过 Python API 或 CLI 返回结构化 JSON。

[English](README.en.md) · [方案](docs/PLAN.md) · [数据口径](docs/DATA_MODEL.md) · [平台核查](docs/PROVIDERS.md) · [接入说明](docs/DEPLOYMENT.md) · [路线图](ROADMAP.md)

## 当前支持

已接入 **Nebius 官方公开计价文档**和 **Crusoe 官网 GPU instances 价格区块**，无需账号或 API key。Lambda、UCloud、AutoDL 尚未实现，调用时返回 `not_implemented`。当前版本尚未发布到 PyPI，请从源码安装。

本库负责请求、解析、筛选核对和返回价格。调用方负责定时执行、存储、历史、上传、比价、告警和看板；Flatkey 与其他使用者使用同一套采集能力，库中没有业务上传地址。

## 安装与抓取

要求 Python 3.11+，运行仅需普通 CPU。

```bash
git clone https://github.com/flatkey-ai/gpu-price-monitor.git
cd gpu-price-monitor
python3 -m pip install -e .
gpu-price-monitor collect --providers nebius,crusoe --currency USD --billing-mode on_demand --pretty
```

`collect` 的 stdout 仅包含 JSON，日志写入 stderr。需要保存文件时，可由调用方使用重定向：

```bash
gpu-price-monitor collect --providers nebius,crusoe --pretty > prices.json
```

Python 调用返回标准 `dict`，可直接交给自己的存储或上传函数：

```python
import json
from gpu_price_monitor import collect_prices, Settings

result = collect_prices(
    providers=["nebius", "crusoe"],
    filters={"currencies": ["USD"], "billing_modes": ["on_demand"]},
    settings=Settings.from_env(),
)
print(json.dumps(result, ensure_ascii=False, indent=2))
```

结果包含 `schema_version`、`status`、UTC `collected_at`、`prices` 和 `provider_results`。部分来源失败时保留成功报价，并返回每个来源的状态、筛选反馈和错误。格式详见 [数据口径](docs/DATA_MODEL.md)。

可查看 [2026-10-15 实际抓取的 JSON](examples/nebius-crusoe-2026-10-15.json)：USD 按需报价共 18 条，其中 15 条有数值、3 条需询价。该文件仅为历史调用示例，不作为实时抓取的回退值。

## 筛选及地区限制

CLI 支持重复传入筛选，例如 `--gpu H100 --gpu H200`。以下命令限定 Nebius 地区：

```bash
gpu-price-monitor collect --providers nebius --region eu-north1 --currency USD --pretty
```

| 筛选 | Python 字段 / CLI | 当前行为 |
| --- | --- | --- |
| GPU 型号 | `gpu_models` / `--gpu` | 两个来源支持 |
| 币种 | `currencies` / `--currency` | 两个来源支持，保留原币，不换汇 |
| 计费方式 | `billing_modes` / `--billing-mode` | 两个来源支持 |
| 地区 | `regions` / `--region` | Nebius 可核对；Crusoe 返回 `unsupported_filter` |
| 服务 / 销售国家 | `compute_countries` / `--country`、`sales_countries` / `--sales-country` | 当前来源无法验证，返回结构化错误 |
| 可用区、卡数 | `zones` / `--zone`、`gpu_counts` / `--gpu-count` | 当前来源无法验证，返回结构化错误 |

价格未说明的国家、地区或卡数保留未知值。库不会把全球或未说明地区的价格包装成指定地区报价。配置格式支持某字段，不代表当前来源可以应用该筛选。

## 配置和 env

```bash
gpu-price-monitor status
gpu-price-monitor validate-config --config configs/collect.example.json
gpu-price-monitor collect --config configs/collect.example.json --pretty
```

示例配置启用 Nebius 和 Crusoe，其余来源关闭。可在每个来源的 `filters` 中分别设置条件；配置检查不联网、不验证凭据有效性。请求选项可通过 `--timeout`、`--max-retries` 设置。

环境变量字段见 [`.env.example`](.env.example)。**只读取进程环境，不自动加载 `.env`**；由调用方、容器或运行器注入。

| 环境变量 | 用途 / 默认值 |
| --- | --- |
| `GPU_PRICE_MONITOR_PROVIDERS` | 逗号分隔的默认来源；`nebius,crusoe` |
| `GPU_PRICE_MONITOR_TIMEOUT_SECONDS` | 请求超时；`30` 秒 |
| `GPU_PRICE_MONITOR_MAX_RETRIES` | 最大重试次数；`2` |
| `LAMBDA_API_KEY` | 为后续 Lambda 适配器保留 |
| `NEBIUS_ACCESS_TOKEN` | 为后续认证估价分支保留；当前公开采集无需凭据 |
| `UCLOUD_PUBLIC_KEY` / `UCLOUD_PRIVATE_KEY` | 为后续 UCloud 适配器保留 |
| `AUTODL_TOKEN` / `AUTODL_STORAGE_STATE_PATH` | 为后续 AutoDL 适配器保留 |

`collect` 退出码：`0` 为全部来源成功（含筛选后无匹配），`2` 为部分来源失败，`1` 为全部失败或配置无效。调用方应同时检查结果与退出码。

## 价格口径

保留原价、币种、单位、资源配置、来源和采集 / 生效时间。Nebius 的 GPU 分项不代表整实例总价；“低至”不代表确定现价；Crusoe 的询价项金额为空。公开挂牌不保证有库存或可以自助购买。

真实联调仅使用只读能力，不创建或购买 GPU 资源获取报价。贡献前请阅读 [贡献指南](CONTRIBUTING.md)。代码采用 [Apache-2.0](LICENSE)，第三方价格再使用范围见 [数据说明](docs/DATA_POLICY.md)。
