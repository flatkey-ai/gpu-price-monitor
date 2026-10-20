# 配置与调用方接入

0.6.0 提供 Nebius、Crusoe、Lambda、AutoDL、UCloud、RunPod、DigitalOcean、Verda、EBCloud、Suanli、Azure 共 11 家免费公开来源，不需要登录、API key、充值或绑卡。Lambda / UCloud 只在显式 API 模式使用认证，认证分支尚未完成成功的真实报价联调。

## 安装和免费采集

Python 3.11+。AutoDL 需要可选 Playwright 和本地 Chromium；其他 HTTP 来源只需基础包：

```bash
python3 -m pip install -e '.[browser]'
python3 -m playwright install chromium
gpu-price-monitor collect --providers all --coverage --lambda-source public --ucloud-source public --pretty
```

Python 返回标准字典，可由调用方序列化、存储或上传：

```python
import json
from gpu_price_monitor import collect_prices, Settings

result = collect_prices(
    providers="all",
    settings=Settings(),
    include_coverage=True,
)
print(json.dumps(result, ensure_ascii=False, indent=2))
```

价格保留来源 USD / EUR / CNY 等币种；UCloud 促销保留月价，其他公开来源为小时价。不要统一筛选 USD 或按需，以免删掉另一来源；调用方必须核对 `unit`、`billing_mode`、资格条件及每来源状态，不能直接比较不同单位的数值。

显式免费配置启用三家公开来源：

```bash
gpu-price-monitor collect --config configs/collect.free.example.json --lambda-source public --ucloud-source public --pretty
gpu-price-monitor collect --config configs/collect.all.example.json --coverage --lambda-source public --ucloud-source public --pretty
```

默认来源仍为 `nebius,crusoe`，保持原调用行为。仅使用 HTTP 来源时，`python3 -m pip install -e .` 足够；不需要安装浏览器。

`--providers all` / Python `collect_prices("all", settings=Settings())` 选择全部 11 家已实现来源；`--coverage` / Python `include_coverage=True` 增加本次返回数据的型号族索引，不增加网络请求、不合并不同价格。报告区分正常数值挂牌、仅下线挂牌、仅询价和本次未找到，不验证库存或改变来源失败状态。见 [实抓 JSON](../examples/all-providers-2026-10-20.json) 和 [覆盖报告](../examples/mainstream-coverage-2026-10-20.json)。

2026-10-20 北京时间 16:01 的全部来源 CLI 采集成功返回 746 条记录（734 条数值价格、12 条联系销售）；内置 34 个目标型号族均有数值挂牌，零缺口。该次覆盖不证明库存、所有地区、显存及硬件变体或所有资源类型已覆盖；`extra_models` 的保守别名也不是额外唯一物理型号数。

## RunPod、DigitalOcean 与 Verda 免费采集

```bash
gpu-price-monitor collect --providers runpod,digitalocean,verda --coverage --pretty
```

无需 `.env`、密钥或询价目标文件。RunPod 通过匿名 GraphQL 读取 GPU Pods 目录，将 Secure / Community 云层分开；不采集 Serverless、MIG 分区或部署接口。DigitalOcean 解析官方 GPU Droplet 按需 / Spot 表，保留完整实例价格与明确的单卡 / 8 卡数量。Verda 解析公开网页的按需 / Spot、USD / EUR 价目。

这些来源未给出与报价直接关联的地区 / 可用区，不能按这些维度筛选。DigitalOcean / Verda 支持按明确卡数筛选；RunPod 目录没有实例卡数。Spot 的公开数值可变化、资源可被回收；挂牌不代表库存。详细价格字段见 [数据口径](DATA_MODEL.md)。

## EBCloud、Suanli 与 Azure

```bash
gpu-price-monitor collect --providers ebcloud,suanli,azure --coverage --pretty
gpu-price-monitor collect --providers azure --region eastus --gpu T4 --pretty
```

三家均无必填 env 或浏览器依赖。EBCloud 仅读取默认明确选中的按量 / 1 卡 GPU 容器配置，支持按卡数筛选；不推算多卡或包月。Suanli 读取官方明示云主机与弹性部署共用的 GPU 卡时价，按秒计费，保留产品范围；当前没有实例卡数、CPU 或 RAM 信息，不支持卡数或地区筛选，也不采 NPU 或 Token API 价格。

Azure 匿名 Retail Prices API 只查 T4 `Standard_NC4as_T4_v3` 和 GB200 `Standard_ND128isr_NDR_GB200_v6` 两个固定规格；按 ARM 地区返回按需 / Spot 零售价，支持 `--region` 和 `--gpu-count`，不支持可用区或国家。价格是基础 VM 实例总价按 1 / 4 GPU 分摊，管理磁盘、网络等另计；不是配额、容量或订阅可购性检查。[官方身份认证与接口说明](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)及硬件依据见 [平台核查](PROVIDERS.md)。

## UCloud 免费月卡和地区筛选

默认 `UCLOUD_SOURCE=public`，使用官网匿名接口 `ListPackage`、`ListActivity`、`GetActivityFlags`、`ListAllRegions` 和 `ListAllZones`。覆盖活动 `10204` / `10216` / `10248`；不使用 keys、登录态或购买接口。

```bash
gpu-price-monitor collect --providers ucloud --ucloud-source public --pretty
gpu-price-monitor collect --providers ucloud --ucloud-source public --region cn-bj2 --zone cn-bj2-02 --gpu T4S --gpu-count 1 --billing-mode monthly --pretty
```

Python 可按相同条件筛选：

```python
from gpu_price_monitor import collect_prices, Settings

result = collect_prices(
    ["ucloud"],
    {"regions": ["cn-bj2"], "zones": ["cn-bj2-02"],
     "gpu_models": ["T4S"], "gpu_counts": [1]},
    settings=Settings(ucloud_source="public"),
)
```

具体套餐的 Zone ID 通过官方地区 / 可用区映射核对，支持地区、可用区、GPU 和卡数筛选；国家筛选仍不支持。每条保留 CPU、内存 MB、磁盘、带宽和 CPU 平台，不以分组最低价替代具体套餐价格。

当前只采集明确的一月套餐。`CurPrice` / `OriginalPrice` 的分值除以 100 得到 CNY 整实例月价，再按 GPU 数量分摊为 `gpu_month`。`instance_price.unit=instance_month`，**不除以 720 计算小时价**，不标为标准按需市场价。

活动公布的新老用户条件、限购和优惠续费标志会保留。10204 / 10216 / 10248 元数据限购分别为 3 / 5 / 5，但官网规则与元数据有资格文案不一致，`eligibility_verified=false`；购买资格仍须平台核验。当前三活动采样 374 条均为 `offline`。`ended`、`upcoming` 等状态同样保留；无这些标记时也仅为 `unknown`，不表示有库存或可购买。

2026-10-20 的 [北京2 T4S 示例](../examples/ucloud-public-cn-bj2-2026-10-20.json) 是实际筛选结果，均有下线标记。它是历史挂牌证据，不是可购承诺或实时回退数据。

## Lambda 与 AutoDL 免费范围

Lambda 默认 `LAMBDA_SOURCE=public` 请求 [官方实例页](https://lambda.ai/instances)，即使已有 key 也不自动改走 API。挂牌单卡小时价乘明确卡数得到派生实例价；资源保留 GiB / TiB。地区、国家和可用区未知，对应筛选返回错误，挂牌不证明库存。

AutoDL 使用新的未登录浏览器上下文读取 [公开首页](https://www.autodl.com/home) 的普通 / 会员价，不使用 token、用户 Cookie 或保存的会话。会员优惠条件单列；首页不是逐机器 / 地区报价或实时库存，卡数也未知。

## 可选认证 API

只有 `LAMBDA_SOURCE=api` / `--lambda-source api` 才使用 `LAMBDA_API_KEY`。该模式返回认证实例目录，整实例原价按卡数分摊；容量地区不是价格地区。公开成功不能作为 API 认证成功证据。

只有 `UCLOUD_SOURCE=api` / `--ucloud-source api` 才调用认证 `GetUHostInstancePrice`。调用方提供公私钥，以及内联 JSON 或 FILE 二选一的完整目标。子账号可能需要 `UCLOUD_PROJECT_ID`。本地 `.env` 和 `configs/ucloud-targets.local.json` 不提交 Git，设置示例：

```dotenv
GPU_PRICE_MONITOR_PROVIDERS=ucloud
UCLOUD_SOURCE=api
UCLOUD_PRICE_TARGETS_FILE=configs/ucloud-targets.local.json
```

在 `.env` 中自行填写 UCloud 公私钥，先执行不联网、不打印密钥值的检查：

```bash
gpu-price-monitor status --env-file .env
```

填好凭据并核对实际可售配置后，再显式调用：

```bash
gpu-price-monitor collect --env-file .env --providers ucloud --ucloud-source api --pretty
```

Python 可用 `Settings.from_env(env_file=".env")` 加载该文件，再交给 `collect_prices`。读取设置不会发起询价，密钥存在也不表示认证已成功。

UCloud API target 为 1–20 个完整对象组成的 UTF-8 JSON 数组：

| 字段 | 约束 |
| --- | --- |
| `Region`、`Zone` | 显式地区和可用区 |
| `MachineType` | 仅 `G`，完整 GPU 实例 |
| `GpuType`、`GPU` | GPU 类型、正整数卡数 |
| `CPU`、`Memory` | CPU 数量、内存 MB；内存为 1024 的倍数 |
| `Disks` | 每项 `Size`（GB）、`Type`、`IsBoot`；恰有一个启动盘 |
| `ChargeType`、`Count` | 仅 `Dynamic`，`Count=1` |

[目标示例](../configs/ucloud-targets.example.json)仅说明格式，不证明地区 / 规格当前可售。认证分支不自动发现可售配置，不支持共享分片、裸金属、其他计费方式或 `Action` 覆盖。返回是账号 CNY 整实例小时价，GPU 值为套餐分摊成本；地区来自请求，不由响应独立回显核验。

## 配置文件与 CLI

`collect.example.json` 默认只启用 Nebius / Crusoe；`collect.free.example.json` 启用 Lambda / AutoDL / UCloud；`collect.all.example.json` 启用全部 11 家。每来源筛选用数组字段 `compute_countries`、`sales_countries`、`regions`、`zones`、`gpu_models`、`gpu_counts`、`billing_modes`、`currencies`；实际支持范围见 [数据口径](DATA_MODEL.md)。

配置来源必须与模式一致：Lambda 公开 / API 分别为 `public_page` / `official_api`，UCloud 分别为 `official_public_api` / `official_quote_api`。RunPod / Azure 为 `official_public_api`，DigitalOcean 为 `public_documentation`，Verda / EBCloud / Suanli 为 `public_page`。API 还需显式模式选择，不会只因 key 存在而切换。

```bash
gpu-price-monitor validate-config --config configs/collect.free.example.json
```

配置检查不联网，不验证账号权限、价格或可售性。CLI 支持 `--providers all`、`--coverage`、`--lambda-source public|api`、`--ucloud-source public|api`、`--env-file`、`--timeout`、`--max-retries`、`--pretty`，以及可重复的 `--gpu`、`--region`、`--zone`、`--gpu-count`、`--currency`、`--billing-mode`、`--country`、`--sales-country`。

`collect` stdout 只写 JSON，日志写 stderr。退出码 `0` 为全部成功或无匹配，`2` 为部分来源失败，`1` 为全部失败或全局配置错误。库保留下线挂牌，不将下线、询价或失败写成零元。

## env 加载与错误边界

默认 `Settings.from_env()` 仅读取进程环境，不隐式查找 `.env`；显式传 `env_file` 或 CLI `--env-file` 才读取指定文件，不搜索父目录。python-dotenv 不插值、不执行 shell、不修改 `os.environ`。进程环境 / 显式映射优先，空值也覆盖。env 文件上限 256 KiB，语法错误、重复赋值或没有 `=` 的变量行会被拒绝。

JSON / FILE 目标来源按层整体选择。进程层只要出现任一变量，就覆盖 env 文件层的两项；两项都为空会清除目标。同层两项非空报 `ConfigurationError`。FILE 相对指定 env 文件目录解析，否则相对当前工作目录。

**即使选择 public，显式配置的 FILE 仍在设置层全局读取校验**；读取或 UCloud target 校验失败在任何来源请求前抛出安全的 `ConfigurationError`，不回退。免费推荐不填 keys / FILE / JSON，不加载旧认证 env 文件。内联目标错误仍在 API 来源阶段返回结构化错误。

| 环境变量 | 用途 / 默认值 |
| --- | --- |
| `GPU_PRICE_MONITOR_PROVIDERS` | 默认 `nebius,crusoe` |
| `GPU_PRICE_MONITOR_TIMEOUT_SECONDS`、`GPU_PRICE_MONITOR_MAX_RETRIES` | 默认 `30` 秒、`2` 次 |
| `LAMBDA_SOURCE`、`UCLOUD_SOURCE` | 默认 `public`；API 必须显式选择 |
| `LAMBDA_API_KEY` | 仅 Lambda API 使用 |
| `UCLOUD_PUBLIC_KEY`、`UCLOUD_PRIVATE_KEY`、`UCLOUD_PROJECT_ID` | 仅 UCloud API 使用 |
| `UCLOUD_PRICE_TARGETS_JSON`、`UCLOUD_PRICE_TARGETS_FILE` | UCloud API 请求目标；FILE 若配置则全局校验 |
| `NEBIUS_ACCESS_TOKEN` | 后续认证估价保留 |
| `AUTODL_TOKEN`、`AUTODL_STORAGE_STATE_PATH` | 当前免费首页不使用 |

缺 API 凭据为 `missing_credentials`，缺少 / 无效内联 target 为 `missing_price_targets` / `invalid_price_targets`，一般只影响该来源。AutoDL 缺可选依赖 / Chromium 分别返回 `browser_dependency_missing` / `browser_not_installed`。参考 [env 模板](../.env.example)。

## 调用方职责

库只抓取并返回，不配置上传 URL、数据库、Webhook 或调度时间。使用者自行运行、上传、存储、保留历史、换汇、比较、告警和展示。采集仅需普通 CPU；不创建、启动或购买云实例来获得报价。遵守来源访问限制，不绕过验证码或访问控制。
