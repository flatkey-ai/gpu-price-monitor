# Lambda 免费登录态采集

`LAMBDA_SOURCE=console` 免费读取已有账号可见的 JSON 目录，无需创建 API key、绑定支付卡或启动 GPU。价格由独立 Python HTTP 请求和固定字段解析取得，不依赖 Codex 或大模型；浏览器只用于用户手动登录和保存会话。

**0.16.0 补充国家、地区与统一目录价的适用范围**。同一 SKU 在控制台所列可选标准地区共享一个目录价，主表会写出具体国家、地区中文名及 region code。只描述该规格当前列出的地区，不扩大为全国或全球统一价，也不将一条目录价复制为多个独立地区报价。预留期限、税费、合同折扣与最终购买价仍须另行确认。

本轮验证：2026-10-23 **10:57:39（北京时间，UTC+8）**，独立 Python / HTTP 采集为 `success`，当前官方前端版本重新核对通过。读取 36 条 GPU 目录报价：22 个按需实例规格、14 个预留集群配置（6 个型号/费率档）；主表为 **17 条：3 个当前可选按需规格、14 个集群配置**，其余 19 条当前无可选标准地区。另审计排除 2 个 CPU 规格。该批当前可选报价覆盖美国和印度；A100 SXM4 单卡列有 `asia-south-1`（India）。地区元数据虽有 18 个地区、6 个国家，不能把无对应可选 SKU 的国家补成报价。库存和行数随采集时间变化，JSON 保留完整目录与排除原因。

这些是控制台内部接口，可能变更，不是承诺稳定的公开云 API。价格和地区数据来自下列 GET：

- `https://cloud.lambda.ai/api/internal/dashboard/v1/instance-types`
- `https://cloud.lambda.ai/api/internal/dashboard/v1/cluster-types/reserved`
- `https://cloud.lambda.ai/api/internal/dashboard/v1/regions`

程序还会读取固定的 `https://cloud.lambda.ai/instances` 页面，发现当前官方入口 JavaScript，并匿名获取该脚本核对 SHA-256。只有与代码中人工核查过的版本一致，才确认“所列可选地区统一目录价”。页面与脚本不提供报价金额，也不由 Codex 解析。入口版本变更、请求失败或哈希不符时，接口返回的原始金额仍保留在 JSON，结果为 `partial`，主 CSV 不接收无法核实适用地区的报价；不会沿用旧代码版本冒充本次确认。已核查版本与证据以 `providers/lambda_locations.py` 和结果中的 `price_applicability.evidence` 为准。

## 本地登录一次

安装 Python 3.11+，在仓库目录执行：

```bash
python -m pip install '.[browser]'
python -m playwright install chromium
cp .env.lambda.example .env.lambda.local
gpu-price-monitor lambda-login --state-file playwright/.auth/lambda.storage-state.json
```

命令会打开全新的浏览器，请自行登录 Lambda。程序不输入密码、不读取个人 Chrome 配置、不操作付款或创建资源。确认实例目录 GET 返回成功后，仅保存 Lambda 域 Cookie，文件权限为 `0600`，不覆盖已有文件。会话文件等同于账号凭据，包含的权限由供应商会话决定；库自身只读不代表 Cookie 本身只有读权限。只在自己授权的账号使用，文件已被 Git 忽略。

已有自己准备的 Playwright storage-state 文件，也可直接设置 `LAMBDA_STORAGE_STATE_PATH`，无须安装浏览器依赖。相对路径以 `.env` 所在目录为准。采集时使用 Python HTTP，不启动浏览器或调用大模型。

会话 Cookie 只发送到同一官方域下固定的 `/instances` 入口和上述三个 JSON 路径；公开 JavaScript 使用匿名请求，不携带 Cookie。会话文件仅保存在用户授权的本地位置，不会自动上传到云端或网站部署环境。

## JSON、CSV 和 Python

```bash
gpu-price-monitor collect --env-file .env.lambda.local --pretty > lambda-prices.json
gpu-price-monitor collect --env-file .env.lambda.local --format csv > lambda-prices.csv
# 完整目录：还保留无库存、私有地区及国家信息待核实的目录记录。
gpu-price-monitor collect --env-file .env.lambda.local --format csv --csv-profile catalog > lambda-catalog.csv
gpu-price-monitor collect --env-file .env.lambda.local --format csv --csv-profile full > lambda-audit.csv
# 同一条适用地区同时满足国家和 region；不是发起该地区独立询价。
gpu-price-monitor collect --env-file .env.lambda.local --country US --region us-east-3 --format csv > lambda-us-east-3.csv
```

```python
from gpu_price_monitor import Settings, collect_prices, prices_to_csv

settings = Settings.from_env(env_file=".env.lambda.local")
result = collect_prices(["lambda"], settings=settings)
print(result["status"])
csv_text = prices_to_csv(result)  # UTF-8 BOM，中英双语 10 列
```

## 官网与当前账号一起核对

`LAMBDA_SOURCE=visible` 独立读取官网公开价格页以及上述三个登录目录，不需要新增密钥或购买资源。也可以保留原 `.env.lambda.local`，用 CLI 覆盖选择：

```bash
gpu-price-monitor collect --providers lambda --env-file .env.lambda.local --lambda-source visible --source-policy configured --pretty > lambda-visible.json
gpu-price-monitor collect --providers lambda --env-file .env.lambda.local --lambda-source visible --source-policy configured --format csv > lambda-region-prices.csv
gpu-price-monitor collect --providers lambda --env-file .env.lambda.local --lambda-source visible --source-policy configured --format csv --csv-profile catalog > lambda-visible-catalog.csv
```

Python 使用相同设置：

```python
from dataclasses import replace
from gpu_price_monitor import Settings, collect_prices

settings = replace(Settings.from_env(env_file=".env.lambda.local"),
                   lambda_source="visible", source_policy="configured")
result = collect_prices(["lambda"], settings=settings)
coverage = result["provider_results"][0]["catalog_coverage"]
print(coverage["reconciliation"])
```

这里显式使用 `configured`，因为原 `.env.lambda.local` 可能设置为 `api_only`；后者按设计禁止读取公开网页，与双来源模式不兼容。

2026-10-23 10:57:39 本轮，官网共 30 行：**28 条有价记录（22 按需、6 预留）**，2 条只有销售询价、没有金额，排除出价格结果；登录目录为 **36 条**。合计 **64 条来源记录**，不是 64 种互不重复的配置。公开的 4×B200 **6.79 USD / GPU / 小时**已保留，当前账号目录没有同型号、同卡数的候选行；官网没有注明地区，因此不会借用其他 B200 卡数的地区补入主表。

两个来源同时展示的价格不自动去重或覆盖。对账只用型号和卡数挑选候选，再逐项比较版本、显存、CPU、RAM、磁盘和单价；同价不代表同规格。例如本轮 H100 PCIe 单卡公开页为 225 GiB RAM，账号为 200 GiB RAM，程序将差异写入 `catalog_coverage.reconciliation.on_demand_checks`，各自的原值、来源及地区范围保持独立。磁盘仅按明确 GiB/TiB 单位做精确转换，不把近似展示值四舍五入成相同规格。公开集群的预留期限与卡数档位也保留，不能和未核实预留期限的账号集群合并。

`visible_source` 和 `visible_record_id` 区分来源记录；`requested_sources_collected` 只说明本次指定页面/目录全部读取成功，不代表整个产品中所有可能页面、功能开关或账号权限都已核查。会话失效仍返回 `partial` 和明确错误，不会用官网成功掩盖账号失败。主表继续只收已核实适用国家地区的报价；完整来源目录通过 JSON、`catalog`、`full` 查看。没有公开金额的销售询价、私下合同、购买资源后才能看到的价格不属于此模式的采集范围。

会话过期、权限不足或字段变化会明确报错，不换成旧快照或官网价冒充成功。三个目录分别处理，某一项失败时保留其他成功结果；尚有成功价格时状态为 `partial`，仅地区元数据成功而两个价格目录均失败时，价格采集仍为 `failed`。登录失效时，请重新登录并保存到新文件，再更新 env 路径。

## 如何读价格

按需 API 的 `price_cents_per_hour` 是整实例美分小时价：除以 100，再除实例 GPU 数，得到 USD / GPU / 小时。原始 SKU、卡数和整实例价同时保留。空库存不等于下线；对应有价配置留在 JSON、`catalog` 与 `full`，不进入当前可选报价主表。

预留集群采用官方前端使用的 `price_cents_per_gpu_hour / 100`。本轮 14 个配置对应 6 个型号/价格档，不能叫作 14 种独立 GPU 费率。接口内旧的集群、节点总价与每 GPU 价存在冲突，较低字段不会代替显示单价，原始值留作审计。按周结算，具体预留期限、账号资格、税费与最终下单条件尚未验证，CSV 会明确提示。

`regions_with_capacity_available`、`regions_available` 提供本 SKU 的可选容量地区；经当前官方前端代码核查，选择标准地区沿用该 SKU 的目录单价，不另取地区价格。因此主表可以准确写出“所列地区共享目录价”，但不能改成“每个地区独立询价”或推断其他未列地区同价。

例如，本轮 A10 单卡规格 `gpu_1x_a10` 的目录价为 **1.29 USD / GPU / 小时**，同一行的适用范围显示为：

> 统一目录价｜美国·弗吉尼亚州（us-east-1）、美国·加利福尼亚州（us-west-1）

价格条件同时说明：同规格在所列可选地区共享目录价；非逐地区独立询价；不保证税费、合同与最终购买价。示例来自上述采集时点，后续库存和价格以新一轮结果为准。

国家与地区中文名根据接口的官方描述逐项映射，保留原描述和 region code，不凭 region 前缀、币种、总部或平台全部覆盖地区推断。未知描述不会猜国家。私有 `dedicated` 地区不共享标准目录价声明，其访问资格和价格仍待核实。

`market` 主表只保留至少一个当前可选标准地区、且所列地区国家与地区信息完整的 SKU。同一个 SKU 无论有几个适用地区都只计一条。无库存、仅私有容量、国家未核实或前端版本未核实的记录留在 JSON、`catalog` 和 `full`；无库存的目录行明确显示“统一目录价；当前无可选地区（无库存）”。

JSON 将共享目录价范围另存于 `price_applicability`、`applicable_regions` 与 `applicable_countries`。`regions`、`compute_countries` 仍为空，`region_price_verified=false`，因为没有取得逐地区独立报价。`--country` / `--region` 在 Lambda console 模式匹配该 SKU 经核实的共享价适用地区；联合筛选必须由同一个地区条目同时满足。筛选不会扩大范围或改变报价金额。`compact` 继续要求独立地区价格证据，因此不收录这些共享目录报价。

公开页与登录目录会有差异：本轮公开页列出 4×B200，账号目录没有该配置；账号目录另外列出两个不同 V100 SKU。`console` 只保留接口自身的记录；`visible` 同时保留两种来源及对账结果。`provider_results` 的目录覆盖仍标 `all_prices_complete=false`，不会把范围之外的销售询价或未证实账号可见的功能报价算作已完成。

2026-10-23 前端证据复核：[当前主脚本](https://cloud.lambda.ai/static/cloud-app/assets/main-BdOFEme8.js) 的 SHA-256 为 `becc45eec9df69c8089947297b2958c047a618fedf8dbb6787806c46c346fa6c`。`lW` 读取实例目录、`rW` 展示 `price_cents_per_hour` 及按卡数分摊的价格，`uW` 的标准地区选择不更新金额或另发地区询价；专用地区隐藏标准目录价格。集群 `GF` 读取 `price_cents_per_gpu_hour`，地区选择只改地区状态。[对应 common 脚本](https://cloud.lambda.ai/static/cloud-app/assets/common-DirxWaW8.js) 的 `Br` 导出仍按美分除以 100 展示美元。更新此证据前，新版本已被程序正确标记为地区未核实；以后未知版本仍会如此处理。

官网对照：[公开价格](https://lambda.ai/pricing)、[1-Click Clusters](https://lambda.ai/1-click-clusters)、[计费说明](https://docs.lambda.ai/public-cloud/billing/)、[公开 API 文档](https://docs.lambda.ai/api/cloud)。

2026-10-27 再次逐项复核[当前主脚本](https://cloud.lambda.ai/static/cloud-app/assets/main-Bqe423_X.js)，SHA-256 为 `dcdf86c8907b3ff9bd862b5070f80fdb295125e9a34d5649fb569fba9f26acb9`（1,079,756 字节）。新版本 `fW` 读取实例目录，`oW` 展示相同 SKU 的 `price_cents_per_hour` 与按 GPU 数分摊的价格；`pW` 仅将该 SKU 的 `regions_with_capacity_available` 标为可选地区，切换地区不重新询价，专用工作区仍隐藏标准价格。集群 `JF` 仍选择 `price_cents_per_gpu_hour`，`DI` 的地区选择仅使用当前集群规格的 `regions_available` 并改变选择状态。公共 common 脚本仍为同一个 `common-DirxWaW8.js`。程序只将这两个已复核版本的精确 URL／摘要组合视作历史地区证据；实时版本校验只接受本次复核摘要，之后未知版本继续保留价格并撤下共享地区声明。复核摘录保存在 `tests/fixtures/lambda-console-frontend-review-20261027.json`。这些证据只支持所列标准地区共享 SKU 目录价，仍不代表全国、全球统一价格或最终成交价。
