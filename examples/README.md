# 真实返回与历史样本

日期 JSON 是特定时刻的固定采样，不是持续更新价目表。库不会将它们当作实时采集失败的回退数据，也不会自动写入这些文件。以文件内 UTC `collected_at` / `observed_at` 为准，它们不代表页面发布日期或价格生效日。来源 URL、原始币种、单位和条件必须随记录保留。

## 当前九家范围：2026-10-21

[nine-providers-2026-10-21.json](nine-providers-2026-10-21.json) 是 0.8.0 九家公开来源的真实采样，UTC `2026-10-21T07:12:56.913219+00:00`，即北京时间 **2026-10-21 15:12:56**，全部九家成功，共 **833 条**。不使用账号密钥或授权市场会话。

| 平台 | 记录数 | 原始口径与位置边界 |
| --- | ---: | --- |
| Nebius | 36 | USD / ILS 小时组件，按需 / Spot，仅平台覆盖 |
| Crusoe | 24 | USD 每 GPU 小时，含 Contact sales，地区未知 |
| Lambda | 22 | USD 每 GPU 小时，明确多卡配置，地区未知 |
| UCloud | 374 | CNY 月套餐，官方中国 / region / zone，全部下线 |
| AutoDL | 24 | CNY 每 GPU 小时，普通 / 会员各 12，地区未知 |
| RunPod | 68 | USD 每 GPU 小时，Secure / Community 分开，地区未知 |
| DigitalOcean | 19 | USD 完整实例价按卡分摊，按需 11 / Spot 8，地区未知 |
| Verda | 52 | USD / EUR 两原币完整实例表，按需 / Spot，地区未知 |
| Azure | 214 | USD 四固定 SKU 按需 / Spot，45 个价格地区；14 条国家未知 |

本批 574 条有国家关联，588 条有价格 region / zone，36 条仅平台覆盖，209 条位置未知；国家 / 地区代码共 23 个（含 UCloud 的 CN）。这些是返回记录覆盖，不是所有市场、全部型号或可购库存覆盖。

新增 RunPod 保留 Secure / Community 两档，DigitalOcean 和 Verda 将完整实例价按明确 GPU 数分摊；Verda USD / EUR 是分别抓取的原币牌价；Azure 当前仅四个固定已核验 GPU SKU（T4 / GB200 / H100 NVL / A100 PCIe），返回实际价格地区。不将 Spot 当普通价，不推断未知国家 / 地区，不证明全部型号、国家或实时可购。

当前版本重新发起公开采集：

```bash
gpu-price-monitor collect --providers all --coverage --pretty
```

0.8.0 起 `all` 运行上述九家，0.9.0 / 0.10.0 延续该范围；HTTP-only 可排除 AutoDL，只有 AutoDL 需要本地 Chromium。来源变化可能使状态 / 价格 / 条数变化，文件是历史证据而非运行时回退。

## 历史：原五家范围，2026-10-21

[five-providers-2026-10-21.json](five-providers-2026-10-21.json) 是原五家官方公开来源的历史真实采集，UTC `2026-10-21T06:35:03.737019+00:00`，即北京时间 **2026-10-21 14:35:03**。不使用账号密钥或授权市场会话。

| 平台 | 记录数 | 单位与条件 | 地理证据 |
| --- | ---: | --- | --- |
| Nebius | 36 | USD / ILS，`gpu_hour`，按需 / Spot 组件价 | `platform_coverage`，不是国家 / 地区独立价 |
| Crusoe | 24 | USD，`gpu_hour`，含空金额 Contact sales | 位置未知目录 |
| Lambda | 22 | USD，`gpu_hour`，保留 1 / 2 / 4 / 8 卡配置 | 位置未知目录 |
| AutoDL | 24 | CNY，`gpu_hour`，普通 / 会员各 12 条 | 首页目录，位置未知 |
| UCloud | 374 | CNY，`gpu_month`，完整月包按卡分摊 | 中国 / 地区 / zone 已绑定，全部 `offline` |

总计 480 条。地理汇总中 374 条绑定中国位置但全部下线，36 条只有平台覆盖，70 条未定位。挂牌、组件价、会员价和月包不能直接当作同一可购小时最低价；该文件也不证明可选认证 API 或 AutoDL 市场已成功实测。

当前版本可重新发起公开采集：

```bash
gpu-price-monitor collect --providers all --coverage --pretty
```

0.7.0 当时的 `all` 只运行 Nebius、Lambda、Crusoe、AutoDL、UCloud；0.8.0 扩为九家，0.9.0 / 0.10.0 延续该范围。新请求内容 / 条数可能变化，不能保证重新得到历史文件中的价格或数量。型号 `coverage` 只针对本次返回集合，不表示全市场、全硬件变体或库存完整覆盖，也不计算跨币种 / 跨单位最低价。

## 历史：2026-10-20 的旧版全来源范围

[all-providers-2026-10-20.json](all-providers-2026-10-20.json) 与 [mainstream-coverage-2026-10-20.json](mainstream-coverage-2026-10-20.json) 属于 **0.6.0 的历史 11 家范围**，其中若干适配器已从 0.7.0 移除。它们不表示当前仍支持旧版所有平台；当前 `--providers all` 不能重现旧版范围。保留旧 JSON 原样以便核查当时来源、字段及型号覆盖，不把旧的“零缺口”结论套用到当前九家。

旧数据可能同时含 GPU 组件、完整实例分摊、容器、共享算力费率、不同币种与月 / 小时单位，不能仅按 GPU 名称合并报价。历史文件中的数量、来源和时间均以其自身记录为准。

## 历史：Lambda / AutoDL，2026-10-20

[lambda-autodl-2026-10-20.json](lambda-autodl-2026-10-20.json) 是当日北京时间 14:55 的公开采样，共 46 条：Lambda 22 条、AutoDL 24 条（普通 / 会员各 12 条）。会员条件和原始资源单位保留；两家公开价目未绑定地区，不证明当时有库存或认证接口已成功。

## 历史：UCloud 北京 2 月包，2026-10-20

[ucloud-public-cn-bj2-2026-10-20.json](ucloud-public-cn-bj2-2026-10-20.json) 是当日北京时间 15:23 的匿名 CLI 筛选结果，当时全量仅覆盖活动 10204 / 10216，共 358 个套餐；文件中返回北京 2 / 可用区 B 的 18 条单卡 T4S。它不是当前新增活动 10248 后的 374 条全量快照。

```bash
gpu-price-monitor collect --providers ucloud --ucloud-source public \
  --country CN --region cn-bj2 --zone cn-bj2-02 --gpu T4S --gpu-count 1 \
  --billing-mode monthly --currency CNY --pretty
```

这是当前版本可执行的筛选示例，不保证重现历史 18 条。金额为 `CNY / gpu_month`，整套餐为 `instance_month`，配置和原始周期保留，不换算小时。该次采样相关可用区均被标 `offline`，不得作为现货价格；促销购买资格未核验。

## 历史：Nebius / Crusoe，2026-10-15

[nebius-crusoe-2026-10-15.json](nebius-crusoe-2026-10-15.json) 是当日 USD / 按需筛选的真实公开采样，共 18 条：Nebius 9、Crusoe 9；其中 15 条数值、3 条询价。数值为 USD / GPU / 小时，组件和购买条件以各记录为准，不能替换成后续采样的型号、价格或条数。

测试目录中带 synthetic / template 标记的夹具是合成测试材料，不属于这些实抓示例。第三方来源内容使用说明见 [数据政策](../docs/DATA_POLICY.md)。


## 将报价导出为 CSV（0.9.0 起，0.10.0 默认英中表头）

**英中表头版**：[gpu-prices-2026-10-21-zh.csv](gpu-prices-2026-10-21-zh.csv)，对应同批 [JSON](gpu-prices-2026-10-21-zh.json)。0.10.0 实际采集完成于北京时间 **2026-10-21 16:05:25**（UTC `2026-10-21T08:05:25.215545+00:00`），九家均成功，共 833 条、51 列，每列均为英文标识加中文说明。原币、周期、来源和报价条件保留；374 条 UCloud 月包仍标记 `offline`。

[gpu-prices-2026-10-21.csv](gpu-prices-2026-10-21.csv) 是 0.9.0 实际采集并导出的完整 CSV（833 条报价、51 列），对应同批 [JSON](gpu-prices-2026-10-21.json)。采集完成时间为北京时间 **2026-10-21 15:53:17**（UTC `2026-10-21T07:53:17.213423+00:00`），九家均成功。CSV 保留 USD / CNY / EUR / ILS 原币和原计费周期，374 条 UCloud 月包报价标记 `offline`。它是该时刻的采样，后续最新价格需重新运行采集。

```bash
gpu-price-monitor collect --providers all --format csv > prices.csv
# 为程序生成纯英文表头；报价数据与默认导出一致。
gpu-price-monitor collect --providers all --format csv --csv-headers english > prices.english.csv
```

0.10.0 起全部列默认带中文翻译，公开 `CSV_HEADERS` 对应双语标签，`CSV_COLUMNS` 保留同序英文 ID。`--csv-headers bilingual` 显式选择默认表头；英文表头使用 `--csv-headers english` 或 Python `prices_to_csv(result, bilingual_headers=False)`。此选择只改第一行，不翻译 GPU / 平台 / 币种 / 状态值，也不改变 JSON。

CSV 是本次通过筛选的报价表，含 UTF-8 BOM / CRLF，不是覆盖报告附表。库不换汇或上传；原币 / 计费周期、地区证据、会员 / 云档位 / Spot、下线和采样时间保留。`prices_to_csv(result)` 可将一次 Python 调用的结果转为相同 CSV 文本，无需再次请求平台。导出历史 JSON 不会把历史价格变成新观察；完整来源状态、错误及 coverage 仍看原 JSON。CLI 诊断写 stderr，退出码继续区分成功 / 部分失败 / 失败，不能仅因文件存在就认为采集全部成功。
