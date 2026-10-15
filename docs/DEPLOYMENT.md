# 配置与调用方接入

本项目提供采集库和命令行工具。当前支持 Nebius 和 Crusoe 的官方公开价格来源，无需账号凭据；Lambda、UCloud 和 AutoDL 返回 `not_implemented`。

## 安装和直接调用

要求 Python 3.11+。当前从源码安装，尚未发布 PyPI 版本：

```bash
python3 -m pip install -e .
gpu-price-monitor status
gpu-price-monitor collect --providers nebius,crusoe --currency USD --billing-mode on_demand --pretty
```

Python API 返回标准字典：

```python
from gpu_price_monitor import collect_prices, Settings

result = collect_prices(
    providers=["nebius", "crusoe"],
    filters={"currencies": ["USD"], "billing_modes": ["on_demand"]},
    settings=Settings.from_env(),
)
```

`result` 可通过 `json.dumps` 序列化，或由调用方交给自己的上传函数。无网络、来源改版等情况应检查 `status`、`provider_results` 和报价数量，不能仅因 API 调用正常返回就认定价格完整。

## 配置文件

```bash
gpu-price-monitor validate-config --config configs/collect.example.json
gpu-price-monitor collect --config configs/collect.example.json --pretty
```

示例中 Nebius 和 Crusoe 为 `enabled=true`，其余来源为 `false`。每个来源有独立 `filters`，包含 `compute_countries`、`sales_countries`、`regions`、`zones`、`gpu_models`、`gpu_counts`、`billing_modes` 和 `currencies`；空数组表示未限定。配置还包含请求超时和重试选项。

GPU 型号、币种和计费方式可在两个来源上筛选。地区仅 Nebius 可验证；Crusoe 的地区筛选返回 `unsupported_filter`。两个来源当前均无法可靠验证国家、可用区和卡数筛选，传入这些条件会返回结构化错误。SKU、CPU、内存和磁盘筛选尚未加入当前配置格式。

配置校验只检查格式，不联网，也不验证凭据能否访问厂商。执行采集时才核对来源支持的筛选能力。

## CLI 选项与返回码

| 选项 | 作用 |
| --- | --- |
| `--providers nebius,crusoe` | 选择来源 |
| `--config PATH` | 使用每来源启用状态及筛选配置 |
| `--gpu`、`--currency`、`--billing-mode` | 可重复的报价筛选 |
| `--region` | 可重复；当前仅 Nebius 可验证 |
| `--country`、`--sales-country`、`--zone`、`--gpu-count` | 可重复；当前来源无法核对时显式报错 |
| `--timeout`、`--max-retries` | 请求超时秒数和最大重试次数 |
| `--pretty` | 格式化 JSON |

限定地区时仅选择支持该筛选的来源：

```bash
gpu-price-monitor collect --providers nebius --region eu-north1 --pretty
```

`collect` 的 stdout 只写 JSON，诊断写 stderr。退出码 `0` 为全部成功或没有匹配项，`2` 为部分来源失败，`1` 为全部失败或配置无效。调用方捕获输出时应保留返回码，避免把部分结果当成完整结果。

## 环境变量

配置通过 `Settings.from_env()` 从进程环境读取，**不自动加载 `.env` 文件**。参考 [`.env.example`](../.env.example)，由应用、容器或运行器注入。

| 变量 | 默认值 / 使用范围 |
| --- | --- |
| `GPU_PRICE_MONITOR_PROVIDERS` | `nebius,crusoe`，逗号分隔 |
| `GPU_PRICE_MONITOR_TIMEOUT_SECONDS` | `30` 秒 |
| `GPU_PRICE_MONITOR_MAX_RETRIES` | `2` 次 |
| `LAMBDA_API_KEY` | 后续 Lambda 适配器保留 |
| `NEBIUS_ACCESS_TOKEN` | 后续认证估价分支保留；当前公开文档不需要 |
| `UCLOUD_PUBLIC_KEY` / `UCLOUD_PRIVATE_KEY` | 后续 UCloud 询价适配器保留 |
| `AUTODL_TOKEN` / `AUTODL_STORAGE_STATE_PATH` | 后续 AutoDL API / 浏览器适配器保留 |

只读取设置不会发起采集，设置凭据也不会启用未实现来源。密钥不放进采集 JSON、返回结果或日志。请求超时和重试需在合理范围内，遵守来源访问限制。

## 调用方上传和运行环境

本库无需 GPU。调用方可在自己的应用进程、定时任务、服务器、容器或 CI 中运行，自己负责频率、重跑、结果保留和运行成本。

```text
调用方注入 env、准备来源和筛选
→ collect_prices(...) / collect CLI
→ 检查各来源状态、过滤反馈及原始价格口径
→ 调用方自己的上传函数（自有 URL、认证、重试）
→ 调用方数据库 / 历史 / 比价 / 通知 / 看板
```

库不配置上传 URL、上传令牌、数据库连接或 Webhook。Flatkey 和其他使用者分别在自己的系统完成这些操作。

如使用 GitHub Actions，调用方自行考虑计划任务延迟或停用、凭据隔离和结果保存。[GitHub 调度规则](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

后续浏览器来源的授权会话需由调用方持有和续期，不绕过验证码或访问控制。[Playwright 认证说明](https://playwright.dev/python/docs/auth)
