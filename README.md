# GPU Price Monitor

**GPU 云算力价格采集库**：从官方来源抓取报价，通过 Python API 或 CLI 返回结构化 JSON。

[English](README.en.md) · [方案](docs/PLAN.md) · [数据口径](docs/DATA_MODEL.md) · [平台核查](docs/PROVIDERS.md) · [接入说明](docs/DEPLOYMENT.md) · [路线图](ROADMAP.md)

## 当前支持

0.5.0 支持 **Lambda + AutoDL + UCloud 免费公开价格采集**，无需登录、API key、充值或绑卡。Lambda 默认抓实例页，AutoDL 读取首页普通 / 会员价，UCloud 默认读取官网匿名促销月卡接口。已有 key 不会自动切换认证来源。Nebius / Crusoe 同为公开来源。当前版本尚未发布到 PyPI，请从源码安装。

Lambda 公开页已完成实际采样：2026-10-20 获取 4 张规格表、22 条报价，覆盖 8 / 4 / 2 / 1 卡实例；挂牌不代表实时库存。可选 Lambda API 和 UCloud 认证询价仅有离线样本验证，尚无成功的真实认证报价记录。

本库负责请求、解析、筛选核对和返回价格。调用方负责定时执行、存储、历史、上传、比价、告警和看板；Flatkey 与其他使用者使用同一套采集能力，库中没有业务上传地址。

## 安装与抓取

要求 Python 3.11+，运行仅需普通 CPU。

```bash
git clone https://github.com/flatkey-ai/gpu-price-monitor.git
cd gpu-price-monitor
python3 -m pip install -e '.[browser]'
python3 -m playwright install chromium
gpu-price-monitor collect --providers lambda,autodl,ucloud --lambda-source public --ucloud-source public --pretty
```

`collect` 的 stdout 仅包含 JSON，日志写入 stderr。需要保存文件时，可由调用方使用重定向：

```bash
gpu-price-monitor collect --providers lambda,autodl,ucloud --lambda-source public --ucloud-source public --pretty > prices.json
```

Python 调用返回标准 `dict`，可直接交给自己的存储或上传函数：

```python
import json
from gpu_price_monitor import collect_prices, Settings

result = collect_prices(
    providers=["lambda", "autodl", "ucloud"],
    settings=Settings(lambda_source="public", ucloud_source="public"),
)
print(json.dumps(result, ensure_ascii=False, indent=2))
```

结果包含 `schema_version`、`status`、UTC `collected_at`、`prices` 和 `provider_results`。部分来源失败时保留成功报价，并返回每个来源的状态、筛选反馈和错误。格式详见 [数据口径](docs/DATA_MODEL.md)。

可查看 [2026-10-20 免费路径实抓 JSON](examples/lambda-autodl-2026-10-20.json)：北京时间 14:55 采样，共 46 条，Lambda 22 条、AutoDL 24 条（普通 / 会员各 12 条）。Python API 和 CLI 均成功返回。该文件是历史调用示例，不作为实时抓取的回退值，也不代表当前库存或认证 API 已验证。

## 筛选及地区限制

CLI 支持重复传入筛选，例如 `--gpu H100 --gpu H200`。以下命令限定 Nebius 地区：

```bash
gpu-price-monitor collect --providers nebius --region eu-north1 --currency USD --pretty
```

| 筛选 | Python 字段 / CLI | 当前行为 |
| --- | --- | --- |
| GPU 型号 | `gpu_models` / `--gpu` | 依据来源价格记录筛选 |
| 币种 | `currencies` / `--currency` | Lambda 为 USD，AutoDL / UCloud 为 CNY；不换汇 |
| 计费方式 | `billing_modes` / `--billing-mode` | UCloud 公开月卡为 `monthly`，可选 API 为按需；其余按来源标识 |
| 地区 | `regions` / `--region` | Nebius / UCloud 支持；Lambda / AutoDL / Crusoe 不支持 |
| 服务 / 销售国家 | `compute_countries` / `--country`、`sales_countries` / `--sales-country` | 尚未开放；UCloud 公开结果仍保留官方 `country_code` 元数据 |
| 可用区 | `zones` / `--zone` | UCloud 支持；其余来源返回结构化错误 |
| 卡数 | `gpu_counts` / `--gpu-count` | Lambda / UCloud 支持；AutoDL / Nebius / Crusoe 无法验证 |

价格未说明的国家、地区或卡数保留未知值。库不会把全球或未说明地区的价格包装成指定地区报价。配置格式支持某字段，不代表当前来源可以应用该筛选。

## 配置和 env

```bash
gpu-price-monitor status
gpu-price-monitor validate-config --config configs/collect.example.json
gpu-price-monitor collect --config configs/collect.example.json --pretty
```

默认配置启用 Nebius / Crusoe；免费示例 `configs/collect.free.example.json` 启用 Lambda / AutoDL / UCloud。不传来源或配置时仍默认 `nebius,crusoe`。可在每来源 `filters` 中设置条件；配置检查不联网，不验证密钥有效性。请求选项可通过 `--timeout`、`--max-retries` 设置。

```bash
gpu-price-monitor collect --config configs/collect.free.example.json --lambda-source public --ucloud-source public --pretty
```

仅使用 Lambda / UCloud / Nebius / Crusoe 等 HTTP 来源可安装基础包 `python3 -m pip install -e .`；AutoDL 需要上面的可选浏览器依赖和 Chromium。

环境变量字段见 [`.env.example`](.env.example)。默认仅读取进程环境；需要本地文件时显式使用 CLI `--env-file .env` 或 Python `Settings.from_env(env_file=".env")`。不搜索父目录，不修改进程环境，不执行文件内的 shell 命令或变量插值。

| 环境变量 | 用途 / 默认值 |
| --- | --- |
| `GPU_PRICE_MONITOR_PROVIDERS` | 逗号分隔的默认来源；`nebius,crusoe` |
| `GPU_PRICE_MONITOR_TIMEOUT_SECONDS` | 请求超时；`30` 秒 |
| `GPU_PRICE_MONITOR_MAX_RETRIES` | 最大重试次数；`2` |
| `LAMBDA_SOURCE` | `public`（默认）抓公开页；`api` 显式选择旧认证目录 |
| `LAMBDA_API_KEY` | 仅 `LAMBDA_SOURCE=api` 时必填；公开抓取不使用该 key |
| `NEBIUS_ACCESS_TOKEN` | 为后续认证估价分支保留；当前公开采集无需凭据 |
| `UCLOUD_SOURCE` | `public`（默认）读取公开月卡；`api` 显式选择认证询价 |
| `UCLOUD_PUBLIC_KEY` / `UCLOUD_PRIVATE_KEY` | 仅 `UCLOUD_SOURCE=api` 时必填 |
| `UCLOUD_PRICE_TARGETS_JSON` / `UCLOUD_PRICE_TARGETS_FILE` | 仅 UCloud API 使用，二选一完整配置 JSON 数组或文件，最多 20 项 |
| `UCLOUD_PROJECT_ID` | UCloud 可选项目 ID；子账号通常需要 |
| `AUTODL_TOKEN` / `AUTODL_STORAGE_STATE_PATH` | 认证功能保留；当前免费公开首页不使用 |

`collect` 退出码：`0` 为全部来源成功（含筛选后无匹配），`2` 为部分来源失败，`1` 为全部失败或配置无效。调用方应同时检查结果与退出码。

## 免费 Lambda 公开采集

默认来源为 [Lambda 官方实例页](https://lambda.ai/instances)，不需要填写 `.env` 或设置凭据：

```bash
gpu-price-monitor collect --providers lambda --pretty
```

价格按官网每 GPU / 小时返回，实例整机小时价由公开单卡价乘卡数推导；资源保留官网 GiB / TiB 单位。地区、国家和可用区未公布时保持未知，请勿添加这些筛选或把挂牌当作可下单库存。

## 免费 AutoDL 的覆盖范围

来源为 [AutoDL 公开首页](https://www.autodl.com/home)，浏览器使用新的未登录上下文读取普通价和会员价。会员优惠条件单独保留，不能将其当作所有用户可享的普通价。

首页报价没有逐机器、逐地区的当前价格和库存，实例卡数也未知；地区、国家、可用区和卡数筛选会返回结构化错误。Lambda / AutoDL 使用不同币种，默认示例不加统一 USD 过滤。

## 免费 UCloud 月卡与地区筛选

默认 `UCLOUD_SOURCE=public` 通过官网匿名接口读取活动 `10204` / `10216` 的完整促销套餐，用官方地区 / 可用区映射核对位置。无需 key、登录或询价配置文件：

```bash
gpu-price-monitor collect --providers ucloud --ucloud-source public --pretty
gpu-price-monitor collect --providers ucloud --region cn-bj2 --zone cn-bj2-02 --billing-mode monthly --pretty
```

`unit=gpu_month`、`instance_price.unit=instance_month`，保留月价，**不除以 720 换成小时价**。单卡月价是包含 CPU、内存、磁盘和带宽的整套餐成本按卡数分摊。

这些是有资格、限购和优惠续费条件的活动挂牌，不是标准按需市场价。区域下线状态会保留；没有下线标记也不保证库存或购买资格。详见 [平台核查](docs/PROVIDERS.md)。

2026-10-20 实抓全量 358 条；[北京2 / 可用区B / T4S 单卡 JSON](examples/ucloud-public-cn-bj2-2026-10-20.json)是北京时间 15:23 的 18 条筛选结果，均标记 `offline`。这是采集成功的历史挂牌，不能作为当前可购买资源。

## 可选 UCloud 与 Lambda API

只有显式 `UCLOUD_SOURCE=api` / `--ucloud-source api` 才使用 UCloud 凭据和完整询价文件。该可选分支使用不入 Git 的 `.env` 与本地目标文件。Lambda 同样只有显式选择 API 才使用 key。认证 UCloud 设置示例：

```dotenv
GPU_PRICE_MONITOR_PROVIDERS=ucloud
UCLOUD_SOURCE=api
UCLOUD_PRICE_TARGETS_FILE=configs/ucloud-targets.local.json
```

先核对本地询价文件中的实际地区和完整规格，再运行只读本地检查：

```bash
gpu-price-monitor status --env-file .env
```

该命令不联网，也不验证密钥有效性。填好密钥和实际配置后，再由操作者明确执行真实采集：

```bash
gpu-price-monitor collect --env-file .env --providers ucloud --ucloud-source api --pretty
```

Python 使用 `settings=Settings.from_env(env_file=".env")`。文件路径相对 `.env` 所在目录解析；未指定 env 文件时相对当前工作目录。进程环境覆盖文件配置，空值也覆盖；同一层不能同时配置非空的 JSON 和 FILE。细节见 [接入说明](docs/DEPLOYMENT.md)。

[UCloud 目标示例](configs/ucloud-targets.example.json)仅说明结构，不代表示例地区或规格当前可售。必须指定 Region、Zone、GPU、CPU、内存 MB 和磁盘，当前仅支持 `MachineType=G`、`ChargeType=Dynamic`、`Count=1` 的完整 GPU 实例。支持范围与凭据操作见 [接入说明](docs/DEPLOYMENT.md)。不要对这两家统一指定 `--currency USD`，否则会筛掉 UCloud 的 CNY 结果。

缺少凭据及内联 JSON 目标错误分别返回来源级 `missing_credentials`、`missing_price_targets` / `invalid_price_targets`，保留其他来源的成功报价。FILE 读取或校验失败则属于全局 `ConfigurationError`，会在任何来源开始采集前终止。

## 价格口径

保留原价、币种、单位、资源配置、来源和时间。Lambda 公开页为挂牌单卡价，实例小时价由卡数推导；UCloud 免费活动保留月价，不与其他来源的小时价直接混比。UCloud 公开月卡位置来自官方映射，认证 API 位置才来自未回显核验的请求条件。组件价、起价、会员价和询价均单独标识；挂牌不保证库存或可下单。

真实联调仅使用只读能力，不创建或购买 GPU 资源获取报价。贡献前请阅读 [贡献指南](CONTRIBUTING.md)。代码采用 [Apache-2.0](LICENSE)，第三方价格再使用范围见 [数据说明](docs/DATA_POLICY.md)。
