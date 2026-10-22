# Lambda 免费登录态采集

`LAMBDA_SOURCE=console` 读取已有账号可见的 JSON 目录。2026-10-22 实际登录会话读取成功：24 个实例规格中有 22 个 GPU、2 个 CPU；另有 14 个预留集群配置和 18 条地区元数据。无需创建 API key、绑定支付卡或启动 GPU。本轮是浏览器已有登录会话读取真实接口，再由 Python 固定规则解析；**尚未用新保存的会话完成独立 Python HTTP 联调**，离线测试不能替代这一步。

这些是控制台内部接口，可能变更，不是承诺稳定的公开云 API。采集库只调用下列 GET：

- `https://cloud.lambda.ai/api/internal/dashboard/v1/instance-types`
- `https://cloud.lambda.ai/api/internal/dashboard/v1/cluster-types/reserved`
- `https://cloud.lambda.ai/api/internal/dashboard/v1/regions`

## 本地登录一次

安装 Python 3.11+，在仓库目录执行：

```bash
python -m pip install '.[browser]'
python -m playwright install chromium
cp .env.lambda.example .env.lambda.local
gpu-price-monitor lambda-login --state-file playwright/.auth/lambda.storage-state.json
```

命令会打开全新的浏览器，请自行登录 Lambda。程序不输入密码、不读取个人 Chrome 配置、不操作付款或创建资源。确认实例目录 GET 返回成功后，仅保存 Lambda 域 Cookie，文件权限为 `0600`，不覆盖已有文件。会话文件等同于账号凭据，包含的权限由供应商会话决定；库自身只读不代表 Cookie 本身只有读权限。只在自己授权的账号使用，文件已被 Git 忽略。

已有自己准备的 Playwright storage-state 文件，也可直接设置 `LAMBDA_STORAGE_STATE_PATH`，无须安装浏览器依赖。相对路径以 `.env` 所在目录为准。采集时使用 Python HTTP，不启动浏览器或调用大模型。

## JSON、CSV 和 Python

```bash
gpu-price-monitor collect --env-file .env.lambda.local --pretty > lambda-prices.json
gpu-price-monitor collect --env-file .env.lambda.local --format csv > lambda-prices.csv
gpu-price-monitor collect --env-file .env.lambda.local --format csv --csv-profile full > lambda-audit.csv
```

```python
from gpu_price_monitor import Settings, collect_prices, prices_to_csv

settings = Settings.from_env(env_file=".env.lambda.local")
result = collect_prices(["lambda"], settings=settings)
print(result["status"])
csv_text = prices_to_csv(result)  # UTF-8 BOM，中英双语 10 列
```

会话过期、权限不足或字段变化会明确报错，不换成旧快照或官网价冒充成功。三个目录分别处理，某一项失败时保留其他成功结果；尚有成功价格时状态为 `partial`，仅地区元数据成功而两个价格目录均失败时，价格采集仍为 `failed`。登录失效时，请重新登录并保存到新文件，再更新 env 路径。

## 如何读价格

按需 API 的 `price_cents_per_hour` 是整实例美分小时价：除以 100，再除实例 GPU 数，得到 USD / GPU / 小时。原始 SKU、卡数和整实例价同时保留；空库存不等于下线，也不删除有价配置。

预留集群采用官方前端使用的 `price_cents_per_gpu_hour / 100`。本轮 14 个配置对应 6 个型号/价格档，不能叫作 14 种独立 GPU 费率。接口内旧的集群、节点总价与每 GPU 价存在冲突，较低字段不会代替显示单价，原始值留作审计。按周结算，具体预留期限、账号资格、税费与最终下单条件尚未验证，CSV 会明确提示。

`regions_with_capacity_available`、`regions_available` 仅表明可选容量位置，不是按地区独立询价，也不证明全球同价。保留官方国家/城市描述和 region code 供核对；`regions`、`compute_countries` 仍为空，严格地区筛选会拒绝。没有把同一报价复制成 18 个地区的价格。

公开页与登录目录会有差异：本轮公开页列出 4×B200，账号目录没有该配置；账号目录另外列出两个不同 V100 SKU。各自来源分别保留，不把公开页数据插入接口结果。所有合同折扣、容量预留或最终结算价仍不能宣称已全部获取。

官网对照：[公开价格](https://lambda.ai/pricing)、[1-Click Clusters](https://lambda.ai/1-click-clusters)、[计费说明](https://docs.lambda.ai/public-cloud/billing/)、[公开 API 文档](https://docs.lambda.ai/api/cloud)。
