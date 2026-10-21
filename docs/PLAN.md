# GPU 云算力价格采集库实施方案

更新：2026-10-21，版本 0.7.0。当前范围严格为用户原始 Word 核查的 **Nebius、Lambda、Crusoe、AutoDL、UCloud**。这是已实现能力与验证边界的说明，原始事项逐项见 [文档覆盖对照](DOCUMENT_COVERAGE.md)。

## 交付边界

库负责只读访问、超时及有限重试、确定性解析、单位 / 配置核对、筛选和结构化结果；提供 Python `collect_prices` 与 JSON CLI。调用方负责调度、部署、数据库、历史、上传、换汇、跨平台比较、告警和前端。RackRate 是独立调用方，本库不内置其上传地址或业务密钥。

采集对象是 GPU 云主机 / GPU 容器价格；排除 Token 模型 API、托管模型推理、微调任务、硬件售卖及混入的裸金属配置。GPU 组件费、公开整机每卡分摊、会员挂牌和促销月包分别标注。没有数值的询价项仍是有效记录，但不能当成零元。

## 来源选择

默认全为 `public`，不需要充值、绑卡、密钥或购买实例。仅 AutoDL 需要免费本地浏览器。认证与市场分支显式选择；已有凭据不改变默认路径。

| 平台 | 默认实施路径 | 已实现的可选路径 | 验证限制 |
| --- | --- | --- | --- |
| Nebius | 官方 Compute 文档，组件 / 币种 / Spot / 日期区间 | 项目地区 GET 核验 + Estimate Batch 完整配置估价，支持 hour / month 聚合及账号合同口径 | 公开已实抓；API 14 项合成测试，未成功真实鉴权 |
| Lambda | 官方实例页，保留 1 / 2 / 4 / 8 卡配置 | 认证 instance-types，整机美分 / GPU 数分摊，容量地区另存 | 公开已实抓；API 未成功真实鉴权，容量不能补地区价 |
| Crusoe | GPU instances 独立区块，按需 / Spot / Contact sales | 未确认公共 VM 价格 API；不调用账单或托管推理作替代 | 公开已实抓；价格未绑定地区 |
| AutoDL | 公开首页普通 / 会员价，新未登录上下文 | 用户授权 storage state 的按量市场，读取页面金额 / 单位、地区及配置 | 首页已实抓；市场 8 项合成测试，未成功登录实抓 |
| UCloud | 匿名活动具体月套餐 + 官方位置目录 | 签名 GetUHostInstancePrice，完整小时主机目标及官方位置核验 | 月包已实抓但本次全部下线；API 未成功真实鉴权 |

源码与配置入口见 [README](../README.md)、[PROVIDERS](PROVIDERS.md) 及 [.env.example](../.env.example)。只读请求不创建或购买资源，账号访问权限仍由供应商决定。

## Python 与 CLI 契约

```python
from gpu_price_monitor import Settings, collect_prices

result = collect_prices(
    "all",
    {"currencies": ["USD", "ILS", "CNY"]},
    settings=Settings(),
    include_coverage=True,
)
```

```bash
gpu-price-monitor collect --providers all --coverage --pretty
gpu-price-monitor collect --providers ucloud --country CN --region cn-bj2 --zone cn-bj2-02 --pretty
gpu-price-monitor collect --env-file .env --providers nebius --nebius-source api --country FI --region eu-north1 --pretty
gpu-price-monitor collect --env-file .env --providers autodl --autodl-source market --pretty
```

结果包含 `prices`、逐平台 `provider_results` 与本次 `geographic_coverage`；`--coverage` 可增加型号覆盖报告。它只描述本批结果，不代表所有平台、硬件变体、国家或库存已覆盖，不输出跨币种 / 跨单位最低价。stdout 只输出 JSON，失败诊断与退出码区分全部成功、部分失败和失败。结构改变或凭据失效不返回上次价格。

`.env` 只显式加载；进程环境优先，包括空值。FILE / JSON 目标来源互斥，FILE 相对 env 文件目录解析，没有 env 文件时相对当前目录。模板仅演示配置，不能当已确认可售规格。密钥、授权会话、私有目标配置不入 Git，认证信息不写到价格返回。

## 地理链路

先保存来源位置证据，再筛选，不先为每个平台列国家并复制相同价格。

1. UCloud 公开月包使用官方地区 / zone 目录；认证入口每次也加载目录，核对完整请求位置与国家，国家筛选已开放。
2. Nebius 公开覆盖标为 `platform_coverage`；认证估价只有在项目地区 GET 与目标一致、官方国家映射通过时才标 `requested_region_quote`。合同价仍为账号价。
3. AutoDL 首页不补位置；授权市场仅保留来源 region 及地区名，不猜国家 / zone。
4. Lambda 容量地区单列；Crusoe 公开表没有价格位置。未知位置保持 `unlocated_catalog`，不写成 global。
5. 组合筛选必须满足同一报价的位置关系。不支持报 `unsupported_filter`；相关报价缺证据报 `unverifiable_filter`，不静默当无匹配。

## 价格语义

保留原始名称 / SKU、GPU 变体 / 显存 / 卡数、CPU / RAM / 磁盘资源和单位、金额字符串、币种、计费方式、原价 / 折扣、会员 / 合同 / 促销条件、询价及下线状态、来源 URL、观察时间与明确生效日期。来源未给的字段保持未知。

Lambda API 的美分是整实例价；Nebius / UCloud 估价是完整指定配置，按 GPU 数分摊不等于裸卡单价。Nebius 月聚合不等于包月承诺；UCloud 月促销不等于按需小时价；AutoDL 会员需资格。所有模式均不自动换美元、不假定 720 小时、不以 0 填补联系销售项。

## 当前验收证据

2026-10-21 14:35（北京时间）[五平台公开实抓](../examples/five-providers-2026-10-21.json) 成功返回 480 条：36 Nebius、24 Crusoe、22 Lambda、24 AutoDL、374 UCloud。UCloud 374 条均为中国下线月包；36 条 Nebius 只是平台覆盖；其余 70 条位置未知。采样时刻不是页面发布时间，也不是实时库存承诺。

公开端已有真实 Python / CLI 返回；新增认证 / 授权路径以明确合成样本测试解析和拒绝错误行为，尚无有效账号成功联调证据。其余验收命令：

```bash
python -m unittest discover -s tests -v
gpu-price-monitor validate-config --config configs/collect.all.example.json
```

后续验证限于已有范围：用授权账号进行最小只读询价 / 市场采样，核对实际配置、单位、位置及账号条件后才可记录“真实认证成功”。在此之前不承诺全地区、全型号、全折扣或可购性。历史 JSON 只保留当时结果，不进入运行时兜底。
