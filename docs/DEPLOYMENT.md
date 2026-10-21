# 安装和接入五家采集

0.13.0 推荐 **Nebius、Lambda、Crusoe、AutoDL、UCloud**。库提供独立 Python 与 CLI，只返回 JSON / CSV 文本；调用方负责定时、保存、换汇和发布。没有 Codex、LLM、模型 API Key 或人工读页的运行时依赖。

## 本地或服务器运行

```bash
git clone https://github.com/flatkey-ai/gpu-price-monitor.git
cd gpu-price-monitor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install '.[browser]'
python -m playwright install chromium
cp .env.five.example .env.five.local
gpu-price-monitor status --env-file .env.five.local
gpu-price-monitor collect --env-file .env.five.local --pretty > prices.json
gpu-price-monitor collect --env-file .env.five.local --format csv > prices.csv
```

Windows PowerShell 使用 `py -3 -m venv .venv` 与 `.\.venv\Scripts\Activate.ps1`。Linux 容器可安装 `python -m playwright install --with-deps chromium`。AutoDL 的免费本地 Chromium 需要浏览器依赖；不采 AutoDL 时可以只装基础包并显式选择其余平台。

`.env.five.example` 设置五家与 `api_preferred`。复制到独立 `.env.five.local`，保留已有 `.env`；密钥留空可运行公开来源。直接 Python：

```python
from gpu_price_monitor import Settings, collect_prices, prices_to_csv

settings = Settings.from_env(env_file=".env.five.local")
result = collect_prices(settings=settings)
csv_text = prices_to_csv(result)
```

若调用签名 API，请先填写真实目标和完整密钥；不使用示例未验证配置为默认运行目标。`Settings()` 不读文件，`Settings.from_env` / `--env-file` 显式加载；进程变量优先，包括空值。不执行 shell / 插值。FILE 路径相对 env 文件目录解析；FILE / JSON 目标来源互斥。

## 三种 CSV

```bash
# 默认 market：10 列真实小时目录价 + 地区价。
gpu-price-monitor collect --env-file .env.five.local --format csv > prices.csv
# compact：10 列严格国家与价格地区已核实的小时价。
gpu-price-monitor collect --env-file .env.five.local --format csv --csv-profile compact > prices.regional.csv
# full：原 51 列全部来源审计。
gpu-price-monitor collect --env-file .env.five.local --format csv --csv-profile full > prices.audit.csv
```

默认英中双语，`--csv-headers english` 用稳定英文 ID。Python 默认 `prices_to_csv(result)`，另可用 `profile="compact"` 或 `profile="full"`；金额不换汇，月价不换算小时。UTF-8 BOM / CRLF 已在返回文本中，调用方保存时用 `encoding="utf-8", newline=""`，无需再加 BOM。

market 接受标明适用范围的有效目录，不因官网未给地区就隐藏；目录不是全球统一价，也不能据此筛出任意国家。compact 保持原严格地区规则。起价、GPU 组件、月包、询价、未核实特殊优惠与明确不可用项仅在 full / JSON 审计。详细资格见 [DATA_MODEL.md](DATA_MODEL.md)。

stdout 只含 JSON 或 CSV，stderr 为诊断和投影计数。退出码成功 `0`、部分失败 `2`、失败 / 配置无效 `1`；来源成功但所选 profile 无合格行时只表头且仍退出 `0`。CSV 文件存在不证明全部来源成功，调用方应同时保存 JSON 状态。

## 策略与可选凭据

- `api_preferred`：五家推荐。Nebius 当前 Spot 加官网 JSON 普通目录；Lambda 依 key 选择接口 / 公开页；UCloud 无 key 为 CompShare 匿名小时询价，有任一 key 则要求完整签名 UHost 目标；Crusoe / AutoDL 固定页面规则。
- `api_only`：只允许价格 API；Nebius 只有 Spot，Crusoe / AutoDL 页面来源报不支持。不是换个标签把页面算作 API。
- `configured`：兼容各 `*_SOURCE`；Nebius public 为旧文档 + Spot，UCloud public 为旧 UHost 月促销。通用 `.env.example` 保留此策略。

`GPU_PRICE_MONITOR_SOURCE_POLICY` 或 `--source-policy` 选择策略。已经选中的 API 若配置 / 鉴权 / 解析失败就报错，不降级成其他产品线或网页目录。

| 可选路径 | 配置 |
| --- | --- |
| Lambda 认证实例目录 | `LAMBDA_API_KEY`，或显式 `LAMBDA_SOURCE=api` |
| UCloud 签名 UHost | 完整 `UCLOUD_PUBLIC_KEY` / `UCLOUD_PRIVATE_KEY` 与 targets FILE / JSON，可选项目 ID；有任一 key 就要求补齐，不回退 CompShare |
| Nebius 账号估价 | 显式 `NEBIUS_SOURCE=api`、`NEBIUS_ACCESS_TOKEN` 与完整 targets FILE / JSON |
| AutoDL 授权市场 | `AUTODL_SOURCE=market`、有效 `AUTODL_STORAGE_STATE_PATH` |

无 key 的 CompShare 询价不需要这些账号配置，输出仍须标明 UCloud 旗下 CompShare 产品线、普通原价及请求地区 / 配置；优惠资格未知只审计。配置发现目录里的价格不作为返回值。

账号估价、Lambda 认证、签名 UHost 与 AutoDL 登录市场尚需有效凭据成功联调，离线测试不证明账号取价成功。`.env`、`.env.*.local`、私有 `*.local.json`、浏览器状态和 Cookie 不提交、不打印、不放进结果。

## 调用方的云运行与发布

任何普通云任务、容器或 CI 都可运行相同 CLI，不要求用户电脑开机。调用方自行安装 Python / AutoDL Chromium、配置网络和所需授权，安排其调度器；本库不内置 RackRate / Flatkey 上传地址、业务凭据或发布流程。

发布前检查退出码、`provider_results`、`market_comparison` 和所需位置条件，决定是否接受部分结果。`comparison` 保持严格地区统计，不是默认 market 总行数。换汇应另记汇率来源 / 日期，原价与条件仍保留；不能把失败来源写成零价，也不能给旧价盖新采集时间。

原文档五家优先运行；`--providers all` 会额外采 RunPod、DigitalOcean、Verda、Azure。相关配置与验证边界见 [PROVIDERS.md](PROVIDERS.md)。

## 验证

```bash
python -m compileall -q src
python -m unittest discover -s tests -v
gpu-price-monitor validate-config --config configs/collect.all.example.json
```

真实采集的 source / method / URL / timestamp 和本次配置诊断比历史样本条数更重要。历史 examples 仅作审计，不作现价或运行时回退。
