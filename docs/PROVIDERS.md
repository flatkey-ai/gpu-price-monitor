# 平台能力与官方依据

文档核查日期：2026-10-20。Nebius / Crusoe 和 Lambda / AutoDL 公开来源已有实际采样；可选 Lambda API / UCloud 认证分支仅有离线样本验证，没有成功的真实认证报价记录。公开页面读取无需充值、绑卡或购买 GPU 资源。

## Lambda：默认免费公开页，可选认证 API

- 默认 `LAMBDA_SOURCE=public`，来源 [官方实例页](https://lambda.ai/instances)。不使用 API key；即使调用方已有 key，也不会自动发认证请求。
- 2026-10-20 公开页采样得到 4 张规格表、22 条价格，分别覆盖 8 / 4 / 2 / 1 卡实例。该数量仅描述一次采样，后续来源内容可能变化。
- 公开 `amount` 为挂牌 USD / GPU / 小时，`price_basis=advertised_per_gpu`、`account_scope=public_catalog`。`instance_price` 是单卡价乘卡数推导的实例价，不是独立来源报价。
- 保留 CPU、内存 GiB、磁盘 GiB / TiB 单位。国家、地区和可用区未在价格表明确，保持未知；挂牌不证明库存或可下单。
- 可用 `collect --lambda-source api` 或环境变量 `LAMBDA_SOURCE=api` 显式选择旧目录 API，才要求 `LAMBDA_API_KEY`。API 为 `GET https://cloud.lambda.ai/api/v1/instance-types`。
- API `price_cents_per_hour` 为整实例每小时美分价，除以 100 保存原价，再按 `specs.gpus` 分摊。`account_scope=authenticated_catalog`；该认证模式尚未完成真实账号联调。
- API `capacity_regions` 仅表达容量，不变成报价 `regions`；两种模式均不支持按地区、国家或可用区查询独立价格。
- [实例价格页](https://lambda.ai/instances) · [官方 API](https://docs.lambda.ai/api/cloud#listInstanceTypes) · [OpenAPI](https://docs.lambda.ai/api/cloud/spec.json)

## Nebius：公开文档已实现

- 使用公开 Compute 计价 Markdown，保留 GPU / CPU / RAM 分项、地区范围、币种和生效日期；当前无需 token。
- `POST https://api.nebius.cloud/billing/v1/calculator/estimate-batch` 是独立的认证配置估价分支，尚未实现，不能当成枚举所有价格的接口。
- 分项价格不能直接代表整机成本。Spot 的“From”是起价，采样不代表全天最低价。
- 地区可按明确来源范围筛选；信息不足时返回 `unverifiable_filter`。国家、可用区和实例卡数不能猜测。
- [Compute 计价](https://docs.nebius.com/compute/resources/pricing) · [估价 API](https://docs.nebius.com/rest-api/billing/v1/calculator/estimate-batch) · [价格页](https://nebius.com/prices)

## Crusoe：公开页面已实现

- 解析官网 GPU instances 区块，排除同页托管推理。无需账号凭据。
- Contact sales 金额为空；挂牌或起价不独立证明有库存或可自助购买，相关承诺与购买条件保留在说明中。
- 公开 VM 规格 / 容量接口不是当前公开价格目录。Billing 的单价也不能自动等同公共挂牌价。
- 当前来源未给逐地区价格，因此地区、国家、可用区、卡数筛选不可验证，不静默忽略。
- [价格页](https://www.crusoe.ai/cloud/pricing) · [API 文档](https://docs.crusoecloud.com/api/) · [OpenAPI](https://api.crusoecloud.com/v1/openapi.json) · [购买条件说明](https://support.crusoecloud.com/hc/en-us/articles/51755978765467-GPU-Quota-vs-Capacity-Understanding-On-Demand-and-Reserved-Instances-RIPA)

## UCloud：显式配置询价已实现，待真实联调

- 只调用 `GetUHostInstancePrice`。使用 `UCLOUD_PUBLIC_KEY` / `UCLOUD_PRIVATE_KEY` 签名认证，以及二选一的 `UCLOUD_PRICE_TARGETS_JSON` / `UCLOUD_PRICE_TARGETS_FILE`；可选 `UCLOUD_PROJECT_ID` 指定项目，子账号可能需要。
- 目标为最多 20 项的完整配置数组。必填 Region、Zone、MachineType=G、GpuType、GPU、CPU、Memory（MB）和 Disks（Size，单位 GB / Type / IsBoot）。只支持完整 GPU 实例、`ChargeType=Dynamic`、`Count=1`，不支持共享分片、裸金属、购买操作或 `Action` 覆盖。
- 当前不自动调用可售规格发现；[目标示例](../configs/ucloud-targets.example.json)不是已验证的可售配置。后续可接 `DescribeAvailableInstanceTypes` 辅助确认，仍须使用者在真实账号下验证。
- 业务成功必须校验 `RetCode=0`，HTTP 200 不足以表示报价成功。Price 为 CNY 整实例成本，按 GPU 数量分摊到 `amount`，保留 `instance_price` 和请求资源。
- `account_scope=account_quote`；是否含账号折扣和可否公开需由使用者确认。地区 / 可用区来自请求，响应不回显，不能当作独立核验或有库存证明。
- 支持按目标 / 结果本地筛选地区、可用区、卡数、GPU、币种、计费方式；国家无可靠映射。凭据缺失、目标缺失和无效分别返回 `missing_credentials`、`missing_price_targets`、`invalid_price_targets`。
- [规格查询](https://docs.ucloud.cn/api/uhost-api/describe_available_instance_types) · [询价文档](https://docs.ucloud.cn/api/uhost-api/get_uhost_instance_price) · [官方文档源文件](https://github.com/UCloudDoc-Team/api/blob/master/uhost-api/get_uhost_instance_price.md)

## AutoDL：免费公开首页普通 / 会员价

- 2026-10-20 北京时间 14:55 的完整 Python / CLI 采集成功返回 12 条普通价和 12 条会员价，与 Lambda 22 条共同构成 [46 条公开采样示例](../examples/lambda-autodl-2026-10-20.json)。数量仅描述该次采样，不代表库存。
- 来源为 [公开首页](https://www.autodl.com/home) 的“炼丹会员及租用价格”卡片，页面由 JavaScript 渲染。需可选 Playwright 及本地 Chromium，不需要登录、充值或绑卡。
- 在新的未登录浏览器上下文中依次读取“普通用户”和“炼丹会员”标签；不使用 `AUTODL_TOKEN`、保存的 storage state 或用户 Cookie。
- 每个 GPU 返回 ordinary / member 两种 `pricing_tier`，会员条目带 `membership_required=true` 和显示折扣 `membership_discount`。会员优惠条件保留，未购买或核验会员资格。
- 金额为公开 CNY / GPU / 小时挂牌，`account_scope=public_catalog`、`source_type=public_page`。首页未给实例卡数、机房、国家、可用区或 CPU / 内存 / 磁盘配置，均不猜测。
- 不支持地区、国家、可用区和卡数筛选；这些卡片不等于逐地区市场报价或实时库存。两标签结构、型号集合或显示折扣发生无法解释的变化时采集失败，不静默输出未验证价格。
- 市场页面的逐机器 / 地区报价另需联调；Pro / 弹性部署的已有资源 API 也不等于完整市场目录。当前免费路径不调用这些账号接口。
- [公开首页](https://www.autodl.com/home) · [市场](https://www.autodl.com/market/list) · [计费说明](https://www.autodl.com/docs/price/) · [Pro API](https://www.autodl.com/docs/instance_pro_api/) · [弹性部署 API](https://www.autodl.com/docs/esd_api_doc/)
