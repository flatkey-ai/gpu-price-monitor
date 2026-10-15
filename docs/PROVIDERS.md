# 平台能力与官方依据

文档核查日期：2026-10-15。Nebius / Crusoe 已有公开来源实际采样；Lambda / UCloud 适配器已通过离线样本验证，但当前未配置账号凭据，**没有成功的真实认证询价记录**。未创建、启动或购买资源。

## Lambda：已实现，待真实认证联调

- 来源：`GET https://cloud.lambda.ai/api/v1/instance-types`，使用 `LAMBDA_API_KEY` Bearer 认证。
- `price_cents_per_hour` 是整实例每小时美分价；先除以 100 保留 USD `instance_price`，再除以 `specs.gpus` 得到 `amount`，即套餐分摊单卡小时成本。
- `account_scope=authenticated_catalog`。来源需要认证不表示已证实是账号专属折扣，公开发布范围仍需使用者确认。
- `capacity_regions` 来自 `regions_with_capacity_available`，仅表示容量。它不填入价格 `regions`，也不用于逐地区价格筛选；请求地区、国家或可用区返回结构化错误。
- 支持 GPU 型号、GPU 卡数、币种和计费方式本地筛选；保留 CPU、内存、磁盘及架构等目录资源信息。
- 缺少凭据返回 `missing_credentials`。离线样本不能代替账号权限、当前目录价格和 API 限制的真实联调。
- [官方 API](https://docs.lambda.ai/api/cloud#listInstanceTypes) · [OpenAPI](https://docs.lambda.ai/api/cloud/spec.json) · [价格页](https://lambda.ai/pricing)

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

- 只调用 `GetUHostInstancePrice`。使用 `UCLOUD_PUBLIC_KEY` / `UCLOUD_PRIVATE_KEY` 签名认证，以及必填 `UCLOUD_PRICE_TARGETS_JSON`；可选 `UCLOUD_PROJECT_ID` 指定项目，子账号可能需要。
- 目标为最多 20 项的完整配置数组。必填 Region、Zone、MachineType=G、GpuType、GPU、CPU、Memory（MB）和 Disks（Size，单位 GB / Type / IsBoot）。只支持完整 GPU 实例、`ChargeType=Dynamic`、`Count=1`，不支持共享分片、裸金属、购买操作或 `Action` 覆盖。
- 当前不自动调用可售规格发现；[目标示例](../configs/ucloud-targets.example.json)不是已验证的可售配置。后续可接 `DescribeAvailableInstanceTypes` 辅助确认，仍须使用者在真实账号下验证。
- 业务成功必须校验 `RetCode=0`，HTTP 200 不足以表示报价成功。Price 为 CNY 整实例成本，按 GPU 数量分摊到 `amount`，保留 `instance_price` 和请求资源。
- `account_scope=account_quote`；是否含账号折扣和可否公开需由使用者确认。地区 / 可用区来自请求，响应不回显，不能当作独立核验或有库存证明。
- 支持按目标 / 结果本地筛选地区、可用区、卡数、GPU、币种、计费方式；国家无可靠映射。凭据缺失、目标缺失和无效分别返回 `missing_credentials`、`missing_price_targets`、`invalid_price_targets`。
- [规格查询](https://docs.ucloud.cn/api/uhost-api/describe_available_instance_types) · [询价文档](https://docs.ucloud.cn/api/uhost-api/get_uhost_instance_price) · [官方文档源文件](https://github.com/UCloudDoc-Team/api/blob/master/uhost-api/get_uhost_instance_price.md)

## AutoDL：尚未实现

- 当前返回 `not_implemented`。后续以授权市场页面为主，登录与筛选稳定性待联调。
- Pro snapshot 需要已有 `instance_uuid`；折前 / 折后价格不代表全市场，单位需核对。
- 弹性部署 container/list 需要已有 `deployment_uuid`，`price` 文档单位“元 × 1000”；响应可能包含访问凭据，只能提取必要报价字段。
- 公网 `POST /api/v1/dev/machine/region/gpu_stock` 返回库存，没有报价；支持价格筛选也不能当作价格目录。
- [市场](https://www.autodl.com/market/list) · [计费说明](https://www.autodl.com/docs/price/) · [Pro API](https://www.autodl.com/docs/instance_pro_api/) · [弹性部署 API](https://www.autodl.com/docs/esd_api_doc/)
