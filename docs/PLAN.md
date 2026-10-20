# GPU 云算力价格采集库实施方案

方案更新：2026-10-20，版本 0.6.0。通过 11 家官方公开来源获取 GPU 租赁挂牌，提供统一 Python API / JSON CLI，并按 34 项主流 GPU 系列报告覆盖和缺口。公开路径无需账号、密钥、充值或购买资源；可选 Lambda API / UCloud 认证询价保留为独立分支，尚未完成成功的真实认证报价联调。

## 目标与边界

使用者通过自己的环境变量和筛选配置调用同一个开源库，获取 GPU 云算力租赁报价及可追溯条件。

本库负责来源访问、请求超时与有限重试、确定性价格解析、筛选核对、原始单位和条件保留、结构化返回。调用方负责定时执行、部署、数据库和历史、上传、换汇、竞品比较、告警和看板。库不持有 Flatkey 上传地址或专属业务凭据。

模型 Token API、托管模型推理价格和硬件销售不进入当前报价集合。Suanli 明示供云主机与弹性部署共用的 GPU 卡时费率属于算力报价，保留该产品范围，不冒充完整配置实例。公开挂牌不保证即时可购买；需询价、起价、GPU 分项、容器与整机报价分别标识。

## 当前能力

| 来源 | 当前实现 | 限制 |
| --- | --- | --- |
| Nebius | 官方 Compute 公开计价 Markdown，解析资源分项、币种、地区和生效日期 | GPU 分项不代表整机总成本；认证估价 API 未实现 |
| Crusoe | 官网 GPU instances HTML 价格区块 | 排除托管推理价格；询价金额为空；未公布逐地区价格 |
| Lambda | 默认公开实例页；可显式选择旧 API | 公开页无需 key，保留卡数与 GiB / TiB 资源单位；地区未知；可选认证 API 未实测 |
| UCloud | 默认匿名读取官网月卡活动的具体套餐；可显式选择原认证询价 | 公开路径保留月价、配置、活动限制与地区 / 可用区；下线挂牌不证明可购；认证分支未实测 |
| AutoDL | 公开首页普通 / 会员价卡片 | 新的未登录本地浏览器；会员条件单列；不代表逐地区 / 机器报价或实时库存 |
| RunPod | 官方匿名 GraphQL GPU Pods 目录，分开 Secure / Community 费率 | 单卡小时目录价；卡数、实例资源与地区未知；排除禁用云层、空 / 零占位价和 MIG 分区 |
| DigitalOcean | 官方 GPU Droplet 按需 / Spot 计价文档 | 保留单卡 / 八卡实例小时原价及分摊；不推断显存、资源或地区；Spot 可变 |
| Verda | 官方 USD / EUR GPU 实例价目，按需 / Spot 分开 | 每种币种独立读取并核对单位；保留 CPU / RAM，不将地区和库存推断到价格 |
| EBCloud | 官网明确选中的单卡按量 GPU 容器配置 | 多卡、包月 / 包年和试用选项不按默认价格推算；地区与库存未知 |
| Azure | 官方匿名 Retail Prices API，T4 / GB200 两个已核对 GPU VM SKU | 保留地区、明确卡数及实例分摊；不是 Azure 全部 GPU SKU 或当前容量查询 |
| Suanli | 官网明示云主机 / 弹性部署共用的 GPU 卡时费率 | 保留 CNY / GPU / 小时及产品范围；GPU 数和整机资源未知；排除 NPU 和未核实加速卡 |

官方核查链接见 [平台说明](PROVIDERS.md)。11 个公开来源不需要登录、API key、充值、绑卡或租用 GPU 资源；AutoDL 需要可选 Playwright 和本地 Chromium，其余 10 个 HTTP 来源使用基础依赖。全局默认仍为 Nebius / Crusoe；`--providers all` 或 `configs/collect.all.example.json` 显式选择全部来源，免费三家示例配置继续保留 Lambda / AutoDL / UCloud。

## 使用路径

Python API `collect_prices(providers, filters, settings=..., include_coverage=True)` 返回可 JSON 序列化的字典；`collect` CLI 将相同类型结果写到 stdout，日志写 stderr。完整公开路径可直接运行：

```bash
gpu-price-monitor collect --providers all --coverage \
  --lambda-source public --ucloud-source public --pretty
```

```python
from gpu_price_monitor import collect_prices, Settings

result = collect_prices(
    providers="all",
    settings=Settings(lambda_source="public", ucloud_source="public"),
    include_coverage=True,
)
```

```text
调用方 env / 来源 / 筛选
→ 配置检查
→ 官方来源请求与解析
→ 筛选、时间和单位校验
→ prices + 每来源状态 / 筛选反馈 / 错误 + 可选型号覆盖报告
→ 调用方自行处理
```

结果包含 `schema_version=1`、`status`、UTC `collected_at`、`prices` 和 `provider_results`；启用后另含 `coverage`。全部成功、部分失败、全部失败分别表达；无匹配不等于请求失败。CLI 返回码用于进程编排，详细情况通过每来源结果核对。见 [接入说明](DEPLOYMENT.md) 和 [数据口径](DATA_MODEL.md)。

## 型号覆盖与缺口

`MAINSTREAM_GPU_MODELS` 固定保留 34 项目标：NVIDIA H100 / H200 / B200 / B300 / GB200 / GB300 / GH200 / A100 / A800 / H800 / H20 / L20 / L40 / L40S / L4 / A40 / A10 / T4 / V100，RTX 5090 / 4090 / 4090D / 3090 / 3080 Ti / 2080 Ti / PRO 6000 / 6000 Ada / A6000 / A5000 / A4000，以及 AMD MI300X / MI325X / MI350X / MI355X。

`gpu_family()` 仅为覆盖归类：H100 的 SXM / PCIe / NVL 可归到同系列，GB200 与 B200、4090D 与 4090 保持独立，T4S 不推断成 T4。原始型号、显存、变体与报价保持不变，系列有报价不表示所有变体都有相同价格。

`report_coverage(result, models=None)` 可独立处理已有结果。`scope=returned_quotes` 表明它统计调用方筛选后实际返回的报价；目标项保留 `priced`、`unavailable_listings_only`、`contact_sales_only`、`not_found`，额外型号放入 `extra_models`。每项给出数量、来源、原币种 / 单位及 `quote_indices`，供调用方定位原始条件。未知库存的数字挂牌可记为 `priced`，不能解释为可下单；失败来源不贡献覆盖，缺失采集元数据保持未知。

覆盖报告不计算最低价、均价或汇率，不通过删除缺失目标达到“全部覆盖”。本次覆盖和真实 JSON 见 [综合采样说明](../examples/README.md)，它不承诺全世界所有平台、地区、资源变体和即时库存。

## 地区与筛选

GPU 型号、币种和计费方式按来源记录筛选。Nebius 地区条件可核对，UCloud 公开套餐根据官方地区 / 可用区关联筛选，认证询价根据请求 target 筛选；Azure 使用零售价格记录中的明确地区。其他当前公开来源无可直接关联的独立地区价依据，请求地区时返回结构化错误；仅可选 Lambda API 提供的容量地区也不等于价格地区。

卡数筛选支持 Lambda / UCloud / DigitalOcean / Verda / EBCloud / Azure；RunPod、AutoDL 和 Suanli 的公开单卡费率不代表已知实例卡数。可用区筛选当前仅 UCloud 支持；所有来源都不从地区名猜测国家映射。

来源未知地区保留未知值，不能由币种、网页语言、IP 或地区库存推断价格范围。后续接入 API / 授权网页时，显式传入地区和完整配置，并核对实际返回或选中条件。

配置支持字段与来源实际支持能力分别校验；不能因字段格式合法就静默忽略无法应用的筛选。原始请求、实际应用情况和失败原因需要能由调用方获知。

## 价格口径

保留原始十进制金额、币种、单位、计费方式、资源包含项和优惠条件，以及来源、采集时间和生效日期。确定报价、起价、需询价、不可用和采集失败分别处理，不用零元表示失败。

GPU 分项不代表整实例成本。Lambda 公开页为挂牌每卡小时价，整实例价是乘以明确卡数的派生值；DigitalOcean、Verda、Azure 和可选 Lambda API / UCloud 认证报价则将整实例原价按明确卡数分摊。EBCloud 为明确选中的单卡容器配置，不冒充虚拟机。RunPod 和 Suanli 返回每卡小时费率，整机资源或卡数未知时不推导整实例总价。

UCloud 公开月卡保留 `gpu_month`，不换算成小时；保留活动限制与下线标记。AutoDL 普通价和会员价保留独立身份与资格条件，不混成同一报价。Verda 的 USD / EUR 为独立公布报价，不是本库换汇。Suanli 保留云主机 / 弹性部署共享卡时定价范围。卡数、周期和配置不充分时，不假设每月小时数或补造资源。跨币种换算、历史去重和涨跌比较由调用方执行。返回值不混入旧缓存；采样 Spot 价格不代表全天最低值。

## 后续顺序

1. 通过全来源真实采样和 34 项覆盖报告持续核对型号缺口、价格身份与原始条件，保留额外型号。
2. 完善公开来源解析样本、浏览器错误、网站改版兼容和安装包；普通 CI 不依赖外网。
3. 依据官方 GPU 规格扩展 Azure 其他 SKU、逐地区价及更多明确可核对的配置 / 计费方式。
4. 如需账号报价，再单独验证可选认证分支或 AutoDL 市场逐机器报价；当前免费型号覆盖不依赖账号联调。
5. 按来源证据扩展 UCloud 可售发现和国家映射，保持库存、资格与挂牌分别表达。

未实现来源不接收成“成功但没有价格”，不使用示例结果冒充实时价格。所有认证联调仅使用只读接口，不创建或购买实例。

## 验收

- 使用者无需 Flatkey 服务、账号或付款即可运行公开采集路径。
- JSON 可供其他程序消费；部分失败仍保留成功报价并给出错误。
- 价格、单位、资源分项、生效时间和范围可追溯到官方来源。
- 已支持筛选确实应用；未知地区和不支持条件不伪造。
- 34 项覆盖清单保留缺口和原报价索引，不把不可用挂牌、系列归类或未知库存等同于全市场可购买。
- 解析器通过脱敏离线样本验证；在线核查记录真实来源、时间、筛选和数量。
- 凭据不进入返回或日志；配置检查不联网。

调用频率、上传与存储由使用者决定，本库不承诺固定采集时刻或托管服务。
