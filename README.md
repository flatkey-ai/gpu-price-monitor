# GPU Price Monitor

面向原文档五家 **Nebius、Lambda、Crusoe、AutoDL、UCloud** 的 GPU 价格采集库。支持独立 Python 调用及 CLI JSON / CSV；只负责采集、校验、筛选和返回价格，定时、存储、换汇、上传及网站发布由调用方处理。

**0.15.0 新增 Lambda 免费登录态目录接口**：显式 `LAMBDA_SOURCE=console`，使用自己的登录会话只读实例、预留集群和地区 JSON。2026-10-22 已有登录会话实际读取 22 个 GPU 实例规格、14 个集群配置（6 个每GPU费率档）及 18 条地区元数据；独立 Python HTTP 还需自己的保存会话完成联调。无需绑定付款方式或创建资源。会话过期会报错，不回退冒充成功。[配置和边界](docs/lambda-console.md) · [env 模板](.env.lambda.example)。

[English](README.en.md) · [平台来源与限制](docs/PROVIDERS.md) · [数据口径](docs/DATA_MODEL.md) · [文档需求对照](docs/DOCUMENT_COVERAGE.md)

**0.14.0 新增三家完整公开目录模式**：Nebius 官方费率与明确规格的计算成本、当前地区 Spot 费率，Lambda 按需实例与预留集群条款，以及 Crusoe 全部公开数值和销售询价项。[三平台配置与范围](docs/three-provider-coverage.md)。计算行标明来源公式，不能当作新增独立报价；登录后的账号路径需要有效凭据，尚未完成真实鉴权验证。

默认 CSV 为 10 列 `market` 小时报价表，包含已核实地区价和明确标注范围的目录价。`catalog` 另保留起价 / 销售询价项（无数值保持空），`compact` 要求国家与价格地区均核实，`full` 保留审计元数据。目录价不复制到多个国家，也不宣称全球统一。

```bash
# 三家无需浏览器或密钥即可运行公开来源；账号字段按需填写。
cp .env.three.example .env.three.local
gpu-price-monitor collect --env-file .env.three.local --pretty > three-prices.json
gpu-price-monitor collect --env-file .env.three.local --format csv --csv-profile catalog > three-catalog.csv
```

**2026-10-21 19:37（北京时间）三家实采样本**：156 行目录、136 行有金额，其中 100 行为明确标注的 Nebius 配置计算，另有 20 行需销售询价；Nebius 当前地区 Spot 源费率只有 12 条，按配置展开不能算新增独立报价。[原币目录 CSV](examples/three-catalog-2026-10-21.csv) · [来源、计数与缺口](examples/three-catalog-sources-2026-10-21.json)。账号报价仍待有效凭据验证。

**2026-10-21 17:45（北京时间）五家实采全部成功**：111 条有效小时报价，Nebius 17、Lambda 22、Crusoe 8、AutoDL 24、UCloud·优云智算 40；其中 52 条地区已核实，59 条为目录报价。[下载本批 CSV](examples/five-market-2026-10-21.csv) · [来源与请求状态](examples/five-market-sources-2026-10-21.json)。另有 20 条起价 / 询价只留审计，不算有效报价。本批无账号密钥；这不是所有规格、地区或库存的完整清单。

## Clone 后运行五家

Python 3.11+，无需 Codex、LLM 或模型 API Key。无供应商密钥也能运行公开来源；AutoDL 需要免费的本地 Chromium。

```bash
git clone https://github.com/flatkey-ai/gpu-price-monitor.git
cd gpu-price-monitor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install '.[browser]'
python -m playwright install chromium
cp .env.five.example .env.five.local
gpu-price-monitor collect --env-file .env.five.local --pretty > prices.json
# 默认：五家、接口优先、10 列小时报价 CSV。
gpu-price-monitor collect --env-file .env.five.local --format csv > prices.csv
```

Windows PowerShell 使用 `py -3 -m venv .venv` 与 `.\.venv\Scripts\Activate.ps1`。Linux 缺少浏览器依赖时运行 `python -m playwright install --with-deps chromium`。安装、配置与部署见 [DEPLOYMENT.md](docs/DEPLOYMENT.md)。本版本从源码安装，尚未发布至 PyPI；用 `gpu-price-monitor --version` 确认版本。

```python
from pathlib import Path
from gpu_price_monitor import Settings, collect_prices, prices_to_csv

result = collect_prices(
    ["nebius", "lambda", "crusoe", "autodl", "ucloud"],
    settings=Settings(source_policy="api_preferred"),
)
print(result["status"], result["market_comparison"])
# 已含 UTF-8 BOM / CRLF；文件保存由调用方负责。
Path("prices.csv").write_text(prices_to_csv(result), encoding="utf-8", newline="")
```

显式加载本地配置可使用 `Settings.from_env(env_file=".env.five.local")`。直接 `Settings()` 不自动读取 `.env`。进程环境优先于文件，包括空值；不做变量插值或 shell 执行。

## 五家实际怎么采

| 平台 | `api_preferred` 来源 | 核对价格时的限制 |
| --- | --- | --- |
| Nebius | 官方匿名当前 Spot API，加官网 Next.js JSON 目录 | Spot 是地区动态价；JSON 目录补普通按需价。L40S 的 From 和 Contact us 保留审计，不当确定报价 |
| Lambda | 公开页、密钥 API；另可显式选 `console` 用自己的登录会话读取目录 JSON | 美分整实例价按明确卡数分摊；容量地区不是价格地区 |
| Crusoe | Python 固定 HTML 规则解析官网 GPU instances 区块 | 没有已核实的公共 VM 价目 API；不混入账单、预留合同或模型部署费用 |
| AutoDL | Playwright 固定 DOM 规则读取普通 / 会员价 | 无合适公开市场价 API；会员条件保留，首页没有价格地区；可选授权 market 模式 |
| UCloud | 无 key 用旗下优云智算 CompShare 匿名配置询价 API；有任一 key 则要求完整签名 UHost 询价配置 | CompShare 与 UHost 分开标记产品线；普通原价用于比较，资格未核实的优惠价留在审计数据 |

金额由程序直接读取接口或固定页面结构，运行时没有模型解读或推测。Nebius 官网 JSON 是网站数据接口，**不是正式稳定的云价目 API**：程序只从 HTML 取得动态构建路由，实际金额来自后续 JSON。UCloud 前端目录只用于发现可询价配置，金额必须取自实际询价响应。

## CSV 四种输出

```bash
# 默认 market：有效每 GPU 小时目录价 + 地区价，10 列。
gpu-price-monitor collect --env-file .env.five.local --format csv > prices.csv
# compact：只要国家与价格地区都已核实的每 GPU 小时价，10 列。
gpu-price-monitor collect --env-file .env.five.local --format csv --csv-profile compact > prices.regional.csv
# catalog：10 列目录表，保留明确标注的起价与销售询价项，询价金额留空。
gpu-price-monitor collect --env-file .env.three.local --format csv --csv-profile catalog > catalog.csv
# full：全部原始记录，原 51 列审计表。
gpu-price-monitor collect --env-file .env.five.local --format csv --csv-profile full > prices.audit.csv
# 程序读取可选择固定英文表头。
gpu-price-monitor collect --env-file .env.five.local --format csv --csv-headers english > prices.english.csv
```

10 列为：**GPU 型号及配置、平台、报价适用范围、每 GPU 金额、币种、单位、价格条件、可用状态、官方来源、采集时间**。默认表头英中双语；普通 / 会员、Spot、税费、账号条件、来源明确的实例总价及 UCloud 产品线仍保留。

`market` 与 `compact` 均要求实际数值 `quoted`、`gpu_hour` 和完整 GPU 租用费口径。起步价、GPU 单独组件、月包、Contact sales、资格未核实的特殊优惠及明确下线 / 不可用项不进入报价表。`market` 接受明确标注范围的目录价，缺少地区不再把真实目录报价藏掉；`compact` 额外要求已核实国家与价格地区。未知地区不补成 global。

Python 分别使用 `prices_to_csv(result)`、`prices_to_csv(result, profile="compact")`、`prices_to_csv(result, profile="full")`。`market_eligible_quote` 检查小时目录 / 地区报价资格，`publishable_quote` 保持严格地区资格；对应列常量为 `MARKET_CSV_*`、`COMPACT_CSV_*` 与 `CSV_*`。

完整目录用 `prices_to_csv(result, profile="catalog")`。`gpu_cluster` 为集群产品，集群总卡数与最短预留时长必须一起读取，不能当单机卡数或普通按需价。Nebius `rate_derivation.independent_provider_quote=false` 表示按已公布费率计算，不是账号询价；`provider_results.catalog_coverage` 分别记录原始费率数量和派生配置数量。

金额保留原币精确十进制字符串，**库不统一换成美元**；月价不除以 720 或其他假定小时数。RackRate 应用另行换汇和发布。CSV 为 UTF-8 BOM / CRLF，不附来源状态表；完整状态、排除原因和审计记录请保留 JSON。stdout 只含所选 JSON 或 CSV，诊断写 stderr；退出码成功 `0`、部分失败 `2`、失败 / 配置错误 `1`。来源成功但所选 profile 无合格行时仅表头，仍退出 `0`。

## 来源策略与环境变量

| 策略 | 行为 |
| --- | --- |
| `api_preferred` | 五家推荐策略；优先价格接口，允许已标明的官网程序解析与网站 JSON。选中接口后失败就报错，不改抓其他页面 |
| `api_only` | 仅允许价格 API；Nebius 只取当前 Spot，不补网站目录；Crusoe / AutoDL 页面来源报 `api_price_source_unavailable` |
| `configured` | 兼容默认，按各 `*_SOURCE` 配置；Nebius 保留旧文档 + Spot，UCloud public 保留旧 UHost 活动月包 |

独立五家模板设置 `GPU_PRICE_MONITOR_PROVIDERS=nebius,lambda,crusoe,autodl,ucloud` 和 `GPU_PRICE_MONITOR_SOURCE_POLICY=api_preferred`。CLI 可覆盖为 `--providers ... --source-policy ...`。通用 `.env.example` 保留 `configured` 兼容行为。

| 可选能力 | 必要配置 |
| --- | --- |
| Lambda 认证实例目录 | `LAMBDA_API_KEY` + `LAMBDA_SOURCE=api`；或免费登录态 `LAMBDA_SOURCE=console` + `LAMBDA_STORAGE_STATE_PATH` |
| UCloud 签名 UHost 完整配置询价 | `UCLOUD_PUBLIC_KEY`、`UCLOUD_PRIVATE_KEY`，及 `UCLOUD_PRICE_TARGETS_FILE` / `UCLOUD_PRICE_TARGETS_JSON` 之一；可选 `UCLOUD_PROJECT_ID` |
| Nebius 账号完整配置估价 | 显式 `NEBIUS_SOURCE=api`、`NEBIUS_ACCESS_TOKEN`，及 `NEBIUS_PRICE_TARGETS_FILE` / `NEBIUS_PRICE_TARGETS_JSON` 之一 |
| AutoDL 授权市场 | `AUTODL_SOURCE=market` 与有效 `AUTODL_STORAGE_STATE_PATH`；首页公开采集不用 token |

只填一把 UCloud key 或漏填 targets 会报错，不降级成其他产品线。targets 模板不证明账号可售；账号估价、Lambda 认证目录和 AutoDL 登录市场仍需有效凭据完成真实成功验证，不能用离线测试冒充联调。配置详情见 [PROVIDERS.md](docs/PROVIDERS.md)。密钥、Cookie、私有目标和浏览器会话不得提交或写入结果。

JSON 的 `execution` 声明 Python、固定规则、不使用 LLM 及所选策略；`provider_results` 标明实际来源、`collection_method`、选择原因、回退选择原因和逐平台 `market_quote_count`。`market_comparison` 统计小时目录 / 地区报价；原 `comparison` 继续统计严格地区价。来源采集成功、有效小时报价、地区已核实及实时可购是不同事实。

## 国家、地区与验证边界

`--country` 使用 ISO 两字母代码；`--region` / `--zone` 匹配同一条价格的实际部署位置。平台覆盖、容量列表、公司总部、币种或访问 IP 不当价格地区；缺少地区也不证明统一价。文档供给范围另用 `--coverage-country` / `--coverage-region`。来源不支持筛选时返回 `unsupported_filter`，本应支持却缺证据时返回 `unverifiable_filter`。

本库还保留 RunPod、DigitalOcean、Verda、Azure 四家独立适配器，`--providers all` 会包含它们；五家模板只运行原文档范围。历史采样仅证明当时来源，见 [examples](examples/README.md)，不作为当前价格或运行时兜底。具体请求、单位、地区证据及认证边界见 [文档对照](docs/DOCUMENT_COVERAGE.md)。

```bash
python -m unittest discover -s tests -v
gpu-price-monitor validate-config --config configs/collect.all.example.json
```
