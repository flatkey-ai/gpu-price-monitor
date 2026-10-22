# Lambda 免费登录态采集

`LAMBDA_SOURCE=console` 免费读取已有账号可见的 JSON 目录，无需创建 API key、绑定支付卡或启动 GPU。价格由独立 Python HTTP 请求和固定字段解析取得，不依赖 Codex 或大模型；浏览器只用于用户手动登录和保存会话。

**0.16.0 补充国家、地区与统一目录价的适用范围**。同一 SKU 在控制台所列可选标准地区共享一个目录价，主表会写出具体国家、地区中文名及 region code。只描述该规格当前列出的地区，不扩大为全国或全球统一价，也不将一条目录价复制为多个独立地区报价。预留期限、税费、合同折扣与最终购买价仍须另行确认。

本轮验证：2026-10-22 **11:21:12（北京时间，UTC+8）**，独立 Python / HTTP 采集为 `success`，当前官方前端版本核对通过。读取 36 条 GPU 目录报价：22 个按需实例规格、14 个预留集群配置（6 个型号/费率档）；主表为 **19 条：5 个当前可选按需规格、14 个集群配置**，其余 17 条当前无可选标准地区。另审计排除 2 个 CPU 规格。该批当前可选报价均在美国；地区元数据虽有 18 个地区、6 个国家，不能把无对应可选 SKU 的国家补成报价。库存和行数随采集时间变化，JSON 保留完整目录与排除原因。

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

公开页与登录目录会有差异：本轮公开页列出 4×B200，账号目录没有该配置；账号目录另外列出两个不同 V100 SKU。各自来源分别保留，不把公开页数据插入接口结果。`provider_results` 的目录覆盖仍标 `all_prices_complete=false`；所有合同折扣、容量预留或最终结算价不能宣称已全部获取。

官网对照：[公开价格](https://lambda.ai/pricing)、[1-Click Clusters](https://lambda.ai/1-click-clusters)、[计费说明](https://docs.lambda.ai/public-cloud/billing/)、[公开 API 文档](https://docs.lambda.ai/api/cloud)。
