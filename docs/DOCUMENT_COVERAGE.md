# 原始 Word 需求与实现对照

对照版本：0.18.0，日期：2026-10-22。原始《GPU云算力_价格入口与API核查_2026-10-10.docx》核查 **Nebius、Lambda、Crusoe、AutoDL、UCloud** 五家；本文以前五家为验收重点。文档中的接口示例、失败响应与接入建议是核查材料，不是直接复制的真实报价。

用户后续明确：免费公开采集、开源可 clone、独立 Python / CLI、接口优先、金额真实可追溯，不依赖 Codex / LLM 解析；允许没有合适市场价接口的 Crusoe / AutoDL 用代码解析官网。库只采集 / 返回，存储、换汇、上传、定时与网站更新由调用方负责。

## 五家按原文对照

| 平台 / 原文事项 | 当前实现 | 真实验证与限制 |
| --- | --- | --- |
| Nebius：Estimate Batch 需要完整资源及 Bearer token | 匿名 Spot；公开网站 JSON 目录；显式 `catalog_api` 自动发现已有项目与 GPU presets 后逐项只读估价 | 2026-10-22 账号实采 37 配置、36 条正数计算价、9 地区 / 6 国家；GB300 零计算费列缺口，SSD 另计。不是库存或全部账号合同 |
| Lambda：instance-types 含美分整机价、卡数及容量位置 | 密钥 API、公开页，或显式 `console` 用本地会话读取官方 JSON | 免费登录态已由 Python / CLI 实采；当前前端证明同 SKU 所列可选标准地区共用目录价。密钥 API 仍未成功联调；容量本身不证明价格地区 |
| Crusoe：VM types 无价；账单 / 托管模型不同于 GPU VM 租价 | 固定规则只解析官网 GPU instances 区块，数值、起价与 Contact sales 分开 | 官网已实采；登录账号可读 35 个规格但无价格字段，当前无配额且配置入口要求付款资料。未找到可验证的完整地区价 API；不补造全球统一价 |
| AutoDL：已有 Pro 实例 / 部署价格不是全市场目录 | 固定 DOM 采首页普通 / 会员价；可选用户授权登录市场，核验分页 / 单位 / 位置 | 首页已真实采集；授权市场有测试但缺有效会话成功联调；不拿已有资源 API 冒充市场 |
| UCloud：指定完整地区 / GPU / CPU / RAM / 磁盘配置后询价 | 接口优先无 key 走旗下 CompShare 匿名小时配置询价，普通原价分摊；有任一 key 要求完整签名 UHost 询价 | CompShare 已有真实匿名 API 成功响应；两条产品线分开。原文 UHost 签名路径仍缺有效账号成功联调，不将原报告 RetCode 错误当报价 |

本批逐平台成功状态与有效小时条数见实际 JSON `provider_results`，不把发现配置数、原始记录数、目录 / 地区有效价和可立即购买混成一个数字。

## 推荐五家运行方式

```bash
cp .env.five.example .env.five.local
gpu-price-monitor collect --env-file .env.five.local --pretty > prices.json
gpu-price-monitor collect --env-file .env.five.local --format csv > prices.csv
```

Python：

```python
from gpu_price_monitor import Settings, collect_prices, prices_to_csv

result = collect_prices(
    ["nebius", "lambda", "crusoe", "autodl", "ucloud"],
    settings=Settings(source_policy="api_preferred"),
)
csv_text = prices_to_csv(result)
```

运行环境为 Python 3.11+，AutoDL 需 browser extra / 本地 Chromium。没有模型调用、模型 API Key 或 Codex 运行时。`.env` 只显式加载，已有 `.env` 可保留，独立五家 profile 为 `api_preferred`。

## 三种来源策略

- `api_preferred`：接口优先，允许明确标记的官网固定规则与网站 JSON。Nebius 合并 Spot + 网站普通目录；Lambda 依 key 选择；UCloud 无 key 为 CompShare、有任一 key 要求完整 UHost 账号配置；Crusoe / AutoDL 页面规则由程序运行。
- `api_only`：仅允许价格 API，Nebius 保持 Spot only；Crusoe / AutoDL 直接报 `api_price_source_unavailable`。缺 key、不完整 targets、鉴权或格式错误不触发其他来源。
- `configured`：兼容原 `*_SOURCE`；Nebius public 保留旧文档 + Spot，UCloud public 保留旧 UHost 促销月包。不能拿兼容月包当新的小时询价结果。

JSON `execution` 明确 Python / 固定规则 / 不使用 LLM / 策略；逐来源返回实际 `source_type`、`collection_method`、选择原因和适用的 fallback 原因。页面或网站 JSON 不包装成正式 API，选中接口失败不换抓网页或旧样本。

## 小时表与地区表分开验收

0.13 默认 `market` 十列，纳入实际数值的 GPU 小时目录价及地区价。缺少地区的有效官方目录有明确适用范围，不再被隐藏；这**不代表全球统一价**，也不生成多个国家的重复价格。

`compact` 十列继续要求实际价格国家与 region 均已核实；`full` 原 51 列保留所有原始来源审计。From、GPU 组件、Contact sales、月包、资格未核实的特殊优惠及明确下线 / 不可用项不进有效小时表。普通 / 会员、Spot、账号资格、税费、产品线、实例分摊和原始单位仍保留。

`market_comparison` 与每来源 `market_quote_count` 表示有效小时报价，原 `comparison` 仍是严格地区统计。保留旧字段是兼容行为，不能拿旧地区计数当当前默认报价表的覆盖条数。库不换汇、不按 720 小时换算月价。

## 国家与地区证据

| 来源 | 能证明什么 | 不能证明什么 |
| --- | --- | --- |
| Nebius 当前 Spot | 接口实际 region、平台、币种和生效时间；国家按官方目录映射 | 不证明普通按需或可立即购得 |
| Nebius 普通 JSON 目录 | 官方 GPU-hour 普通费率及列出的 CPU / RAM | 不证明价格地区、GPU 数量、显存或特定云 SKU |
| Lambda API / 页面 | 实例规格 / 每卡费率；API 的容量位置单列 | 不证明独立逐地区费率 |
| Crusoe / AutoDL 首页 | 公开目录每卡小时价；AutoDL 普通 / 会员资格分开 | 不证明目录适用的全部国家或全球统一价 |
| AutoDL 授权市场 | 来源原始挂牌 region / 地区名 | 未核实国家 / zone，不根据大陆平台名称猜国家 |
| UCloud CompShare | 原 ZoneId 精确映射、实时官方国家 / region / zone 目录核验的请求位置、完整配置询价 | 响应未独立回显位置；不证明库存 / 所有区域 SKU；未知 ZoneId 不借用已知区域 |
| UCloud UHost 账号询价 | 完整目标及官方位置目录核验后的请求上下文 | 缺有效账号成功响应不能说真实联调完成 |

筛选必须在同一条报价满足国家 / region / zone。缺失位置不填 global；容量、覆盖、币种、总部和 IP 不补价格地区。缺证据的支持维度报 `unverifiable_filter`，来源不支持报 `unsupported_filter`。

## UCloud 产品线和原价验收

CompShare（优云智算）是 UCloud 旗下产品线，输出必须明确标记。目录前端只发现 GPU / CPU / 内存 / 磁盘 / ZoneId 请求配置，嵌入金额丢弃；价格来自每次匿名 `POST https://api.compshare.cn/` 的 `GetCompShareInstancePrice` 响应。

普通比较价为 `OriginalPriceDetails` 中实际返回小时分项之和，再按明确 GPU 数分摊；`PriceDetails` 的优惠资格未核实，仅保存审计，不标为通用会员价。请求明确 `ChargeType=Postpay` 与一台完整主机；计费单位核对官方说明，不从旧月套餐换算。地区只按官方精确映射，不替换原目录未知 ZoneId。来源、单位及证据链接见 [PROVIDERS.md](PROVIDERS.md)。

## 仍需凭据的边界

Nebius 账号 Estimate Batch、Lambda 认证目录、签名 UCloud UHost 询价及 AutoDL 登录市场仍需要调用者有效权限。现有离线测试证明配置 / 解析 / 失败行为，不等于这些账号接口真实成功。公开 CompShare 成功也不能证明签名 UHost 成功；不同平台接口是否收费激活由供应商决定，库不代办购买。

## 历史样本与扩展

[examples](../examples/README.md)保留旧五家 / 九家 JSON 与严格地区 CSV，均是当时的宽表或地区证据，不代表当前默认 market 范围，不进入运行时回退。旧截图的 Nebius 历史 Spot 数字不写成现价。

RunPod、DigitalOcean、Verda、Azure 是后来新增的独立适配器；`all` 包含它们，但不是原 Word 已核查的五家事项。五家 profile 只运行本页范围，其余来源和限制见 [PROVIDERS.md](PROVIDERS.md)。
