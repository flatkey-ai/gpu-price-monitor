# GPU 价格采集库实施与验收

更新：2026-10-21，版本 0.13.0。当前重点为原文档五家 **Nebius、Lambda、Crusoe、AutoDL、UCloud**；RunPod、DigitalOcean、Verda、Azure 保留独立扩展能力，五家模板不包含它们。

## 交付范围

库负责只读采集、有限重试、固定规则解析、单位 / 配置核对、筛选以及 Python / CLI JSON / CSV 返回。调度、存储、历史、换汇、上传、比价、告警与 RackRate 网站发布由调用方负责。不创建 / 启动 / 购买 GPU，不依赖 Codex、LLM 或模型 API Key。

只采 GPU VM / 容器租用价，不以 Token 模型 API、托管模型部署、微调、已有资源账单或硬件售价替代。起价、GPU 单独组件、会员条件、账号合同、月套餐和下线状态分别保留；未知金额不填零。

## 五家实施路径

| 平台 | 推荐 `api_preferred` | 仍需验证的边界 |
| --- | --- | --- |
| Nebius | 匿名当前地区 Spot API + 官网动态 Next.js JSON 普通目录 | 网站数据不是正式稳定云 API；目录无地区、卡数、显存或真实 SKU。账号 Estimate Batch 需有效 token |
| Lambda | 有 key 用 instance-types，无 key 固定官网解析；完整实例美分按卡数分摊 | 容量不是价格地区；认证目录仍缺有效 key 成功联调 |
| Crusoe | 固定 HTML 规则只读 GPU instances；按需数值与询价分开 | 没有核实公共 VM 价目 API，网页不是接口；无地区位置证据 |
| AutoDL | 固定 Playwright DOM 普通 / 会员首页，授权市场另选 | Pro / 部署 API 不是市场价目；登录市场需有效会话成功验证 |
| UCloud | 无 key 调 CompShare 匿名完整配置小时询价；有任一 key 要求完整签名 UHost 路径 | 产品线必须标记，普通原价与优惠审计分开；未知 ZoneId 不代配地区；签名 UHost 仍需有效账号联调 |

CompShare 的前端目录仅发现原始配置，不取其中金额；实际响应 `OriginalPriceDetails` 分项合计 / GPU 数为普通每卡小时价，`PriceDetails` 资格未核实仅审计。源地区为官方精确映射及当前国家 / region / zone 目录核验的请求上下文，不保证响应独立回显位置或实时库存。

`configured` 默认兼容原 `*_SOURCE`；旧 Nebius 文档与 UCloud UHost 月促销保留，但不能代替新小时价。`api_only` 只允许价格 API：Nebius 仅 Spot，不加网站目录；Crusoe / AutoDL 报不支持。已选 API 的任何失败不改抓网页、其他产品线或旧快照。

## 输出契约

推荐 `collect_prices(["nebius", "lambda", "crusoe", "autodl", "ucloud"], settings=Settings(source_policy="api_preferred"))`，或复制 `.env.five.example` 后用 CLI `--env-file .env.five.local`。全部由普通 Python 程序执行。

0.13 默认 `market` 十列小时目录 / 地区价，保留官网没有标明适用地区的真实有效目录，不把“缺地区”误当“没价格”；其范围必须写明，不表示全球统一。`compact` 保持严格国家 + region 小时表，`full` 保留原 51 列全部审计。起价、组件、月包、询价、资格未核实特殊优惠及明确不可用项不进有效小时报价表。

`market_comparison` 和每来源 `market_quote_count` 说明当前有效小时覆盖；原 `comparison` 继续是严格地区统计。`execution` 说明 Python / 固定规则 / 不用 LLM；来源方法与选择理由随 `provider_results` 返回。来源成功、数值有效、位置核实与立即可购分别验收。

CSV 保留原币、精确金额、实例配置、普通 / 会员 / Spot / 税费 / 账号 / 产品线条件、来源与时间，默认双语表头、UTF-8 BOM / CRLF。库不换 USD，不除以 720 换月价，不写文件或上传。stderr 是诊断；退出码成功 0、部分 2、失败 1，空投影仍应看 JSON 来源状态。

## 地区处理

先保留来源证据再筛选，不给每个平台预列国家并复制价格。Nebius Spot 才有实际价格 region，网站目录无位置；文档覆盖单列。Lambda 容量单列；Crusoe / AutoDL 首页无位置；授权市场不猜国家。CompShare 仅使用原配置已核实 ZoneId，UHost 账号询价核验完整目标；产品线地区不能互套。

国家 / region / zone 必须在同一条报价匹配。不支持报 `unsupported_filter`，支持但缺证据报 `unverifiable_filter`。币种、总部、访问 IP、机房覆盖不补价格位置；位置缺失不证明全球统一。

## 验收要求

- 单元测试覆盖金额 / 单位 / 格式变化拒绝、接口失败不回退、地区不猜、GPU 数分摊、普通 / 会员 / 优惠身份分开、market / compact / full 投影及兼容字段。
- 实采必须留来源 URL、实际方法、观察时间、具体配置与逐来源状态。发现目录不等于询价成功，合成样本不等于账号已认证。
- 比较表行数由资格计算，不能用原始月包、Contact sales、From 或复制国家来凑条数。部分失败保留诊断，不给失败金额填零。
- 原文档五家各自验收；不能靠新增其他平台补齐这五家的缺项。未验证的账号路径、地区与资格要直接说明。

```bash
python -m unittest discover -s tests -v
gpu-price-monitor validate-config --config configs/collect.all.example.json
```

历史五家 / 九家样本及旧严格地区表见 [examples](../examples/README.md)，仅属于当时观察，不作现价或运行时兜底。当前请求、单位与边界见 [PROVIDERS.md](PROVIDERS.md)，逐条原文对照见 [DOCUMENT_COVERAGE.md](DOCUMENT_COVERAGE.md)。
