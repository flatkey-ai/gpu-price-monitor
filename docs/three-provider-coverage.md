# Nebius、Lambda、Crusoe 三家完整目录

0.17 新增 [Nebius 地区 Spot / 账号发现估价及 Crusoe 部署目录](nebius-crusoe.md)。以下历史样本计数仍以原采集时间为准；当前官网数值、销售询价和地区目录须重新采集。

`catalog_scope=complete` 用于逐项清点三家的公开价格目录、已公布配置、预留条件和缺口。**完整目录不是所有地区和所有账号的最终成交价，也不是每一条配置都新增了一次独立询价。** Contact sales、未核实单位及账号权限缺口必须保留，不能以零价或计算行数掩盖。

## 独立运行

下面的公开来源示例使用 Python 3.11+，安装基础包即可，不需要 AutoDL 的浏览器依赖，也不需要 Codex、LLM 或模型 API Key。可选 Lambda console 模式的手动登录与保存会话另见下文；后续 HTTP 采集仍不启动浏览器。

```bash
python -m pip install .
cp .env.three.example .env.three.local
gpu-price-monitor status --env-file .env.three.local
gpu-price-monitor collect --env-file .env.three.local --catalog-scope complete --pretty > three-prices.json
# 默认 10 列有效小时目录 / 地区报价。
gpu-price-monitor collect --env-file .env.three.local --catalog-scope complete --format csv > three-prices.csv
# 10 列完整目录：另保留起价和需销售报价的记录，无报价金额为空。
gpu-price-monitor collect --env-file .env.three.local --catalog-scope complete --format csv --csv-profile catalog > three-catalog.csv
# 全部原始记录审计；无数值询价、起价和其他不合格记录不抹掉。
gpu-price-monitor collect --env-file .env.three.local --catalog-scope complete --format csv --csv-profile full > three-prices.audit.csv
```

Python 对应：

```python
from gpu_price_monitor import Settings, collect_prices, prices_to_csv

result = collect_prices(
    ["nebius", "lambda", "crusoe"],
    settings=Settings(source_policy="api_preferred", catalog_scope="complete"),
)
csv_text = prices_to_csv(result)
# 完整模式同时返回 catalog_audit，分开统计原始来源和派生配置。
print(result["catalog_audit"]["totals"])
```

模板设置 `GPU_PRICE_MONITOR_PROVIDERS=nebius,lambda,crusoe`、`GPU_PRICE_MONITOR_SOURCE_POLICY=api_preferred`、`GPU_PRICE_MONITOR_CATALOG_SCOPE=complete`。账号字段均为空，不会假装鉴权成功；`.env` 必须显式加载。`standard` 保持普通范围，`complete` 增加目录配置 / 预留条件清点。`api_only` 仍不能将页面、文档或网站 JSON 改称正式价格 API，完整公开目录建议用 `api_preferred`。

## 各平台实际返回什么

| 平台 | 公开来源与范围 | 必须保留的边界 |
| --- | --- | --- |
| Nebius | 官方资源费率、平台 / preset / 地区文档、当前地区 Spot API、网站 JSON 询价项 | 明确区分原始费率、按配置推导的成本、实际 Spot 地区费率及账号估价 |
| Lambda | 本轮官网为 22 条按需配置，另有 8 条预留集群记录：6 条数值、2 条联系销售 | 预留承诺、集群卡数、每 GPU 小时价和按周结算都保留，不当普通单机按需价 |
| Crusoe | 本轮官网为 12 个 GPU 目录项、按需 / Spot 共 24 格：8 条数值、16 条 Contact sales | 没有公开数值的 Spot 不填价；公开目录没有独立地区价格，已有合同另作账号审计 |

以上数量是本轮公开结构核查结果，页面会变化；实际覆盖以本次 `provider_results`、目录覆盖 / 缺口及原始记录为准。已发现配置、成功请求、原始来源条目、派生配置行、有效小时价和已核实地区价不是同一个数字。

## Nebius：费率计算不等于独立报价

官方来源：[计算资源费率](https://docs.nebius.com/compute/resources/pricing)、[GPU 平台与 preset](https://docs.nebius.com/compute/virtual-machines/types)、[地区目录](https://docs.nebius.com/overview/regions)、[当前 Spot 获取方式](https://docs.nebius.com/signup-billing/spot-prices)、[官网价格目录](https://nebius.com/prices)。

公开完整模式把来源中的 GPU / vCPU / RAM 小时费率与明确 preset 数量关联：

```text
配置计算资源小时费 = Σ（官方资源小时费率 × preset 资源数量）
每 GPU 小时费 = 配置计算资源小时费 ÷ 明确 GPU 数
```

这些记录带有 `rate_derivation`、来源分项和公式，`independent_provider_quote=false`。L40S 的 GPU 单项价格不能直接冒充含 CPU / RAM 的完整计算资源价格；磁盘、网络等附加服务也不能默认为已包含。USD / ILS 是来源币种与客户计费辖区，不据此猜部署国家。

平台 / preset 的供给地区另存为 coverage。**不能把同一目录费率按覆盖地区复制后称为各地区独立报价。** Spot API 则返回真实的平台 + region + 当前每 GPU 小时费率，并保留源快照和生效时间。将同一条 Spot 费率应用到 1 卡 / 多卡 preset 时，也要标记成本推导：该地区源报价只有一条，不因配置展开变成多次独立取价。没有匹配 preset 的实际 Spot 报价保留其原始范围，不猜配置。

From 最低抢占价不当当前 Spot；官网 Contact us 仍无数值。网站 JSON 是公开网站的数据接口，不是正式稳定云价目 API。

账号估价需要有效 IAM token、调用者有权使用的项目及完整资源目标；显式 `NEBIUS_SOURCE=api`，设置 `NEBIUS_ACCESS_TOKEN` 及 `NEBIUS_PRICE_TARGETS_FILE` / `NEBIUS_PRICE_TARGETS_JSON` 之一。项目 / 地区 / 国家 / 平台 / preset 与磁盘条件须核对，模板不证明配置可售。[Estimate Batch](https://docs.nebius.com/rest-api/billing/v1/calculator/estimate-batch)只估价，不创建 VM；不同项目、账号合同及地区并不会仅靠登录自动枚举齐全。

## Lambda：按需、集群预留与账号目录分开

官方来源：[按需实例](https://lambda.ai/instances)、[1-Click Clusters](https://lambda.ai/1-click-clusters)、[API 规范](https://docs.lambda.ai/api/cloud/spec.json)、[计费说明](https://docs.lambda.ai/public-cloud/billing/)。

按需公开表的金额是每 GPU 小时价，1 / 2 / 4 / 8 卡配置分开。预留集群是另一个产品线，保留承诺时长和集群卡数；`256+` 是下限，不能当精确实例卡数。虽然价格单位是 GPU-hour，预留按周结算，不能改成可随时退租的普通按需价。联系销售的两项没有可制造的价格，整个集群与单节点总价也不能在缺少明确依据时补算。

可选 `LAMBDA_API_KEY` 与显式 `LAMBDA_SOURCE=api` 调用认证 instance-types。API `price_cents_per_hour / 100` 是整实例美元小时价，再按明确 GPU 数分摊。`regions_with_capacity_available` 只表明容量，不是地区价；账号 API 也不等于所有长期协议 / 销售折扣均可读取。

0.15.0 另提供免费 `LAMBDA_SOURCE=console`：只 GET 控制台内部实例、预留集群和地区目录，使用调用者自行保存的会话。**2026-10-22 用户手动登录保存会话后，独立 Python CLI / HTTP 三个 GET 均实采成功，返回 36 条 GPU 报价：22 个按需实例规格和 14 个预留集群配置（6 个型号/费率档）**；另审计排除 2 个 CPU 规格，保留 18 条地区元数据。采集时不启动浏览器，不需要 API key、绑定付款方式或创建 GPU。内部接口可能变化；地区仅表明容量，不是逐地区价格。集群期限与最终购买条件仍未核实，不能宣称所有合同价已获取。[登录态配置、字段冲突和覆盖边界](lambda-console.md)。

## Crusoe：全部公开目录与账号合同审计

官方来源：[GPU instances 价格表](https://www.crusoe.ai/cloud/pricing)、[OpenAPI](https://api.crusoecloud.com/v1/openapi.json)、[VM 规格及供给可用区](https://docs.crusoecloud.com/compute/virtual-machines/overview/)、[Spot 政策](https://docs.crusoecloud.com/usage-billing/spot/)、[预留合同](https://docs.crusoecloud.com/usage-billing/reservations/overview/)。

12 个公开目录项包括有数值价的型号，以及 GB200、MI355X、GB300、Vera Rubin 等无数值项。当前公开表没有数值 Spot，16 个 Contact sales 格保留 null；不把账单、Foundry 模型部署或旧宣传价代替 GPU VM 报价。规格页的实例 SKU / zone 是供给覆盖，不能为公开费率补造地区绑定。

可选 `CRUSOE_SOURCE=account` 只读已有 reservations；`combined` 同时保留公开目录与已有合同审计。要求 `CRUSOE_ACCESS_KEY_ID`、`CRUSOE_SECRET_KEY`、`CRUSOE_ORGANIZATION_ID`。认证按[官方 HMAC-SHA256 1.0 签名](https://docs.crusoecloud.com/reference/api/)执行，secret 是供应商生成的 URL-safe Base64，不是普通 Bearer token；只 GET 已有合同，不创建或修改资源。

当前 Reservation API 的 `price` 和通用 `product_line` 缺少结构化币种、小时单位和 GPU 产品分类证据，故返回 `contract_records` 审计，**不能把它直接作为 USD / GPU / 小时报价或填进小时 CSV**。合同数量是承诺容量，不能当一台 VM 的卡数；合同位置约束也不是独立公共地区价。组织、项目、VM 等私有标识不回显，原合同标识只保留哈希引用。

官方说明 Spot 需联系销售 / 支持，预留折扣需已有签约协议。只登录控制台不能保证获取所有地区、Spot 和其他客户合同价格；本库不会发销售邮件、提交询价表或购买资源。

## 账号入口与未验证事项

| 平台 | 登录入口 | 仍需调用者提供 |
| --- | --- | --- |
| Nebius | [控制台](https://console.nebius.com/) | 有效 IAM token、有权使用的真实项目、完整估价目标 |
| Lambda | [控制台](https://cloud.lambda.ai/) | console 模式使用自己的有效保存会话，已通过独立 HTTP 实测；API key 模式仍需有效 key 验证，二者均不保证包含所有合同条件 |
| Crusoe | [控制台](https://console.crusoecloud.com/) | API access key ID、secret、组织 UUID 及对已有合同的权限 |

公开来源已实际采集；Lambda 控制台会话路径也已在 2026-10-22 完成独立 Python HTTP 真实成功验证。Nebius 账号估价、Lambda API key 模式和 Crusoe 合同认证仍缺有效凭据的成功联调证据；原文档另两家的 UCloud 签名估价、AutoDL 登录市场也仍未完成该验证。缺密钥、会话过期、鉴权失败或源格式变化会明确报错，不以公开目录、旧快照或零价冒充账号成功。

库只返回原币 JSON / CSV 文本，不做 FX、上传或定时。默认 `market` 表、保留询价项的 `catalog` 表、严格地区 `compact` 表和全部来源 `full` 审计用途不同；目录计算、承诺预留与独立地区询价必须带着条件一起阅读。需要完整状态、公式、销售缺口和 `contract_records` 时应保留 JSON，不能只看有效报价 CSV 的行数。
