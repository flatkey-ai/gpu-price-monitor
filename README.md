# GPU Price Monitor

根据五家 GPU 云平台的官方价格入口构建的采集库：**Nebius、Lambda、Crusoe、AutoDL、UCloud**。提供 Python 调用和 CLI JSON，只负责抓取、解析、筛选及返回报价。定时、存储、换汇、上传和比价由调用方处理。

[English](README.en.md) · [文档需求与实现对照](docs/DOCUMENT_COVERAGE.md) · [数据口径](docs/DATA_MODEL.md) · [环境配置](.env.example)

从 **0.7.0** 起仅支持上述五家，`--providers all` 也只运行这五家。其他平台适配器已移除；旧日期示例仅作为历史采样，不代表当前采集范围。本版本从源码安装，未发布至 PyPI。

## 先看地区能力

公开价格页并不一定提供不同国家的独立价格。库不根据公司总部、币种、访问 IP、机房库存或平台覆盖地点推测价格地区，也不会将同一目录价复制到多个国家。

| 平台 | 默认免费来源 | 地区报价能力 |
| --- | --- | --- |
| Nebius | 官方公开计算价目，含 USD / ILS、按需 / 抢占式及组件价 | 公开文档的机房覆盖单独标注。可选 `api` 按项目地区及完整配置询价，核验项目地区和官方国家映射；需 access token |
| Lambda | 官方实例价格页，保留 1 / 2 / 4 / 8 卡配置 | 公开表不绑定具体地区。可选 API 的容量地区单独保留，不当成逐地区价 |
| Crusoe | 官网 GPU instances 区块 | 当前公开表未给逐地区价格；保留未知地区及 Contact sales，不混入托管推理报价 |
| AutoDL | 官网普通用户 / 炼丹会员价 | 公开首页不绑定地区。可选 `market` 读取用户授权登录态的市场挂牌，保留市场地区；需有效会话 |
| UCloud | 官方匿名促销套餐及位置目录 | 每条套餐绑定原始国家 / 地区 / 可用区。可选 `api` 按完整配置询价；需公私钥及 targets |

**2026-10-21 14:35（北京时间）实抓：五家成功，共 480 条记录。** 其中 374 条 UCloud 月包绑定中国地区，但全部标为下线；36 条 Nebius 记录只有平台机房覆盖；其余 70 条目录价未绑定地区。详见 [真实返回 JSON](examples/five-providers-2026-10-21.json)。不能据此声称已获得五家在所有国家的可购价格。

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

Windows PowerShell 使用 `py -3 -m venv .venv` 与 `.\.venv\Scripts\Activate.ps1`。Linux 若缺少浏览器系统库，使用 `python -m playwright install --with-deps chromium`。仅 HTTP 采集可安装基础包 `python -m pip install .` 并指定 `--providers nebius,lambda,crusoe,ucloud`。

CLI 的 stdout 只包含 JSON，诊断写入 stderr。退出码 `0` 表示全部成功（含筛选无匹配），`2` 为部分失败，`1` 为失败或配置无效。失败不会返回零元或上次价格。

```python
from gpu_price_monitor import Settings, collect_prices

result = collect_prices("all", settings=Settings(), include_coverage=True)
for quote in result["prices"]:
    print(quote["provider"], quote["gpu_model"], quote["amount"],
          quote["currency"], quote["unit"], quote["price_scope"],
          quote["compute_countries"], quote["regions"], quote["zones"])
```

## 按国家和地区取价

同一报价的国家、地区、可用区必须同时匹配，不把它们分别匹配到不同记录。国家筛选用 ISO 两字母代码，可重复传入。尚未公开或支持的维度返回 `unsupported_filter`；本应支持但相关报价缺少位置证据返回 `unverifiable_filter`，不静默当成无匹配。

```bash
# 真实公开地区月包：保留下线状态，不能当现货或小时价。
gpu-price-monitor collect --providers ucloud --country CN --region cn-bj2 --zone cn-bj2-02 --pretty

# Nebius 的公开地区仅表示平台覆盖，JSON 会标 platform_coverage。
gpu-price-monitor collect --providers nebius --region eu-north1 --currency USD --pretty

# 有效账号和配置填好后，再对项目所在国家/地区进行完整配置询价。
gpu-price-monitor collect --env-file .env --providers nebius --nebius-source api --country FI --region eu-north1 --pretty
gpu-price-monitor collect --env-file .env --providers ucloud --ucloud-source api --country CN --region cn-bj2 --pretty

# 已有授权登录态的 AutoDL 市场；地区代码以市场原始返回值为准。
gpu-price-monitor collect --env-file .env --providers autodl --autodl-source market --pretty
```

Python 筛选字段为 `compute_countries`、`regions`、`zones`、`gpu_models`、`gpu_counts`、`currencies`、`billing_modes`，值均为数组。例如 `collect_prices(["ucloud"], {"compute_countries": ["CN"], "regions": ["cn-bj2"]}, settings=Settings())`。销售国家与部署国家不同，当前 `sales_countries` 不支持。

`geographic_coverage` 汇总本次返回报价中有国家绑定、地区绑定、仅平台覆盖、位置未知的数量。`price_scope` 明确区别 `unlocated_catalog`、`platform_coverage`、`regional_quote`、`zone_quote`、`requested_region_quote`、`requested_zone_quote`。它不表示库存或购买资格。

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
| 五家公开模式 | 无必填 env；所有 `*_SOURCE=public` |
| Nebius 配置估价 | `NEBIUS_SOURCE=api`、`NEBIUS_ACCESS_TOKEN`、`NEBIUS_PRICE_TARGETS_FILE` 或 `NEBIUS_PRICE_TARGETS_JSON` |
| Lambda 认证目录 | `LAMBDA_SOURCE=api`、`LAMBDA_API_KEY`；返回容量位置但不生成地区差价 |
| UCloud 配置询价 | `UCLOUD_SOURCE=api`、`UCLOUD_PUBLIC_KEY`、`UCLOUD_PRIVATE_KEY`、`UCLOUD_PRICE_TARGETS_FILE` 或 `UCLOUD_PRICE_TARGETS_JSON`，可选 `UCLOUD_PROJECT_ID` |
| AutoDL 地区市场 | `AUTODL_SOURCE=market`、`AUTODL_STORAGE_STATE_PATH`；失效会话返回登录错误，不回退首页目录价 |

targets 模板是待填写配置示例，不是已验证可售规格。Nebius 的项目、平台、预设、GPU 数量及磁盘配置必须与账号实际配置一致；只将资源规格发送到 calculator，不调用资源创建接口。UCloud 需要指定一台完整主机的地区、可用区、GPU、CPU、内存、磁盘与计费方式。私钥仅本地签名，认证字段不写入结果。

授权会话可由调用者在自己的浏览器环境准备，例如 `python -m playwright codegen --save-storage=playwright/.auth/autodl.storage-state.json https://www.autodl.com/market/list`，手动登录后关闭窗口，并将该路径填入 env。会话文件、`.env` 与 `*.local.json` 已被 Git 忽略，不要公开分享。

普通价、会员价、合同价、组件价、套餐价、起价、询价及下线状态分别保留。按月金额保持按月；库不换成美元，不用假定 720 小时将月租转成小时价。RackRate 是使用本库的应用，其美元换算、发布和定时逻辑不包含在库内。

## 验证

```bash
python -m unittest discover -s tests -v
gpu-price-monitor validate-config --config configs/collect.all.example.json
```

离线测试使用明确的合成或已归档公开样本，不证明账号可访问。真实采样文件保留原始币种、单位、来源和 UTC 时间，不作为运行时回退数据。
