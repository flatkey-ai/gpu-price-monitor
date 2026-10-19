# GPU Price Monitor

**GPU 云算力价格采集库**：从官方来源抓取报价，通过 Python API 或 CLI 返回结构化 JSON。

[English](README.en.md) · [方案](docs/PLAN.md) · [数据口径](docs/DATA_MODEL.md) · [平台核查](docs/PROVIDERS.md) · [接入说明](docs/DEPLOYMENT.md) · [路线图](ROADMAP.md)

## 当前支持

0.3.0 支持 **Nebius、Crusoe、Lambda 和 UCloud**，并提供显式 env 文件及本地询价文件加载。Nebius / Crusoe 使用公开来源；Lambda / UCloud 使用调用方凭据，只读查询价格。AutoDL 尚未实现，返回 `not_implemented`。当前版本尚未发布到 PyPI，请从源码安装。

Lambda 和 UCloud 已通过离线样本验证，当前环境未配置凭据，**尚未完成真实认证报价联调**。下方公开抓取示例不证明这两家的账号接口已经实测成功。

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
| GPU 型号 | `gpu_models` / `--gpu` | 四个已实现来源支持 |
| 币种 | `currencies` / `--currency` | 四个来源支持；Lambda 为 USD，UCloud 为 CNY，不换汇 |
| 计费方式 | `billing_modes` / `--billing-mode` | 四个来源支持；UCloud 当前仅 Dynamic 按需询价 |
| 地区 | `regions` / `--region` | Nebius / UCloud 支持；Crusoe / Lambda 返回 `unsupported_filter` |
| 服务 / 销售国家 | `compute_countries` / `--country`、`sales_countries` / `--sales-country` | 当前四家均无法可靠映射，返回结构化错误 |
| 可用区 | `zones` / `--zone` | UCloud 支持；其余来源返回结构化错误 |
| 卡数 | `gpu_counts` / `--gpu-count` | Lambda / UCloud 支持；公开页面来源无法验证 |

价格未说明的国家、地区或卡数保留未知值。库不会把全球或未说明地区的价格包装成指定地区报价。配置格式支持某字段，不代表当前来源可以应用该筛选。

## 配置和 env

```bash
gpu-price-monitor status
gpu-price-monitor validate-config --config configs/collect.example.json
gpu-price-monitor collect --config configs/collect.example.json --pretty
```

示例配置启用 Nebius 和 Crusoe，其余来源关闭。可在每个来源的 `filters` 中分别设置条件；配置检查不联网、不验证凭据有效性。请求选项可通过 `--timeout`、`--max-retries` 设置。

环境变量字段见 [`.env.example`](.env.example)。默认仅读取进程环境；需要本地文件时显式使用 CLI `--env-file .env` 或 Python `Settings.from_env(env_file=".env")`。不搜索父目录，不修改进程环境，不执行文件内的 shell 命令或变量插值。

| 环境变量 | 用途 / 默认值 |
| --- | --- |
| `GPU_PRICE_MONITOR_PROVIDERS` | 逗号分隔的默认来源；`nebius,crusoe` |
| `GPU_PRICE_MONITOR_TIMEOUT_SECONDS` | 请求超时；`30` 秒 |
| `GPU_PRICE_MONITOR_MAX_RETRIES` | 最大重试次数；`2` |
| `LAMBDA_API_KEY` | Lambda 必填，只读实例目录认证 |
| `NEBIUS_ACCESS_TOKEN` | 为后续认证估价分支保留；当前公开采集无需凭据 |
| `UCLOUD_PUBLIC_KEY` / `UCLOUD_PRIVATE_KEY` | UCloud 必填，账号询价认证 |
| `UCLOUD_PRICE_TARGETS_JSON` / `UCLOUD_PRICE_TARGETS_FILE` | UCloud 二选一：内联完整配置 JSON 数组或 UTF-8 JSON 文件，最多 20 项 |
| `UCLOUD_PROJECT_ID` | UCloud 可选项目 ID；子账号通常需要 |
| `AUTODL_TOKEN` / `AUTODL_STORAGE_STATE_PATH` | 为后续 AutoDL 适配器保留 |

`collect` 退出码：`0` 为全部来源成功（含筛选后无匹配），`2` 为部分来源失败，`1` 为全部失败或配置无效。调用方应同时检查结果与退出码。

## Lambda / UCloud 认证采集

本地使用不入 Git 的 `.env` 和 `configs/ucloud-targets.local.json`。`.env` 中填写 `LAMBDA_API_KEY`、`UCLOUD_PUBLIC_KEY`、`UCLOUD_PRIVATE_KEY`，并设置：

```dotenv
GPU_PRICE_MONITOR_PROVIDERS=lambda,ucloud
UCLOUD_PRICE_TARGETS_FILE=configs/ucloud-targets.local.json
```

先核对本地询价文件中的实际地区和完整规格，再运行只读本地检查：

```bash
gpu-price-monitor status --env-file .env
```

该命令不联网，也不验证密钥有效性。填好密钥和实际配置后，再由操作者明确执行真实采集：

```bash
gpu-price-monitor collect --env-file .env --providers lambda,ucloud --pretty
```

Python 使用 `settings=Settings.from_env(env_file=".env")`。文件路径相对 `.env` 所在目录解析；未指定 env 文件时相对当前工作目录。进程环境覆盖文件配置，空值也覆盖；同一层不能同时配置非空的 JSON 和 FILE。细节见 [接入说明](docs/DEPLOYMENT.md)。

[UCloud 目标示例](configs/ucloud-targets.example.json)仅说明结构，不代表示例地区或规格当前可售。必须指定 Region、Zone、GPU、CPU、内存 MB 和磁盘，当前仅支持 `MachineType=G`、`ChargeType=Dynamic`、`Count=1` 的完整 GPU 实例。支持范围与凭据操作见 [接入说明](docs/DEPLOYMENT.md)。不要对这两家统一指定 `--currency USD`，否则会筛掉 UCloud 的 CNY 结果。

缺少凭据及内联 JSON 目标错误分别返回来源级 `missing_credentials`、`missing_price_targets` / `invalid_price_targets`，保留其他来源的成功报价。FILE 读取或校验失败则属于全局 `ConfigurationError`，会在任何来源开始采集前终止。

## 价格口径

保留原价、币种、单位、资源配置、来源和采集 / 生效时间。Lambda / UCloud 的 `amount` 是整实例小时价按 GPU 数量分摊的值，`instance_price` 保留整实例原价；不能当作裸 GPU 单独售价。Lambda 的容量地区与报价地区分开。UCloud 地区来自请求条件，接口不回显验证，不保证该规格可售。Nebius GPU 分项、起价和 Crusoe 询价也分别标识；公开挂牌不保证库存或可以自助购买。

真实联调仅使用只读能力，不创建或购买 GPU 资源获取报价。贡献前请阅读 [贡献指南](CONTRIBUTING.md)。代码采用 [Apache-2.0](LICENSE)，第三方价格再使用范围见 [数据说明](docs/DATA_POLICY.md)。
