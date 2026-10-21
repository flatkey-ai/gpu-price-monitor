# GPU Price Monitor

根据九家 GPU 云平台的官方价格入口构建的采集库：**Nebius、Lambda、Crusoe、AutoDL、UCloud、RunPod、DigitalOcean、Verda、Azure**。提供 Python 调用和 CLI JSON / CSV，只负责抓取、解析、筛选及返回报价。定时、存储、换汇、上传和比价由调用方处理。

[English](README.en.md) · [文档需求与实现对照](docs/DOCUMENT_COVERAGE.md) · [数据口径](docs/DATA_MODEL.md) · [环境配置](.env.example)

当前版本 **0.12.0** 增加接口优先的来源策略。原文档五家建议使用 `--providers nebius,lambda,crusoe,autodl,ucloud --source-policy api_preferred`：有合适接口时调用接口，缺少接口或密钥时按明确规则选择公开页面，并返回实际来源。所有采集由 Python 程序执行，不需要 Codex、LLM、模型 API Key 或人工读取页面。Crusoe、AutoDL 的公开价格目前仍用固定页面规则，不能称为五家纯 API 采集。

默认仍输出严格的 **10 列地区每 GPU 小时比较 CSV**，仅保留实际数值、国家和 region 均已核实的小时报价；`--csv-profile full` 保留原 51 列来源审计表。表头默认英中双语，可选纯英文。`--providers all` 运行九家；旧日期示例是当时的来源记录，不代表当前全市场覆盖。本版本从源码安装，未发布至 PyPI，可用 `gpu-price-monitor --version` 确认版本。

## 先看地区能力

公开价格页并不一定提供不同国家的独立价格。库不根据公司总部、币种、访问 IP、机房库存或平台覆盖地点推测价格地区，也不会将同一目录价复制到多个国家。来源缺少地区字段不证明全球统一价；当前没有依据据此宣称这些目录价格全球相同。

| 平台 | 接口优先策略下的来源 | 地区报价能力 |
| --- | --- | --- |
| Nebius | 公开模式仅调用无需认证的当前 Spot API；显式 `api` 仍是账号完整配置估价 | Spot API 实际绑定平台、地区、币种及生效时间，国家按官方地区目录关联；无需抓计算价目文档 |
| Lambda | 配置 `LAMBDA_API_KEY` 时调用实例 API；无密钥时解析官方实例页 | 公开表不绑定具体地区。API 的容量地区单独保留，不当成逐地区价；1 / 2 / 4 / 8 卡配置分开 |
| Crusoe | 固定规则解析官网 GPU instances 区块；未找到可核实的公共 VM 价目 API | 当前公开表未给逐地区价格；保留未知地区及 Contact sales，不混入账单或托管推理报价 |
| AutoDL | Playwright 固定 DOM 规则读取官网普通用户 / 炼丹会员价；显式 `market` 保留授权市场模式 | 公开首页不绑定地区。市场挂牌保留来源地区；已有资源的 Pro API 不当成市场价格 API |
| UCloud | 有任一账号密钥配置时走完整配置询价 API；无密钥时走匿名活动 API | 完整询价要求两把密钥和 targets；匿名来源为地区月包，不能伪造为小时价 |
| RunPod | 官方匿名 GraphQL GPU Pods 目录 | Secure / Community 云档位分开；目录未绑定价格地区，不把机房覆盖当地区价 |
| DigitalOcean | 官方 GPU Droplet 定价文档 | 按需 / Spot 分开，整实例按明确 1 / 8 卡数分摊；文档未给价格地区 |
| Verda | 官方 USD / EUR GPU instances 表 | 每种币种分别抓取，按需 / Spot 和完整实例总价保留；不推断芬兰等部署国家 |
| Azure | 官方匿名 Retail Prices API | 当前只采四个已核验 SKU（T4、GB200、H100 NVL、A100 PCIe）的已生效地区零售价及官方目录已核验国家映射；不表示全 SKU、国家或库存覆盖 |

**0.12.0 五家实跑于 2026-10-21 17:18:56（北京时间）完成，全部来源成功，共 456 条记录**：Nebius 12、Lambda 22、Crusoe 24、AutoDL 24、UCloud 374。详见[实际来源报告](examples/five-api-preferred-sources-2026-10-21.json)。这次无账号密钥，Lambda 使用公开页，UCloud 使用匿名月包 API；严格地区小时 CSV 仅 12 条 Nebius。没有将月套餐或缺少价格地区的记录算作五家地区小时报价。

**0.11.0 于 2026-10-21T08:45:38.349457Z 实采：845 条来源记录，224 条严格地区小时比较价（Nebius 当前 Spot 12、Azure 212）**，见 [224 行原币 10 列 CSV](examples/regional-hourly-2026-10-21.csv)。其他七家该批免费来源缺少完整价格国家 / region，或仅有下线月包，因此没有合格比较项；这不表示其没有可购产品，也不证明 0.12.0 的认证分支已成功联调。

旧版 **2026-10-21 15:12:56（北京时间）的 833 条来源记录**保存在 [九家历史 JSON](examples/nine-providers-2026-10-21.json)，其中包含未知价格地区、平台覆盖、询价和 374 条已下线 UCloud 月包。它们是历史宽表审计证据，不能作为当前小时比较结果；[五家历史样本](examples/five-providers-2026-10-21.json) 同样保留当时范围。当前可比较条数看返回的 `comparison.eligible_quote_count` 和 CLI 的 CSV 汇总。

Nebius 截图中 **2026-10-21 08:00 UTC** 的 B200 `me-west1` **4.10** 与 `us-central1` **1.90 USD/GPU/hour** 是历史 Spot 图表的最后价，反映当时的地区差价，不是普通按需价或固定现价。Spot 会动态改变；当前采集读取 [官方 Spot API](https://docs.nebius.com/signup-billing/spot-prices)，不硬编码截图数字或用历史点代替现价。

认证询价和登录市场仅发送只读请求，不创建、启动或购买资源。账号是否允许取价由供应商决定；新增认证分支有合成样本测试，尚未完成有效账号的成功联调，不把文档示例当实抓。

## Clone 后运行

要求 Python 3.11+、Git 和能访问各平台官网的网络。公开模式不用密钥或 `.env`，AutoDL 需要本地免费 Chromium。

```bash
git clone https://github.com/flatkey-ai/gpu-price-monitor.git
cd gpu-price-monitor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install '.[browser]'
python -m playwright install chromium
python -m gpu_price_monitor collect --providers nebius,lambda,crusoe,autodl,ucloud --source-policy api_preferred --pretty
```

Windows PowerShell 使用 `py -3 -m venv .venv` 与 `.\.venv\Scripts\Activate.ps1`。Linux 若缺少浏览器系统库，使用 `python -m playwright install --with-deps chromium`。仅 HTTP 采集可安装基础包 `python -m pip install .` 并指定 `--providers nebius,lambda,crusoe,ucloud,runpod,digitalocean,verda,azure`。

CLI 的 stdout 默认只包含 JSON，`collect --format csv` 时只包含 CSV；诊断写入 stderr。退出码 `0` 表示全部成功（含筛选无匹配），`2` 为部分失败，`1` 为失败或配置无效。失败不会返回零元或上次价格。

```python
from gpu_price_monitor import Settings, collect_prices

result = collect_prices(
    ["nebius", "lambda", "crusoe", "autodl", "ucloud"],
    settings=Settings(source_policy="api_preferred"),
    include_coverage=True,
)
for quote in result["prices"]:
    print(quote["provider"], quote["gpu_model"], quote["amount"],
          quote["currency"], quote["unit"], quote["price_scope"],
          quote["compute_countries"], quote["regions"], quote["zones"])
```

## 来源策略与可追溯执行

| 策略 | 行为 |
| --- | --- |
| `configured` | 默认兼容行为，按各 `*_SOURCE` 配置采集；没有密钥也不会自动启用账号 API |
| `api_preferred` | 推荐五家采集方式：Nebius 公开模式只走 Spot API；Lambda 有 key 用 API，否则公开页；UCloud 配有任一 key 就要求完整账号询价配置，否则匿名活动 API；Crusoe、AutoDL 使用已标明的页面规则 |
| `api_only` | 只允许价格 API；Crusoe、AutoDL 等页面来源返回 `api_price_source_unavailable`，不悄悄抓页；Lambda 缺 key 或账号配置不完整会报错 |

Python 使用 `Settings(source_policy="api_preferred")`；CLI 使用 `--source-policy api_preferred`；环境配置为 `GPU_PRICE_MONITOR_SOURCE_POLICY=api_preferred`，通过 `Settings.from_env()` 或显式 `--env-file` 加载。显式选择账号 API 后，鉴权失败、请求错误或响应格式变化均直接返回失败，不降级成网页目录或历史样本。

JSON 的 `execution` 声明 `runtime=python`、`parsing=deterministic_rules`、`uses_llm=false` 和所选 `source_policy`。每个 `provider_results` 条目保留实际 `source_type`、`collection_method`、`selection_reason` 和适用时的 `fallback_reason`；方法分别为 `http_json`、`http_html`、`http_document`、`browser_dom`，兼容模式 Nebius 的文档与 API 混合来源为 `hybrid_http`。这些信息可核对“到底调用接口还是解析页面”，不会因开启接口优先就把页面标成 API。

五个平台都可尝试采集原始来源，**不表示五家都有国家和地区完整的每小时比较价**。Lambda 容量地区不代表地区报价，UCloud 匿名月包不转换成小时价，Crusoe / AutoDL 缺少价格位置的首页记录仍不进入默认 CSV。

## 导出 CSV 表格

**0.11.0 起默认 `compact` 比较表为 10 列**：GPU 型号及配置、平台、价格国家与地区、原币每 GPU 金额、币种、计费单位、价格与资格条件、可用状态、官方来源、采集时间。普通 / 会员、云档位、Spot、税费和账号适用条件仍保留；来源明确的整实例总价放在条件中，不补造总价。

默认表仅接受 `quoted` 数值报价、`unit=gpu_hour`、已核实的地区价格范围、非空国家与 region；地区不完整、仅平台覆盖、起步价、GPU 组件价、月包、Contact sales 和明确下线 / 不可用项均不进入比较表。Spot 保留动态价格的生效时间。`prices_to_csv(result, profile="full")` 或 `--csv-profile full` 返回原 51 列全量审计表，方便核对被排除的来源记录。JSON 默认仍返回原始筛选结果及来源状态；库只返回文本，不自行写文件、上传或换汇。

```bash
# 默认仍返回完整 JSON，可查看逐平台状态和覆盖汇总。
gpu-price-monitor collect --providers all --coverage --pretty > prices.json

# 默认严格 10 列比较表；stderr 显示保留和排除条数。
gpu-price-monitor collect --providers all --format csv > prices.csv
# 程序读取：保留纯英文固定字段名。
gpu-price-monitor collect --providers all --format csv --csv-headers english > prices.english.csv
# 全量 51 列来源审计表，保留未知地区、月价和下线项。
gpu-price-monitor collect --providers all --format csv --csv-profile full > prices.audit.csv
```

```python
from pathlib import Path
from gpu_price_monitor import Settings, collect_prices, prices_to_csv

result = collect_prices("all", settings=Settings())
csv_text = prices_to_csv(result)  # 默认严格 10 列、英中双语表头
english_csv_text = prices_to_csv(result, bilingual_headers=False)
audit_csv_text = prices_to_csv(result, profile="full")  # 原 51 列，全量来源记录
# 返回文本已含 BOM 与 CRLF；使用 utf-8、禁用换行改写，避免重复 BOM。
Path("prices.csv").write_text(csv_text, encoding="utf-8", newline="")
```

`--csv-profile compact` 可显式选择默认 10 列；`--csv-profile full` 选择兼容的 51 列。`COMPACT_CSV_COLUMNS` / `COMPACT_CSV_HEADERS` 定义比较表字段与双语表头，`CSV_COLUMNS` / `CSV_HEADERS` 继续定义完整审计表。`--csv-headers english` 或 `bilingual_headers=False` 使用英文 ID，只改变表头。依赖旧 51 列的脚本应显式选择 `full`；`publishable_quote(quote)` 可检查单条记录是否符合默认比较条件。

金额保留来源精确十进制字符串，CNY / EUR / ILS 不转换为美元；月价保留在 JSON / full 审计表中，不除以 720 或其他假定小时数。未知地区不补成 global，平台覆盖不生成国家价格。RackRate 应用另行负责 USD 展示、存储和网站更新。

文件编码为 **UTF-8 BOM**，行结束符为 **CRLF**；采集和生效时间保留原 ISO 时间，不按主机时区改写。CSV 不附加 `provider_results`、`geographic_coverage` 或型号 `coverage` 表。默认比较表在 stderr 提示保留及排除条数；来源全部成功但无合格地区小时价时，仅返回表头，退出码仍为 `0`。部分来源失败退出 `2`，全部失败 / 配置错误退出 `1`；完整来源状态与排除记录查看 JSON 或 full 审计表。

## 按国家和地区取价

同一报价的国家、地区、可用区必须同时匹配，不把它们分别匹配到不同记录。国家筛选用 ISO 两字母代码，可重复传入。尚未公开或支持的维度返回 `unsupported_filter`；本应支持但相关报价缺少位置证据返回 `unverifiable_filter`，不静默当成无匹配。

```bash
# 真实公开地区月包：保留下线状态，不能当现货或小时价。
gpu-price-monitor collect --providers ucloud --country CN --region cn-bj2 --zone cn-bj2-02 --pretty

# Azure 的价格响应绑定 ARM region；国家由官方目录已核验映射关联。
gpu-price-monitor collect --providers azure --gpu T4 --country US --region eastus --pretty

# Nebius 当前地区 Spot 价；country / region 只匹配实际价格位置。
gpu-price-monitor collect --providers nebius --gpu B200 --billing-mode spot --country US --region us-central1 --pretty

# 文档供给覆盖单独查询，不能当作这些国家已有独立报价。
gpu-price-monitor collect --providers nebius --coverage-region eu-north1 --coverage-country FI --pretty

# 有效账号和配置填好后，再对项目所在国家/地区进行完整配置询价。
gpu-price-monitor collect --env-file .env --providers nebius --nebius-source api --country FI --region eu-north1 --pretty
gpu-price-monitor collect --env-file .env --providers ucloud --ucloud-source api --country CN --region cn-bj2 --pretty

# 已有授权登录态的 AutoDL 市场；地区代码以市场原始返回值为准。
gpu-price-monitor collect --env-file .env --providers autodl --autodl-source market --pretty
```

Python 价格位置筛选字段为 `compute_countries`、`regions`、`zones`，平台供给覆盖另用 `coverage_countries`、`coverage_regions`；其余字段为 `gpu_models`、`gpu_counts`、`currencies`、`billing_modes`，值均为数组。例如 `collect_prices(["nebius"], {"compute_countries": ["US"], "regions": ["us-central1"], "billing_modes": ["spot"]}, settings=Settings())`。价格位置与覆盖条件匹配各自证据，通常分次查询，不跨记录拼出国家地区价格。销售国家与部署国家不同，当前 `sales_countries` 不支持。

`geographic_coverage` 汇总本批价格位置与独立的 `coverage_region_codes` / `coverage_country_codes`；`coverage_regions` / `coverage_countries` 不进入价格 `regions` / `compute_countries`。`price_scope` 区分未知目录、平台覆盖、地区 / 可用区报价及请求配置询价，不表示库存或购买资格。相关地区若没有已核验国家映射，国家筛选可返回 `unverifiable_filter`；可以结合已核验 region 限定集合，不能把未知国家静默当作不匹配。

## 可选账号配置

原文档五家可先使用独立配置模板，保留已有 `.env`：

```bash
cp .env.five.example .env.five.local
gpu-price-monitor collect --env-file .env.five.local --providers nebius,lambda,crusoe,autodl,ucloud --pretty
```

该模板设置 `GPU_PRICE_MONITOR_SOURCE_POLICY=api_preferred`；密钥留空可运行公开路径，填入 Lambda / UCloud 凭据后按策略选择账号接口。只填一把 UCloud 密钥或漏填 targets 会报配置错误，不能当成功取到小时价。下面的通用模板仍以 `configured` 保持兼容：

```bash
cp .env.example .env
cp configs/nebius-targets.example.json configs/nebius-targets.local.json
cp configs/ucloud-targets.example.json configs/ucloud-targets.local.json
gpu-price-monitor status --env-file .env
```

`.env` 必须通过 `--env-file .env` 或 `Settings.from_env(env_file=".env")` 显式加载。进程环境优先，空值也能清除文件设置；不做 shell 执行、变量插值或自动发现。直接构造 `Settings()` 不读凭据文件。

| 来源 | 必要配置 |
| --- | --- |
| 九家公开模式 | 无必填 env；兼容模式保持 `*_SOURCE=public`；五家推荐 `GPU_PRICE_MONITOR_SOURCE_POLICY=api_preferred` |
| Nebius 配置估价 | `NEBIUS_SOURCE=api`、`NEBIUS_ACCESS_TOKEN`、`NEBIUS_PRICE_TARGETS_FILE` 或 `NEBIUS_PRICE_TARGETS_JSON` |
| Lambda 认证目录 | `LAMBDA_API_KEY`，配合 `api_preferred` 或显式 `LAMBDA_SOURCE=api`；返回容量位置但不生成地区差价 |
| UCloud 配置询价 | `UCLOUD_PUBLIC_KEY`、`UCLOUD_PRIVATE_KEY`、`UCLOUD_PRICE_TARGETS_FILE` 或 `UCLOUD_PRICE_TARGETS_JSON`，配合 `api_preferred` 或显式 `UCLOUD_SOURCE=api`；可选 `UCLOUD_PROJECT_ID` |
| AutoDL 地区市场 | `AUTODL_SOURCE=market`、`AUTODL_STORAGE_STATE_PATH`；失效会话返回登录错误，不回退首页目录价 |

targets 模板是待填写配置示例，不是已验证可售规格。Nebius 的项目、平台、预设、GPU 数量及磁盘配置必须与账号实际配置一致；只将资源规格发送到 calculator，不调用资源创建接口。UCloud 需要指定一台完整主机的地区、可用区、GPU、CPU、内存、磁盘与计费方式。私钥仅本地签名，认证字段不写入结果。

授权会话可由调用者在自己的浏览器环境准备，例如 `python -m playwright codegen --save-storage=playwright/.auth/autodl.storage-state.json https://www.autodl.com/market/list`，手动登录后关闭窗口，并将该路径填入 env。会话文件、`.env` 与 `*.local.json` 已被 Git 忽略，不要公开分享。

RunPod 的 Secure Cloud 与 Community Cloud 是不同云档位，不是普通 / 会员身份；两档金额通过 `cloud_tier` 与 `conditions.cloud_type` 保留。DigitalOcean 和 Verda 的整实例价按明确卡数分摊，同时保留 `instance_price`。Verda USD / EUR 是两张原币挂牌，不是库内换汇；Azure 仅限四个固定已核验 SKU。普通价、会员价、合同价、组件价、套餐价、起价、询价及下线状态分别保留。按月金额保持按月；库不换成美元，不用假定 720 小时将月租转成小时价。RackRate 是使用本库的应用，其美元换算、发布和定时逻辑不包含在库内。

## 验证

```bash
python -m unittest discover -s tests -v
gpu-price-monitor validate-config --config configs/collect.all.example.json
```

离线测试使用明确的合成或已归档公开样本，不证明账号可访问。真实采样文件保留原始币种、单位、来源和 UTC 时间，不作为运行时回退数据。
