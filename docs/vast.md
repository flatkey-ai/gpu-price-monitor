# Vast.ai 公开机器报价

这个适配器读取官方 Search Offers 接口返回的**具体机器组合报价**，不是最低起价。不登录、不读取任何 API key/Cookie，也不创建实例。免费匿名访问于 2026-10-23 实测可用；[官方接口文档](https://docs.vast.ai/api-reference/search/search-offers)仍要求 API key，所以不能保证匿名访问长期开放。拒绝访问时直接报错，不偷偷切换账户或历史价格。

## 独立 Python 调用

```python
from datetime import datetime, timezone
from gpu_price_monitor.providers.vast import collect_result
from gpu_price_monitor.settings import Settings

result = collect_result(
    settings=Settings(timeout_seconds=20, max_retries=0),
    observed_at=datetime.now(timezone.utc).isoformat(),
)
prices = result["prices"]
coverage = result["coverage"]
```

该模块也已接入共享 provider 注册表，可用 `--providers vast` 运行。

先读取官方 `GET https://console.vast.ai/api/v0/gpu_names/unique/` 型号目录，再对每个型号固定请求 `POST https://console.vast.ai/api/v0/bundles`，用 `gpu_name.eq` 查询该型号的 `on-demand` offer。显式传 `allocated_storage: 8`，按 ID 升序，每个型号最多 1000 条；最多并发 4 个型号，每次请求超时上限 20 秒、响应上限 5 MiB、不自动重试。`limit` 可向下调，不能超过上限。2026-10-27 起不再用可租状态或验证状态筛除已有数字价格；这两项来源字段与每个型号的成功、失败、限额状态分别保留。型号目录异常时失败，不猜型号或复用历史结果。

## 费用与配置

- `instance_price` 直接采用接口 `dph_total`，是该 offer 的小时总价；包含本次查询选择的磁盘。`amount = dph_total / num_gpus`，单位美元/卡/小时。不会再次叠加磁盘费用。
- CPU 使用 `cpu_cores_effective`，RAM 使用该 offer 的 `cpu_ram`，不是整个宿主机的 CPU/RAM。RAM/显存保留原始 MB，展示 GB 按 MB / 1000；不把接口显存改成推测的标称规格。
- CPU 数量或名称没有公布时保留 `null` 并列入 `conditions.missing_resource_fields`；不补猜 CPU，也不因此删除已有的独立数字报价。
- `gpu_frac` 是 offer 中 GPU 数相对宿主机 GPU 数的比例，不是分割 GPU 的比例。例如 8 卡主机上的 2 卡 offer 可为 0.25，依然按明确的 2 张卡分摊。
- `storage_cost` 是美元/GB/月；保存该费率与接口返回的小时磁盘费用，仅校验总价组成，不自行按月折算覆盖官方总价。带宽额外收费，税费未说明。优惠预付、Reserved、竞价价、会员资格均不推测。
- API 文档把 `allocated_storage` 单位写作 **GB**，而[官方 CLI](https://github.com/vast-ai/vast-cli/blob/master/vast.py)帮助文字写作 **GiB**。本模块原样传数字 8，以 API 文档标注该请求单位，并在每条报价条件中保留差异；不进行未经证实的 GB/GiB 换算。API 文档示例与 CLI 使用 `on-demand`，虽然文档枚举另列 `ondemand`；本模块采用经实测的 `on-demand`。

## 国家、地区和完整性

国家仅来自**同一报价** `geolocation` 的明确两字母代码，校验为 ISO 3166-1 alpha-2；不由 IP、币种或公司地址推断。原始地点保存在 `location_source.raw_location`。

`Czechia, CZ`、`Ireland, IE`、`, US` 只有国家依据，`regions=[]`、`region_price_verified=false`，不能进入要求完整地区的严格比较表，也不代表全国统一价。对于已明确识别的美国州/加拿大省份（例如 `California, US`、`British Columbia, CA`），地区保留原报价地点，仍不声称它是云可用区。未知地点只保留国家，不擅自提升为地区；国家本身不明确则将该 offer 排除并计数。

结果始终标记 `status=partial`、`coverage.complete=false`。官方文档和 CLI 没有经过验证的游标/分页及全市场总数保证。即使逐型号响应返回 `truncated=false`、条数小于请求上限，也不宣称全量。2026-10-23 的单次混合型号搜索只返回 64 条，可能漏掉 T4 等型号；现在逐项查询官方型号目录，避免少量混合结果代表全部型号。每个型号仍受独立响应上限约束。不会猜测分页参数或把一个快照当全部可选机器。请求过滤范围、每个型号查询结果和排除原因均在 `coverage` 中。

`available` 仅表示搜索响应当时的 `rentable=true`、`rented=false`，并不保证随后点击租用时仍有库存或价格不变。具体 offer ID、时间、CPU/RAM、卡数、存储和地理来源必须一起用于比对。

共享层集成时需保留 `offer_country` 的 `compute_countries`；现有地理归一化若只接受地区报价，会清空这些国家。不要为了通过严格 CSV 校验把国家文字填入 `regions`。`collect_result` 返回 `prices/status/errors/coverage/catalog_coverage/pricing_limitations`；`collect_quotes` 只返回报价列表，每条仍有 `conditions.catalog_coverage=partial`，推荐使用前者读取覆盖情况。

## 验证

`tests/test_vast.py` 覆盖多卡分摊与宿主机比例、地区证据、国家级排除、费用组成冲突、坏字段、重复 ID、无凭据请求、请求上限、匿名 403 和不虚报完整性。`tests/fixtures/vast-public-offers.json` 是 2026-10-23 真实响应的三个脱敏字段子集，仅作历史回归测试；运行时不读 fixture 或旧报价。

2026-10-23 07:39 UTC 新采集得到 64 条可解析报价、32 个型号、18 个国家；其中 23 条有明确州/省信息，41 条只有国家，解析排除 0 条。该次请求的 `truncated=false` 仍保留 `complete=false`。这些是采集快照计数，不是当前市场总量；完整 JSON 和三种 CSV 保存在本地 `work/vast-public-2026-10-23/`，不作为运行时后备数据。

官方参考：[Search Offers](https://docs.vast.ai/api-reference/search/search-offers)、[费用说明](https://docs.vast.ai/guides/instances/pricing)、[官方 CLI](https://github.com/vast-ai/vast-cli/blob/master/vast.py)。
