# GPU Price Monitor

根据九家 GPU 云平台的官方价格入口构建的采集库：**Nebius、Lambda、Crusoe、AutoDL、UCloud、RunPod、DigitalOcean、Verda、Azure**。提供 Python 调用和 CLI JSON / CSV，只负责抓取、解析、筛选及返回报价。定时、存储、换汇、上传和比价由调用方处理。

[English](README.en.md) · [文档需求与实现对照](docs/DOCUMENT_COVERAGE.md) · [数据口径](docs/DATA_MODEL.md) · [环境配置](.env.example)

当前版本 **0.10.0** 为 CSV 的全部列提供默认英中双语表头，可选纯英文表头；0.9.0 已新增 CSV 导出；0.8.0 已在原 Word 五家基础上增加 RunPod、DigitalOcean、Verda、Azure，`--providers all` 仍运行这九家。旧日期示例保留当时范围，不代表当前支持全市场。本版本从源码安装，未发布至 PyPI。安装后可用 `gpu-price-monitor --version` 确认版本：CSV 导出需 0.9.0 起，默认双语表头及表头切换需 0.10.0 起。

## 先看地区能力

公开价格页并不一定提供不同国家的独立价格。库不根据公司总部、币种、访问 IP、机房库存或平台覆盖地点推测价格地区，也不会将同一目录价复制到多个国家。

| 平台 | 默认免费来源 | 地区报价能力 |
| --- | --- | --- |
| Nebius | 官方公开计算价目，含 USD / ILS、按需 / 抢占式及组件价 | 公开文档的机房覆盖单独标注。可选 `api` 按项目地区及完整配置询价，核验项目地区和官方国家映射；需 access token |
| Lambda | 官方实例价格页，保留 1 / 2 / 4 / 8 卡配置 | 公开表不绑定具体地区。可选 API 的容量地区单独保留，不当成逐地区价 |
| Crusoe | 官网 GPU instances 区块 | 当前公开表未给逐地区价格；保留未知地区及 Contact sales，不混入托管推理报价 |
| AutoDL | 官网普通用户 / 炼丹会员价 | 公开首页不绑定地区。可选 `market` 读取用户授权登录态的市场挂牌，保留市场地区；需有效会话 |
| UCloud | 官方匿名促销套餐及位置目录 | 每条套餐绑定原始国家 / 地区 / 可用区。可选 `api` 按完整配置询价；需公私钥及 targets |
| RunPod | 官方匿名 GraphQL GPU Pods 目录 | Secure / Community 云档位分开；目录未绑定价格地区，不把机房覆盖当地区价 |
| DigitalOcean | 官方 GPU Droplet 定价文档 | 按需 / Spot 分开，整实例按明确 1 / 8 卡数分摊；文档未给价格地区 |
| Verda | 官方 USD / EUR GPU instances 表 | 每种币种分别抓取，按需 / Spot 和完整实例总价保留；不推断芬兰等部署国家 |
| Azure | 官方匿名 Retail Prices API | 当前只采四个已核验 SKU（T4、GB200、H100 NVL、A100 PCIe）的已生效地区零售价及官方目录已核验国家映射；不表示全 SKU、国家或库存覆盖 |

**2026-10-21 15:12:56（北京时间）九家公开实抓成功，共 833 条**：Nebius 36、Crusoe 24、Lambda 22、UCloud 374、AutoDL 24、RunPod 68、DigitalOcean 19、Verda 52、Azure 214。574 条有已核验国家关联，588 条有价格地区 / 可用区，其中 UCloud 374 条全部下线；36 条仅平台覆盖，209 条未定位目录。Azure 214 条覆盖 45 个价格地区，其中 14 条国家未知。以上不是全地域可购库存。 见 [真实返回 JSON](examples/nine-providers-2026-10-21.json)；原 Word 范围的 [五家历史样本](examples/five-providers-2026-10-21.json) 另行保留。

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
python -m gpu_price_monitor collect --providers all --coverage --pretty
```

Windows PowerShell 使用 `py -3 -m venv .venv` 与 `.\.venv\Scripts\Activate.ps1`。Linux 若缺少浏览器系统库，使用 `python -m playwright install --with-deps chromium`。仅 HTTP 采集可安装基础包 `python -m pip install .` 并指定 `--providers nebius,lambda,crusoe,ucloud,runpod,digitalocean,verda,azure`。

CLI 的 stdout 默认只包含 JSON，`collect --format csv` 时只包含 CSV；诊断写入 stderr。退出码 `0` 表示全部成功（含筛选无匹配），`2` 为部分失败，`1` 为失败或配置无效。失败不会返回零元或上次价格。

```python
from gpu_price_monitor import Settings, collect_prices

result = collect_prices("all", settings=Settings(), include_coverage=True)
for quote in result["prices"]:
    print(quote["provider"], quote["gpu_model"], quote["amount"],
          quote["currency"], quote["unit"], quote["price_scope"],
          quote["compute_countries"], quote["regions"], quote["zones"])
```

## 导出 CSV 表格

**0.9.0 新增** `prices_to_csv(result)` 与 `collect --format csv`；**0.10.0 起所有表头默认英中双语**，例如 `provider（平台）`，可选择英文 ID 表头供程序读取。JSON 仍是默认格式，已有 Python `collect_prices` 返回结构、CLI JSON 和退出码兼容。CSV 使用 Python 标准库生成文本，无需额外表格依赖；库不会自行写文件、上传或换汇。

```bash
# 默认仍返回完整 JSON，可查看逐平台状态和覆盖汇总。
gpu-price-monitor collect --providers all --coverage --pretty > prices.json

# CSV 输出到 stdout；由 shell 保存文件，诊断单独留在 stderr。
gpu-price-monitor collect --providers all --format csv > prices.csv
# 程序读取：保留纯英文固定字段名。
gpu-price-monitor collect --providers all --format csv --csv-headers english > prices.english.csv
```

```python
from pathlib import Path
from gpu_price_monitor import Settings, collect_prices, prices_to_csv

result = collect_prices("all", settings=Settings())
csv_text = prices_to_csv(result)  # 默认英中双语表头
english_csv_text = prices_to_csv(result, bilingual_headers=False)
# 返回文本已含 BOM 与 CRLF；使用 utf-8、禁用换行改写，避免重复 BOM。
Path("prices.csv").write_text(csv_text, encoding="utf-8", newline="")
```

`--csv-headers bilingual` 可显式选择默认双语表头；`--csv-headers english` 使用纯英文表头。这个选项只影响 CSV 表头，JSON 与报价值不变。Python 公开常量 `CSV_COLUMNS` 保留稳定英文 ID，`CSV_HEADERS` 为按相同顺序排列的英中表头；0.10.0 升级后，依赖英文列名的脚本应显式选择英文模式。

每条 CSV 行对应一条通过筛选的报价，保留型号 / 平台、原始金额 / 币种 / 计费周期、完整实例价、国家 / 地区 / 可用区、地区证据范围、普通 / 会员和云档位条件、Spot、下线状态、来源与采样时间。未知地区保持空或明确未知范围，不补成 global，不把平台覆盖当地区价。CNY / EUR / ILS 不转换为美元，月价不转小时价；RackRate 应用另行负责 USD 展示、存储和网站更新。

文件编码为 **UTF-8 BOM**，行结束符为 **CRLF**。CSV 只包含报价表，不附加 `provider_results`、`geographic_coverage` 或型号 `coverage` 表；即使指定 `--coverage`，完整汇总仍应查看 JSON。部分失败退出 `2`，全部失败 / 配置错误退出 `1`，错误诊断写入 stderr；CSV 只写成功来源的报价，无报价时仅表头。不能只根据 CSV 文件存在判断采集成功，调用方须检查退出码或保留 JSON 状态。

## 按国家和地区取价

同一报价的国家、地区、可用区必须同时匹配，不把它们分别匹配到不同记录。国家筛选用 ISO 两字母代码，可重复传入。尚未公开或支持的维度返回 `unsupported_filter`；本应支持但相关报价缺少位置证据返回 `unverifiable_filter`，不静默当成无匹配。

```bash
# 真实公开地区月包：保留下线状态，不能当现货或小时价。
gpu-price-monitor collect --providers ucloud --country CN --region cn-bj2 --zone cn-bj2-02 --pretty

# Azure 的价格响应绑定 ARM region；国家由官方目录已核验映射关联。
gpu-price-monitor collect --providers azure --gpu T4 --country US --region eastus --pretty

# Nebius 的公开地区仅表示平台覆盖，JSON 会标 platform_coverage。
gpu-price-monitor collect --providers nebius --region eu-north1 --currency USD --pretty

# 有效账号和配置填好后，再对项目所在国家/地区进行完整配置询价。
gpu-price-monitor collect --env-file .env --providers nebius --nebius-source api --country FI --region eu-north1 --pretty
gpu-price-monitor collect --env-file .env --providers ucloud --ucloud-source api --country CN --region cn-bj2 --pretty

# 已有授权登录态的 AutoDL 市场；地区代码以市场原始返回值为准。
gpu-price-monitor collect --env-file .env --providers autodl --autodl-source market --pretty
```

Python 筛选字段为 `compute_countries`、`regions`、`zones`、`gpu_models`、`gpu_counts`、`currencies`、`billing_modes`，值均为数组。例如 `collect_prices(["ucloud"], {"compute_countries": ["CN"], "regions": ["cn-bj2"]}, settings=Settings())`。销售国家与部署国家不同，当前 `sales_countries` 不支持。

`geographic_coverage` 汇总本次返回报价中有国家绑定、地区绑定、仅平台覆盖、位置未知的数量。`price_scope` 明确区别 `unlocated_catalog`、`platform_coverage`、`regional_quote`、`zone_quote`、`requested_region_quote`、`requested_zone_quote`。它不表示库存或购买资格。Azure 部分地区没有已核验国家映射；仅指定国家可能返回 `unverifiable_filter`，可同时指定已核验 region，如上例 US + eastus，不能把未知国家静默当作不匹配。

## 可选账号配置

```bash
cp .env.example .env
cp configs/nebius-targets.example.json configs/nebius-targets.local.json
cp configs/ucloud-targets.example.json configs/ucloud-targets.local.json
gpu-price-monitor status --env-file .env
```

`.env` 必须通过 `--env-file .env` 或 `Settings.from_env(env_file=".env")` 显式加载。进程环境优先，空值也能清除文件设置；不做 shell 执行、变量插值或自动发现。直接构造 `Settings()` 不读凭据文件。

| 来源 | 必要配置 |
| --- | --- |
| 九家公开模式 | 无必填 env；可切换模式的来源保持 `*_SOURCE=public`，新增四家仅使用匿名公开来源 |
| Nebius 配置估价 | `NEBIUS_SOURCE=api`、`NEBIUS_ACCESS_TOKEN`、`NEBIUS_PRICE_TARGETS_FILE` 或 `NEBIUS_PRICE_TARGETS_JSON` |
| Lambda 认证目录 | `LAMBDA_SOURCE=api`、`LAMBDA_API_KEY`；返回容量位置但不生成地区差价 |
| UCloud 配置询价 | `UCLOUD_SOURCE=api`、`UCLOUD_PUBLIC_KEY`、`UCLOUD_PRIVATE_KEY`、`UCLOUD_PRICE_TARGETS_FILE` 或 `UCLOUD_PRICE_TARGETS_JSON`，可选 `UCLOUD_PROJECT_ID` |
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
