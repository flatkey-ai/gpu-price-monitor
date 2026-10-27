# UCloud：无需浏览器会话的定时抓价

完整目录模式使用官方 `PublicKey` / `PrivateKey` 签名请求，不读取 Cookie、浏览器配置或历史配置目录，不创建云资源。普通 API 密钥与网页登录会话是两套认证；采集无需人为刷新网页登录。

## 已接好的调用链

| 步骤 | 官方接口 | 本程序用途 |
| --- | --- | --- |
| 1 | `GetRegion` | 每次重新取得账号能看到的地域和可用区对应关系。 |
| 2 | 官网匿名 `ListAllRegions` / `ListAllZones` | 仅补充官方国家代码、地域和可用区名称；必须与步骤 1 的地域—可用区精确匹配，不按代码前缀推断国家。 |
| 3 | `DescribeAvailableInstanceTypes` | 对步骤 1 的每个精确地域分别读取完整配置响应，枚举 GPU 型号、卡数、CPU、内存、CPU 平台、磁盘范围和网络特性。没有固定 GPU 型号白名单。 |
| 4 | `DescribeImage` | 按地域读取基础 Linux 镜像，必要时读取明确支持该 GPU 的市场镜像；使用 `Offset` / `Limit` 分页，并校验 `TotalCount` 和重复 ID。 |
| 5 | `GetUHostInstancePrice` | 对每个目录配置、精确地域和可用区、兼容镜像及最小启动盘独立询价；使用 `Dynamic` 小时计费、单实例。 |

每 GPU 小时价格为该实例小时总价除以 GPU 数量。CPU、内存和基准启动盘均计入。市场镜像许可费、额外磁盘、网络、带宽、合同价、包月包年和 Spot 不属于这个基准目录，不能以普通按需价格替代。

没有配置的售罄行无法询价。签名目录已有精确地域—可用区，但独立官方国家目录缺少对应项时，仍对原地域询价并保留数字报价，国家为 null、`compute_countries=[]`，同时记录 `country_not_verified`；严格国家地区 CSV 可排除这类行。无权读取地域、分页不完整、没有兼容镜像或询价失败会明确记录缺口。不会拿其他地区的金额补齐，也不会把旧配置目录说成当前完整目录。

## 运行配置

```dotenv
UCLOUD_SOURCE=api
UCLOUD_PUBLIC_KEY=<仅存本地私有文件或 GitHub Secret>
UCLOUD_PRIVATE_KEY=<仅存本地私有文件或 GitHub Secret>
UCLOUD_PROJECT_ID=<已授权项目，子用户必须明确配置>
UCLOUD_CHECK_AVAILABILITY=false
```

调用时选用 `catalog_scope=complete`。原来的指定配置 API 模式仍用于少量显式目标，不能代表全目录；其 `UCLOUD_PRICE_TARGETS_JSON` / `UCLOUD_PRICE_TARGETS_FILE` 在完整目录模式中不需要。

最小运行示例：

```python
from datetime import datetime, timezone
from gpu_price_monitor.providers.ucloud_api_catalog import collect_result
from gpu_price_monitor.settings import Settings

settings = Settings.from_env()
result = collect_result(
    settings=settings,
    observed_at=datetime.now(timezone.utc).isoformat(),
)
```

## 最小授权建议

使用专用子用户和已授权的目标项目，不使用管理员密钥。需允许的只读 API：

- `GetRegion`
- `DescribeAvailableInstanceTypes`
- `DescribeImage`
- `GetUHostInstancePrice`

项目 ID 已明确提供时，不必授权 `GetProjectList`。不需要 `CreateUHostInstance`、`DeleteUHostInstance`、账户管理、充值或其他资源修改权限。具体 IAM 策略的项目级／全局级及资源表达式应按 UCloud 当前控制台生成并核验；这里不伪造可直接部署的策略 JSON。

本次真实账号中，未绑定任何策略的专用 API 子用户已经能签名读取 `GetRegion`，无需额外地区权限。其余三个查询动作通过控制台生成的**项目级**策略授权，并仅绑定一个指定项目；没有选择“全部项目”，也没有添加全局或管理员策略。策略中的资源 `*` 受该项目级绑定约束，不能据此把它改成全局授权。该行为是本次账号实测结果，其他账号仍须逐项验证。

官方说明子用户可持有独立 API 密钥，权限继承该子用户，并支持禁用或删除密钥。已查到的文档未承诺普通密钥的固定过期天数，因此不能承诺“永久有效”；密钥禁用、删除、轮换、账号冻结、项目权限或 API IP 限制变化仍可能使采集失败。程序应上报认证和权限错误，不能改回旧价并标成新采集。

UCloud 还提供可自定义有效期的 STS `AssumeRole`。它仍需要一个获授权的主体自动换取令牌，并非完全没有长期信任根；本实现没有声称支持 STS，也没有请求新增角色权限。当前最直接的无人值守方案是专用子用户的受限密钥。

新建密钥、子用户或修改权限属于持久授权变化，必须在最终操作前单独确认。不要把密钥发到聊天、提交代码或打印进日志。

## 验证范围

已通过合成官方响应结构测试：逐地域发现、逐可用区不同价格、新增型号自动出现、完整镜像分页、权限拒绝、询价失败、未知地区及跨地区响应拒绝、认证值不出现在输出中、资源创建动作拒绝。现有控制台目录与镜像投影测试同时通过。

2026-10-27 已创建专用 API 子用户，关闭控制台登录，并完成指定项目的三项查询授权。四个签名读取动作均通过真实请求，完整配置基准目录一次采集耗时 **196.2 秒**：

- `GetRegion` 返回 27 个地域、34 组地域—可用区，27 个地域的配置请求均成功。
- 158 条原始目录行含 63 条 GPU 行；生成 758 个精确配置目标，758 个均返回并通过小时价格校验，没有报价缺口。
- 数字报价覆盖 22 个 GPU 型号、11 个地域、13 个可用区；其中 T4 有 18 条报价。例如本次 `cn-bj2-05` 的单卡 T4、4 vCPU、8 GB 内存、20 GB SSD 基准配置为 CNY 4.94／实例小时。这是本次观察值，不是固定价格。
- 签名请求计数：地区 1 次、配置 27 次、镜像 12 次、询价 758 次；配置目录每次重新发现，没有读取历史目录替代。
- 官方独立国家目录缺少 `hk-01` 和 `cn-bj2-04` 两个对应项，保留 `country_not_verified` 审计缺口，因此结果状态为 `partial`；这两个目录项没有造成数字报价缺失。
- 另有 5 条售罄目录行未提供可报价配置，保留排除原因。未据名称猜造 GPU 数量、配置或价格。

授权前的规格／镜像请求曾返回官方 `RetCode=299`（没有 `Action` 字段），已增加安全错误解析和回归；成功响应仍要求精确 `Action`。专用密钥和目标项目已安全写入获授权的云端采集 Secrets；云端定时任务及网站导入还应另查执行结果，不能用本地成功代替云端验收。

## 官方依据

- [API 快速开始与签名认证](https://docs.ucloud.cn/api/summary/public)
- [获取地域和可用区列表 GetRegion](https://docs.ucloud.cn/api/uaccount-api/get_region)
- [配置目录 DescribeAvailableInstanceTypes（官方文档仓库）](https://github.com/UCloudDoc-Team/api/blob/master/uhost-api/describe_available_instance_types.md)
- [镜像目录 DescribeImage](https://docs.ucloud.cn/api/uhost-api/describe_image)
- [配置询价 GetUHostInstancePrice](https://docs.ucloud.cn/api/uhost-api/get_uhost_instance_price)
- [子用户独立 API 密钥和权限](https://docs.ucloud.cn/register/subaccount)
- [IAM 策略文档](https://docs.ucloud.cn/uproject/mdToPdf/uproject.pdf)
- [STS 与临时授权](https://docs.ucloud.cn/uproject/sts)
- [官方 Python SDK 认证方式](https://docs.ucloud.cn/opensdk-python/quickstart)
- [官方 UAPI 密钥入口](https://console.ucloud.cn/uapi/apikey)

UAPI 密钥入口来自官方 SDK 文档链接；具体页面可能跳转到当前控制台的账号密钥页面。
