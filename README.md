# GPU Price Monitor

主要采集 **Nebius、Lambda、Crusoe、AutoDL、UCloud、RunPod** 的 GPU 价格。支持独立 Python 调用及 CLI JSON / CSV；只负责采集、校验、筛选和返回价格，定时、存储、换汇、上传及网站发布由调用方处理。

**0.24.0：每个平台独立 CSV，列随平台变化。** 新增 `provider` 输出，保留该平台真正有用的配置列，不再把不同平台塞进一张宽表。默认英中双语表头，同配置会员价优先；只纳入国家和报价地区有证据的有效小时报价。库保留原币金额，美元换算由调用方显式处理。没有合格地区报价的平台仍返回表头，缺口通过 `provider_csv_coverage(result)` 查看，不能当作零价或全国统一价。

```bash
# 一个来源直接返回专用表格，支持重定向。
gpu-price-monitor collect --env-file .env.five.local --providers ucloud --format csv --csv-profile provider > ucloud.csv
# 多来源各存一份 CSV；目录内已有同名文件时停止，不覆盖旧批次。
gpu-price-monitor collect --env-file .env.five.local --format csv --csv-profile provider --output-dir exports/new-batch
```

```python
from pathlib import Path
from gpu_price_monitor import Settings, collect_prices, prices_to_provider_csvs, provider_csv_coverage

result = collect_prices(settings=Settings.from_env(env_file=".env.five.local"))
tables = prices_to_provider_csvs(result)  # dict[平台名称, CSV字符串]；不写文件、不上传
for provider, content in tables.items():
    Path(f"{provider}.csv").write_text(content, encoding="utf-8", newline="")
print(provider_csv_coverage(result))
```

另新增 **Vast.ai** 官方市场接口的匿名具体机器报价，带卡数、CPU / RAM、8 单位存储和机器公布的地点。该接口暂无已核实的分页 / 全市场总量，所以始终标记 `partial`；只有国家、没有州省的机器不进入严格地区 CSV。[配置](.env.vast.example) · [来源及限制](docs/vast.md)。`--providers all` 目前为十个平台，不表示覆盖每个平台全部产品。

**0.23.0 加入 RunPod 地区起价、会员价优先输出，并扩充 Azure 规格**。RunPod 直接读取官方匿名 GraphQL，不需要登录、密钥或浏览器，Secure / Community 两种云类型分开，不称为会员价。按机房的最低起价与无地区目录价也分开；来源不能证明国家的机房不会进入地区对比。[RunPod 配置](.env.runpod.example) · [范围说明](docs/runpod.md)。Azure 的官方公开 Retail Prices API 已扩为 17 个有硬件规格证据的整卡 SKU，覆盖六个 GPU 型号；不把分卡型号算作整卡，不声称覆盖 Azure 全部产品。[Azure 范围](docs/azure.md)。

```bash
gpu-price-monitor collect --env-file .env.runpod.example --pretty > runpod.json
gpu-price-monitor collect --env-file .env.runpod.example --format csv --csv-profile catalog > runpod.csv
# 使用已有五家配置时显式加上 RunPod；同一资源有会员价时优先输出。
gpu-price-monitor collect --env-file .env.five.local --providers nebius,lambda,crusoe,autodl,ucloud,runpod --format csv --prefer-member-prices > prices.csv
```

会员偏好只删除同一次采集、同资源 ID、同型号配置和同地区的明确普通/会员配对中的普通行，会员条件保留。未配对或有冲突的行不合并；JSON 保留全部原始档位。Python 使用 `prices_to_csv(result, prefer_member=True)` 或 `prefer_member_quotes(result["prices"])`；`--prefer-member-prices` 仅用于 CSV。要排除未核实国家地区的目录价，再加 `--csv-profile compact`。

**0.22.0 修复 UCloud 配置漏价**：按官网规则为 A800 / H20 的少卡配置选择普通网络，保留八卡增强网络；新加坡 P40 的显式空网络选项使用官网默认普通网络。未在当前账号地区目录中出现、或已售罄且没有配置的目录条目单独列为页面范围排除项，不伪造价格，也不当作采集请求失败。详见[五家覆盖与验收](docs/DOCUMENT_COVERAGE.md)。

登录后数据同样可以在服务器或 CI 中定时采集。调用方必须显式提供有效会话 / API 凭据；本库不自动登录、不保证 Cookie 永久有效，也不把认证失败悄悄降级成公开价。部署与续期边界见[云运行说明](docs/DEPLOYMENT.md#调用方的云运行与发布)。

**0.21.0 增加 Lambda 官网与登录目录对账**：`LAMBDA_SOURCE=visible` 同时读取公开价格页和本人登录后可见目录，保留两套来源，比较型号、卡数、CPU、内存、磁盘与金额。不同来源不自动合并，也不借用另一来源的地区；报价条数是来源记录数，不是去重后的配置数。无数值的销售询价不进入此模式价格结果。使用 [配置模板](.env.lambda-visible.example) 与 [说明](docs/lambda-console.md)，`--source-policy configured` 或 `api_preferred`；`api_only` 不允许混入公开 HTML。

本轮核对范围仅为官网公开、当前登录账号可见的 GPU 小时报价，未公开销售价和私人合同不作为补全目标。价格与国家地区分别核实，未确认地区不填“统一价”；失败批次不读取历史样本充当当前报价。UCloud 请求失败现在保留安全的官方操作名和错误码，便于对照网页诊断。

Crusoe 公开价解析已适配官网新的三列 CMS 表格，并校验型号与两类价格的对应关系；结构不匹配会报错，不使用旧报价。

Lambda `visible` 的默认 `market` CSV 只显示国家地区有证据的报价；官网有价但未说明地区的条目保留在 JSON 和 `catalog` / `full` 中。不会为了让公开页新增型号进入地区表而复制登录目录中的地区。

**0.20.0 新增 UCloud UHost 登录态接口采集**，对应原文档的 GPU 配置报价页：显式设置 `UCLOUD_SOURCE=console` 与 `UCLOUD_SESSION_PATH`，程序读取官方国家 / 地区 / 可用区和 GPU 配置目录，逐个配置调用每小时询价接口。默认只确认报价，库存为未知；设置 `UCLOUD_CHECK_AVAILABILITY=true` 可额外核查库存。运行时使用独立 Python HTTP，不需要浏览器或 LLM；UHost 与优云智算 CompShare 分开，不相互替代。优先使用基础 Linux 镜像；无兼容项时选择官方明确支持该 GPU 的预装 Linux 镜像，并核实镜像费用为零。[本地会话、采集范围与价格口径](docs/ucloud-console.md)。

**AutoDL 市场接口已于 2026-10-22 完成实采**：`AUTODL_SOURCE=market` 使用自己从官网导出的最小登录会话，直接请求官方市场 JSON，不启动浏览器或 LLM，支持 `api_only`。本次一次读取 3,372 条市场记录，排除 93 条非 GPU 记录，取得 3,279 个 GPU 资源的普通 / 会员两档报价，共 6,558 行，覆盖 30 个型号、17 个地区代码。其中 3,358 行的国家地区证据完整；其余国家缺证据的地区保留原价与缺口，不猜国家。计费范围是明确的按量每 GPU 小时，不包含包日 / 包月价。[登录会话导出与用法](docs/autodl-market.md)。

**0.18.0 完成 Nebius 账号目录实采**：`NEBIUS_SOURCE=catalog_api` 使用自己的 token，自动发现已有授权项目的 GPU 规格并逐项调用官方估价 API，无需手填 targets。`spot_api` 继续免费取当前 Spot 地区价。Crusoe 完整模式读取官网全部价格格及官方 VM / 部署目录；部署地点不冒充报价地区，销售询价不填金额。[用法和证据边界](docs/nebius-crusoe.md) · [Nebius 配置](.env.nebius.example) · [Crusoe 配置](.env.crusoe.example)。

**2026-10-22 14:21:49（北京时间）Nebius 独立 Python 账号实采**：发现并询价 37 个 GPU preset，取得 **36 条有效计算资源报价，覆盖 9 地区、6 国家**。GB300 的计算费返回零，按 `compute_tariff_unavailable` 留缺口，不当免费 GPU 价格，故结果为 `partial`。主价是含 GPU / CPU / RAM 的每 GPU 小时计算费；40 GiB SSD 单独询价，另存磁盘费与完整配置总价，不混入 GPU 比价。该批未创建资源或绑定付款方式；范围仅为当前账号可访问项目，不代表所有合同或库存，也不据相同金额宣称全球统一。

**2026-10-22 11:53（北京时间）独立 Python 实采**：Nebius 12 条原始 Spot 地区价，覆盖 9 地区、6 国家；Crusoe 7 条明确价格、17 条销售询价记录，另有 17 个文档 GPU 规格和 7 可用区 / 3 国家部署目录。Crusoe 尚无价格地区绑定证据，未进入地区比价主表。[Nebius 地区 CSV](examples/nebius-regional-spot-2026-10-22.csv) · [Crusoe 官网目录 CSV](examples/crusoe-public-catalog-2026-10-22.csv) · [Crusoe 部署目录（非价格表）](examples/crusoe-deployment-catalog-2026-10-22.csv) · [来源与缺口](examples/nebius-crusoe-sources-2026-10-22.json)。这些是带时间的历史样本，程序不会用它们兜底实时采集。

**0.16.0 补全 Lambda 登录目录的国家与地区**：显式 `LAMBDA_SOURCE=console`，免费读取实例、预留集群和地区 JSON；同规格的所列可选标准地区共享目录价，主表展示具体中文国家、地区与 region code，不重复计数，也不宣称全国统一。每次核对当前官方前端代码版本；版本变更或证据不足会保留 JSON 原价、标记 `partial`，不进入主表。无库存、私有或未知地区的目录记录留在 `catalog` / `full` / JSON。无需绑卡、启动 GPU 或调用大模型，Cookie 仅存本地。[配置和边界](docs/lambda-console.md) · [env 模板](.env.lambda.example)。

2026-10-22 **11:21:12（北京时间）本轮实采通过**：36 条 GPU 目录记录中，19 条进入主表（5 个当前可选按需规格、14 个预留集群配置），其余 17 条无当前可选标准地区。该批可选报价均在美国；18 条平台地区元数据不扩展为各国报价。库存和行数随时间变化，集群期限与最终购买条件仍未核实。

[English](README.en.md) · [平台来源与限制](docs/PROVIDERS.md) · [数据口径](docs/DATA_MODEL.md) · [文档需求对照](docs/DOCUMENT_COVERAGE.md)

**0.14.0 新增三家完整公开目录模式**：Nebius 官方费率与明确规格的计算成本、当前地区 Spot 费率，Lambda 按需实例与预留集群条款，以及 Crusoe 全部公开数值和销售询价项。[三平台配置与范围](docs/three-provider-coverage.md)。计算行标明来源公式，不能当作新增独立报价；Nebius 账号目录与 Lambda 控制台会话现已通过上述真实 HTTP 联调，Lambda API key 模式和 Crusoe 合同认证仍待有效凭据验证。

默认 CSV 为 10 列 `market` 小时报价表，包含已核实地区价和明确标注范围的目录价。`catalog` 另保留起价 / 销售询价项（无数值保持空），`compact` 要求国家与价格地区均核实，`full` 保留审计元数据。目录价不复制到多个国家，也不宣称全球统一。

```bash
# 三家无需浏览器或密钥即可运行公开来源；账号字段按需填写。
cp .env.three.example .env.three.local
gpu-price-monitor collect --env-file .env.three.local --pretty > three-prices.json
gpu-price-monitor collect --env-file .env.three.local --format csv --csv-profile catalog > three-catalog.csv
```

**2026-10-21 19:37（北京时间）三家实采样本**：156 行目录、136 行有金额，其中 100 行为明确标注的 Nebius 配置计算，另有 20 行需销售询价；Nebius 当前地区 Spot 源费率只有 12 条，按配置展开不能算新增独立报价。[原币目录 CSV](examples/three-catalog-2026-10-21.csv) · [来源、计数与缺口](examples/three-catalog-sources-2026-10-21.json)。该历史批次不含账号来源；Nebius 账号目录和 Lambda 控制台的后续实测见上文。

**2026-10-21 17:45（北京时间）五家实采全部成功**：111 条有效小时报价，Nebius 17、Lambda 22、Crusoe 8、AutoDL 24、UCloud·优云智算 40；其中 52 条地区已核实，59 条为目录报价。[下载本批 CSV](examples/five-market-2026-10-21.csv) · [来源与请求状态](examples/five-market-sources-2026-10-21.json)。另有 20 条起价 / 询价只留审计，不算有效报价。本批无账号密钥；这不是所有规格、地区或库存的完整清单。

## Clone 后运行五家

Python 3.11+，无需 Codex、LLM 或模型 API Key。无供应商密钥也能运行公开来源；AutoDL 首页来源需要免费的本地 Chromium，授权市场接口无需浏览器依赖。

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
| Nebius | 默认官方匿名 Spot API + 官网 Next.js JSON；可显式选 `catalog_api` 发现账号项目 / preset 并调用官方估价 API | Spot 是地区动态价；账号主价含 VM 的 GPU / CPU / RAM，SSD 另计。公开目录的 From / Contact us 不当确定报价 |
| Lambda | 公开页、密钥 API；另可显式选 `console` 用自己的登录会话读取目录 JSON | 整实例价按卡分摊；经当前前端版本核实，所列可选标准地区共享 SKU 目录价，非逐地区独立询价 |
| Crusoe | Python 固定 HTML 规则解析官网 GPU instances 区块 | 没有已核实的公共 VM 价目 API；不混入账单、预留合同或模型部署费用 |
| AutoDL | `market` 直接读取授权市场 JSON；兼容 `public` 读取首页 DOM | 市场接口返回逐资源地区及普通 / 会员小时 SKU；首页没有价格地区。`market` 采集无需 Playwright |
| UCloud | 显式 `console` 使用自己的登录会话读取 UHost 配置目录并逐项询价；另保留签名 UHost targets 和匿名 CompShare 来源 | `console` 询价绑定具体国家、地区、可用区、GPU / CPU / 内存及明确的基准网络模式；账号报价不代表所有合同，CompShare 不代替 UHost |

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

`market` 与 `compact` 均要求实际数值 `quoted`、`gpu_hour` 和完整 GPU 租用费口径。起步价、GPU 单独组件、月包、Contact sales、资格未核实的特殊优惠及明确下线 / 不可用项不进入报价表。`market` 接受明确标注范围的目录价；Lambda console 的新共享价记录另外要求完整国家地区及当前可选标准容量，其他记录保留完整目录。`compact` 额外要求独立核实的国家与价格地区，Lambda 的共享目录价不满足该条件。未知地区不补成 global。

Python 分别使用 `prices_to_csv(result)`、`prices_to_csv(result, profile="compact")`、`prices_to_csv(result, profile="full")`。`market_eligible_quote` 检查小时目录 / 地区报价资格，`publishable_quote` 保持严格地区资格；对应列常量为 `MARKET_CSV_*`、`COMPACT_CSV_*` 与 `CSV_*`。

完整目录用 `prices_to_csv(result, profile="catalog")`。`gpu_cluster` 为集群产品，集群总卡数与最短预留时长必须一起读取，不能当单机卡数或普通按需价。Nebius `rate_derivation.independent_provider_quote=false` 表示按已公布费率计算，不是账号询价；`provider_results.catalog_coverage` 分别记录原始费率数量和派生配置数量。

Nebius `catalog_api` 的主金额为计算资源费，`instance_price.scope=compute_resources_only`；额外 SSD 保留在 `storage_quote`，含盘完整配置总额保留在 `full_configuration_price`。CSV 条件列说明这些另计费用；网络等未请求的服务不包含在内。

金额保留原币精确十进制字符串，**库不统一换成美元**；月价不除以 720 或其他假定小时数。RackRate 应用另行换汇和发布。CSV 为 UTF-8 BOM / CRLF，不附来源状态表；完整状态、排除原因和审计记录请保留 JSON。stdout 只含所选 JSON 或 CSV，诊断写 stderr；退出码成功 `0`、部分失败 `2`、失败 / 配置错误 `1`。来源成功但所选 profile 无合格行时仅表头，仍退出 `0`。

## 来源策略与环境变量

| 策略 | 行为 |
| --- | --- |
| `api_preferred` | 五家推荐策略；优先价格接口，允许已标明的官网程序解析与网站 JSON。选中接口后失败就报错，不改抓其他页面 |
| `api_only` | 仅允许价格 API；AutoDL 显式 `market`、UCloud 显式 `console` 可用；Nebius 公开来源只取 Spot，显式 `catalog_api` / `api` 可用账号估价，不补网站目录；Crusoe / AutoDL 首页页面来源报 `api_price_source_unavailable` |
| `configured` | 兼容默认，按各 `*_SOURCE` 配置；Nebius 保留旧文档 + Spot，UCloud public 保留旧 UHost 活动月包 |

独立五家模板设置 `GPU_PRICE_MONITOR_PROVIDERS=nebius,lambda,crusoe,autodl,ucloud` 和 `GPU_PRICE_MONITOR_SOURCE_POLICY=api_preferred`。CLI 可覆盖为 `--providers ... --source-policy ...`。通用 `.env.example` 保留 `configured` 兼容行为。

| 可选能力 | 必要配置 |
| --- | --- |
| Lambda 认证实例目录 | `LAMBDA_API_KEY` + `LAMBDA_SOURCE=api`；或免费登录态 `LAMBDA_SOURCE=console` + `LAMBDA_STORAGE_STATE_PATH` |
| UCloud 登录态 UHost 目录询价 | 显式 `UCLOUD_SOURCE=console` + `UCLOUD_SESSION_PATH`；可选 `UCLOUD_PROJECT_ID` 与 `UCLOUD_CHECK_AVAILABILITY`，不需要 API key 或手写 targets，见 [使用说明](docs/ucloud-console.md) |
| UCloud 签名 UHost 完整配置询价 | `UCLOUD_PUBLIC_KEY`、`UCLOUD_PRIVATE_KEY`，及 `UCLOUD_PRICE_TARGETS_FILE` / `UCLOUD_PRICE_TARGETS_JSON` 之一；可选 `UCLOUD_PROJECT_ID` |
| Nebius 账号地区目录 | 显式 `NEBIUS_SOURCE=catalog_api`、`NEBIUS_ACCESS_TOKEN`；自动发现已有授权项目与 preset，无需 targets；SSD 大小 / 币种可选，见 [配置](.env.nebius.example) |
| Nebius 指定完整配置估价 | 显式 `NEBIUS_SOURCE=api`、`NEBIUS_ACCESS_TOKEN`，及 `NEBIUS_PRICE_TARGETS_FILE` / `NEBIUS_PRICE_TARGETS_JSON` 之一；主金额为全部请求资源总额 |
| AutoDL 授权市场 | `AUTODL_SOURCE=market` 与有效 `AUTODL_STORAGE_STATE_PATH`；首页公开采集不用 token |

UCloud 显式 `console` 始终使用登录态 UHost 来源，缺会话或会话失效会报错，不降级成其他产品线。在签名 API 模式下，只填一把 UCloud key 或漏填其 targets 同样会报错。targets 模板不证明账号可售。Nebius `catalog_api`、Lambda 控制台会话及 AutoDL 市场接口已在 2026-10-22 通过独立 Python HTTP 实测；UCloud 签名估价、Lambda API key 模式与 Crusoe 合同认证仍缺有效凭据的真实成功验证，不能以离线测试冒充联调。配置详情见 [PROVIDERS.md](docs/PROVIDERS.md)。密钥、Cookie、私有目标和浏览器会话不得提交或写入结果。

JSON 的 `execution` 声明 Python、固定规则、不使用 LLM 及所选策略；`provider_results` 标明实际来源、`collection_method`、选择原因、回退选择原因和逐平台 `market_quote_count`。`market_comparison` 统计小时目录 / 地区报价；原 `comparison` 继续统计严格地区价。来源采集成功、有效小时报价、地区已核实及实时可购是不同事实。

## 国家、地区与验证边界

`--country` 使用 ISO 两字母代码；`--region` / `--zone` 匹配同一条价格的实际部署位置。Lambda console 的 `--country` / `--region` 则匹配经官方前端核实的共享目录价适用地区，联合条件须由同一个地区条目满足，不代表逐地区独立询价；JSON 的适用范围另存 `price_applicability` / `applicable_*`。平台覆盖、容量列表、公司总部、币种或访问 IP 本身不建立价格地区；缺少地区也不证明统一价。文档供给范围另用 `--coverage-country` / `--coverage-region`。来源不支持筛选时返回 `unsupported_filter`，本应支持却缺证据时返回 `unverifiable_filter`。

本库还保留 DigitalOcean、Verda、Azure 三家独立适配器，`--providers all` 会包含它们；五家模板只运行原文档范围，加入 RunPod 请显式设置六个平台。历史采样仅证明当时来源，见 [examples](examples/README.md)，不作为当前价格或运行时兜底。具体请求、单位、地区证据及认证边界见 [文档对照](docs/DOCUMENT_COVERAGE.md)。

```bash
python -m unittest discover -s tests -v
gpu-price-monitor validate-config --config configs/collect.all.example.json
```
