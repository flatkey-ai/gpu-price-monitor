# 配置与调用方接入

0.2.0 支持 Nebius / Crusoe 公开来源和 Lambda / UCloud 认证只读询价。AutoDL 仍返回 `not_implemented`。Lambda / UCloud 已通过离线样本验证，但当前环境没有凭据，**尚未成功完成真实账号报价联调**。

## 安装和公开采集

要求 Python 3.11+。当前从源码安装，尚未发布 PyPI 版本：

```bash
python3 -m pip install -e .
gpu-price-monitor status
gpu-price-monitor collect --providers nebius,crusoe --currency USD --billing-mode on_demand --pretty
```

Python API 返回可 JSON 序列化的标准字典：

```python
from gpu_price_monitor import collect_prices, Settings

result = collect_prices(
    providers=["nebius", "crusoe"],
    filters={"currencies": ["USD"], "billing_modes": ["on_demand"]},
    settings=Settings.from_env(),
)
```

调用方检查 `status`、`provider_results` 和报价数量后，将返回值交给自己的存储或上传函数。API 正常返回不代表所有来源都成功。

## Lambda 凭据与报价

通过调用方 secrets 系统向进程注入 `LAMBDA_API_KEY`，再执行：

```bash
gpu-price-monitor collect --providers lambda --pretty
```

适配器只请求官方实例目录，不创建或启动资源。返回 `instance_price` 为 USD 整实例小时价，`amount` 为按实例 GPU 数量分摊的单卡小时成本，`account_scope=authenticated_catalog`。

`capacity_regions` 仅表示可用容量地区，不是价格适用地区。支持 GPU、卡数、币种和计费方式本地筛选；`--region`、国家和可用区筛选无法从该价格响应验证，返回结构化错误。

## UCloud 凭据与完整配置

调用方需注入 `UCLOUD_PUBLIC_KEY`、`UCLOUD_PRIVATE_KEY` 和 `UCLOUD_PRICE_TARGETS_JSON`；`UCLOUD_PROJECT_ID` 为可选项目 ID，子账号访问对应项目时需要。目标 JSON 必须是最多 20 个完整配置对象组成的数组：

| 字段 | 约束 |
| --- | --- |
| `Region`、`Zone` | 显式指定地域和可用区 |
| `MachineType` | 仅 `G`，完整 GPU 实例 |
| `GpuType`、`GPU` | GPU 类型和正整数卡数 |
| `CPU`、`Memory` | CPU 数量与内存，`Memory` 单位 MB 且为 1024 的倍数 |
| `Disks` | 对象列表，每项包含 `Size`（GB）、`Type`、`IsBoot`，且恰有一项为启动盘 |
| `ChargeType` | 可省略，默认且仅支持 `Dynamic` |
| `Count` | 固定为 `1` |

参考 [目标结构示例](../configs/ucloud-targets.example.json)。示例只说明 JSON 格式，**未证明示例地区或规格在账户下可售**；请替换为自己已确认的完整配置。当前不自动枚举可售规格，不支持共享分片、裸金属和非按需计费，也不允许传入 `Action` 等字段覆盖请求。

调用方运行器可加载示例文件到进程环境；这不是库自动读取文件：

```bash
export UCLOUD_PRICE_TARGETS_JSON="$(cat configs/ucloud-targets.example.json)"
gpu-price-monitor collect --providers ucloud --pretty
```

请在运行前通过自己的 secrets 系统注入公私钥，避免把真实密钥写入仓库、命令示例或日志。配置后可同时查询两家：

```bash
gpu-price-monitor collect --providers lambda,ucloud --pretty
```

不要统一使用 `--currency USD`，否则 UCloud 的 CNY 报价会被筛除。也可设置 `GPU_PRICE_MONITOR_PROVIDERS=lambda,ucloud`，再运行不带 `--providers` 的命令。

UCloud 仅调用 `GetUHostInstancePrice`，校验 HTTP 和业务成功码。`instance_price` 为 CNY 整实例小时价，`amount` 为按 GPU 数量分摊成本，`account_scope=account_quote`。CPU、内存 MB、磁盘和地区等条件保留在结果中，但地区 / 可用区来自请求目标，报价接口不回显核验，不构成可售或有库存证明。

GPU、地区、可用区、卡数、币种和计费方式可按目标与结果本地筛选。国家未建立可靠映射，不根据地域名字猜测国家。

## 失败处理

| 错误 | 含义 |
| --- | --- |
| `missing_credentials` | 来源缺少所需凭据 |
| `missing_price_targets` | UCloud 未提供显式目标 |
| `invalid_price_targets` | UCloud 目标不满足结构或支持范围 |
| `unsupported_filter` | 来源不能支持请求筛选 |
| `unverifiable_filter` | 来源数据不足以核对筛选 |
| `not_implemented` | 当前未实现，如 AutoDL |

缺少某一家配置只使该来源失败，其他来源仍可返回结果。`collect` 的 stdout 仅写 JSON，诊断写 stderr。退出码 `0` 为全部成功或没有匹配，`2` 为部分来源失败，`1` 为全部失败或配置无效。调用方应同时检查返回码和每来源状态。

## 配置文件和 CLI

```bash
gpu-price-monitor validate-config --config configs/collect.example.json
gpu-price-monitor collect --config configs/collect.example.json --pretty
```

示例配置默认启用 Nebius / Crusoe；认证来源默认关闭。启用 Lambda / UCloud 前应准备好对应 env。每来源 `filters` 支持数组字段：`compute_countries`、`sales_countries`、`regions`、`zones`、`gpu_models`、`gpu_counts`、`billing_modes`、`currencies`，空数组表示不限。各来源支持范围见 [数据口径](DATA_MODEL.md)。

UCloud 的完整 CPU / 内存 / 磁盘等通过 `UCLOUD_PRICE_TARGETS_JSON` 配置，不放入上述通用筛选对象。配置检查不联网，不测试凭据有效性或可售性。

| CLI 选项 | 作用 |
| --- | --- |
| `--providers`、`--config` | 选择来源，或每来源启用状态及筛选 |
| `--gpu`、`--currency`、`--billing-mode` | 可重复的报价筛选 |
| `--region`、`--zone`、`--gpu-count` | 可重复，按来源实际能力验证 |
| `--country`、`--sales-country` | 可重复；当前无法可靠映射，返回错误 |
| `--timeout`、`--max-retries` | 超时秒数和最大重试次数 |
| `--pretty` | 格式化 JSON |

## 环境变量

`Settings.from_env()` 只读取进程环境，**不自动加载 `.env` 文件**。参考 [`.env.example`](../.env.example)，由应用、容器或运行器注入。

| 变量 | 默认值 / 使用范围 |
| --- | --- |
| `GPU_PRICE_MONITOR_PROVIDERS` | 默认 `nebius,crusoe`，可设 `lambda,ucloud` |
| `GPU_PRICE_MONITOR_TIMEOUT_SECONDS` | `30` 秒 |
| `GPU_PRICE_MONITOR_MAX_RETRIES` | `2` 次 |
| `LAMBDA_API_KEY` | Lambda 必填 |
| `UCLOUD_PUBLIC_KEY` / `UCLOUD_PRIVATE_KEY` | UCloud 必填 |
| `UCLOUD_PRICE_TARGETS_JSON` | UCloud 必填，完整目标 JSON 数组 |
| `UCLOUD_PROJECT_ID` | UCloud 可选项目，子账号可能需要 |
| `NEBIUS_ACCESS_TOKEN` | 后续认证估价保留，当前公开文档不需要 |
| `AUTODL_TOKEN` / `AUTODL_STORAGE_STATE_PATH` | 后续 AutoDL 适配器保留 |

读取设置不会发起采集，提供凭据不代表认证已成功。密钥、请求签名和账号原始响应不进入价格返回或日志。真实联调仅使用只读询价，不创建、启动或购买收费实例。

## 调用方上传和运行环境

本库无需 GPU。调用方在自己的应用、定时任务、服务器、容器或 CI 中运行，自己负责频率、重跑、保存、上传和运行成本。库不配置上传 URL、上传令牌、数据库或 Webhook。

```text
调用方注入 env、准备来源和筛选
→ collect_prices(...) / collect CLI
→ 检查来源状态、筛选反馈及价格口径
→ 调用方自己的上传函数（URL、认证、重试）
→ 调用方数据库 / 历史 / 比价 / 通知 / 看板
```

使用 GitHub Actions 时，调用方自行考虑调度延迟、凭据隔离和结果保存。[GitHub 调度规则](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

后续浏览器来源的授权会话由调用方持有和续期，不绕过验证码或访问控制。[Playwright 认证说明](https://playwright.dev/python/docs/auth)
