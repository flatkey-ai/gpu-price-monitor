# 平台能力与官方依据

文档核查日期：2026-10-15。未使用账号凭据成功询价，未创建、启动或购买资源。下列是接入依据，不是已运行采集器清单。

## Lambda

- 主源：`GET https://cloud.lambda.ai/api/v1/instance-types`，API key，推荐 Bearer。
- `price_cents_per_hour` 是实例总价（美分 / 小时），除以 100 和 `specs.gpus` 才得到套餐分摊的美元 / GPU / 小时。
- 接口的一份价格与 `regions_with_capacity_available` 分别表达目录报价和容量。该地区数组不能当作逐地区询价结果。
- 首次接入需将认证目录与公开网页抽样对照，明确报价范围。
- [官方 API](https://docs.lambda.ai/api/cloud#listInstanceTypes) · [OpenAPI](https://docs.lambda.ai/api/cloud/spec.json) · [价格页](https://lambda.ai/pricing)

## Nebius

- 公开 Compute 计价文档优先，保留平台 SKU、地区适用范围、币种及生效日期。
- `POST https://api.nebius.cloud/billing/v1/calculator/estimate-batch` 是指定资源配置估价，需有效认证及配置；不等于枚举全部价格。
- 区分合同价与公开价；核对小时、月等聚合单位。L40S 等 GPU、CPU 和 RAM 分项不能直接当成整机租价。
- Spot 的“From”不是确定现价，日采仅是快照。
- [Compute 计价](https://docs.nebius.com/compute/resources/pricing) · [估价 API](https://docs.nebius.com/rest-api/billing/v1/calculator/estimate-batch) · [价格页](https://nebius.com/prices)

## Crusoe

- 官网 GPU instances 区块作为计划主源。公开 VM 规格与容量接口不能当成当前公开价目表。
- Billing 中出现单价不等于 VM 公共目录价；同页托管推理价格也不能混入。
- Contact sales 留空。官网挂牌价不能独立证明有库存或可以自助购买，购买条件冲突时标记待核查。
- [价格页](https://www.crusoe.ai/cloud/pricing) · [API 文档](https://docs.crusoecloud.com/api/) · [OpenAPI](https://api.crusoecloud.com/v1/openapi.json) · [购买条件说明](https://support.crusoecloud.com/hc/en-us/articles/51755978765467-GPU-Quota-vs-Capacity-Understanding-On-Demand-and-Reserved-Instances-RIPA)

## UCloud

- 先用 `DescribeAvailableInstanceTypes` 发现地域内合法配置，再用 `GetUHostInstancePrice` 询价。
- PublicKey 与客户端签名；建议后续采用官方 SDK。`RetCode=0` 才算业务成功，不能仅检查 HTTP 200。
- 固定 `Count=1`、GPU、CPU、内存、磁盘、计费方式和地区。`Price` 为元；是否账号优惠及如何公开需要联调确认。
- [规格查询](https://docs.ucloud.cn/api/uhost-api/describe_available_instance_types) · [询价文档](https://docs.ucloud.cn/api/uhost-api/get_uhost_instance_price) · [官方文档源文件](https://github.com/UCloudDoc-Team/api/blob/master/uhost-api/get_uhost_instance_price.md)

## AutoDL

- 市场页面为计划主源，登录与筛选稳定性待授权联调。
- Pro snapshot 需要已有 `instance_uuid`；折前、折后价格不能代表全市场，单位需确认。
- 弹性部署 container/list 需要已有 `deployment_uuid`，`price` 文档单位为“元 × 1000”。响应可能包含访问凭据，只提取允许的字段。
- 公网 `POST /api/v1/dev/machine/region/gpu_stock` 返回库存，没有报价；支持价格筛选也不能将其作为价格目录。
- [市场](https://www.autodl.com/market/list) · [计费说明](https://www.autodl.com/docs/price/) · [Pro API](https://www.autodl.com/docs/instance_pro_api/) · [弹性部署 API](https://www.autodl.com/docs/esd_api_doc/)
