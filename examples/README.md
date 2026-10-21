# 真实返回与历史样本

日期 JSON 是特定时刻的固定采样，不是持续更新价目表。库不会将它们当作实时采集失败的回退数据，也不会自动写入这些文件。以文件内 UTC `collected_at` / `observed_at` 为准，它们不代表页面发布日期或价格生效日。来源 URL、原始币种、单位和条件必须随记录保留。

## 当前五家范围：2026-10-21

[five-providers-2026-10-21.json](five-providers-2026-10-21.json) 是五家官方公开来源的真实采集，UTC `2026-10-21T06:35:03.737019+00:00`，即北京时间 **2026-10-21 14:35:03**。不使用账号密钥或授权市场会话。

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

从 0.7.0 开始 `all` 只运行 Nebius、Lambda、Crusoe、AutoDL、UCloud。新请求内容 / 条数可能变化，不能保证重新得到历史文件中的价格或数量。型号 `coverage` 只针对本次返回集合，不表示全市场、全硬件变体或库存完整覆盖，也不计算跨币种 / 跨单位最低价。

## 历史：2026-10-20 的旧版全来源范围

[all-providers-2026-10-20.json](all-providers-2026-10-20.json) 与 [mainstream-coverage-2026-10-20.json](mainstream-coverage-2026-10-20.json) 属于 **0.6.0 的历史 11 家范围**，其中若干适配器已从 0.7.0 移除。它们不表示当前仍支持旧版所有平台；当前 `--providers all` 不能重现旧版范围。保留旧 JSON 原样以便核查当时来源、字段及型号覆盖，不把旧的“零缺口”结论套用到当前五家。

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
