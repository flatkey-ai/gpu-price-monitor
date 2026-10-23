# AutoDL 市场小时价格

`AUTODL_SOURCE=market` 直接调用官网使用的只读市场 JSON 接口：
`POST https://www.autodl.com/api/v1/user/machine/list`。
它是官方产品内部接口，需使用自己的有效登录会话，并非有稳定性承诺的开发者 OpenAPI。
运行时只需 Python；不打开浏览器、不调用 Codex / LLM、不创建或租用实例。

## 第一次配置

1. 在平时使用的浏览器登录 <https://www.autodl.com/market/list>。
2. 打开仓库中的 [本地导出页](../examples/autodl-session-export.html)，按页内说明把按钮拖到书签栏，再回到官网市场点击书签。
3. 浏览器下载 `autodl.storage-state.json`，只含该官网的 `localStorage.token`。这个文件留在本机，不上传或提交 Git。将文件权限设为仅本人可读，例如 `chmod 600 /完整路径/autodl.storage-state.json`。
4. 在自己的 `.env` 中填写：

```dotenv
GPU_PRICE_MONITOR_PROVIDERS=autodl
GPU_PRICE_MONITOR_SOURCE_POLICY=api_only
AUTODL_SOURCE=market
AUTODL_STORAGE_STATE_PATH=/完整路径/autodl.storage-state.json
```

导出书签只有本地 Blob 下载，不发送网络请求、不读 Cookie 或账号资料，也不接受协议或购买资源。可直接查看 HTML 中的完整代码。不会读取平时 Chrome 的配置目录、Cookie 数据库或系统钥匙串。不要使用保存了所有 Cookie / localStorage 的完整浏览器快照代替最小文件；采集器会拒绝多余字段。登录会话过期后由本人重新登录并导出。

## Python 与 CLI

```python
from gpu_price_monitor import Settings, collect_prices, prices_to_csv

result = collect_prices(["autodl"], settings=Settings.from_env(env_file=".env"))
csv_text = prices_to_csv(result, profile="compact")
# result / csv_text 交给调用方保存、上传或发布。
```

```bash
python -m gpu_price_monitor --env-file .env collect --providers autodl --autodl-source market --source-policy api_only --pretty
python -m gpu_price_monitor --env-file .env collect --providers autodl --autodl-source market --format csv --csv-profile compact > autodl.csv
```

## 金额、库存与国家

- 只选择 `machine_sku_info[0].type=payg`，不把包日、包周或包月价格除算成小时。
- `normal_user` / `member_user` 分别使用接口明确给出的 `discounted_price`，不根据折扣反推价格。普通档还须与 `current_price` 一致。
- 官方前端将毫元除以 1,000，并显示两位小数。`amount` 与该显示规则一致；`exact_api_hourly_amount` 和 `price_source.native_amount_milli_cny` 保留接口更高精度。例如接口 1.577 元，官网显示 1.58 元。
- 两档均为 CNY / 广告 GPU 槽位 / 小时；每卡 CPU / 内存随报价保留。虚拟 GPU 或组合卡的原始型号不冒充单张物理卡。
- `out_of_stock` 对应官网“已租完”，报价仍保留；它不等于产品下线。是否能即时租用与报价是否有效分别记录。
- 地区代码和名称来自同一条市场记录。公开地区目录只有代码、名称和数据中心，没有原生国家字段；仅为与官方地名表严格对应的 11 个地区身份补中国，保留交叉核对证据。其余地区不按代码前缀、币种、公司或 IP 猜国家。
- `market` CSV 包含有地区但国家可能缺证据的真实小时报价；正式完整国家地区表用 `compact`。全量报价和明确地理缺口保留在 JSON，不把缺口填成全国统一价。
- 精简 CSV 的官方链接优先指向可人工核对的 `pricing_page_url`；JSON 的 `source_url` 仍是实际市场接口地址，价格字段与换算证据均保留。

接口支持有界大页。当前一次请求 5,000 条，最多接收 32 MiB，核对接口总数、条数及唯一资源 ID；若需要继续分页，重复记录或总数变化会报 `market_changed`，不静默拼接成完整目录。

2026-10-22 17:24（北京时间）CLI 的 `api_only` 实采：3,372 条市场记录、3,279 个 GPU 资源、6,558 条双档报价、30 型号、17 地区代码，93 条非 GPU 记录排除。小时报价全部通过协议校验；3,358 条国家地区证据完整，其余 3,200 条仅保留原始报价及地理缺口，所以批次状态为 `partial`，不是登录或价格请求失败。该快照不代表永久现价或所有计费周期。

## 国家信息核查边界

2026-10-23 重新读取了[官方地区目录](https://www.autodl.com/api/v1/region/list)、[公共站点配置](https://www.autodl.com/api/v1/common)及[官方文档的机房附录](https://www.autodl.com/docs/esd_api_doc/#_39)。地区目录仍只有地区代码、名称和数据中心标识，没有国家字段。以下 8 个地区身份仍缺少可把**当前 GPU 部署位置**确定到国家的官方证据，继续保留真实小时价与原始地区名称，不补造国家：

| 地区代码 | 官方地区名称 | 数据中心标识 | 尚不能确定国家的原因 |
| --- | --- | --- | --- |
| `west-B`、`west-C`、`west-D`、`west-E` | 西北B区 | `westDC3` | 附录只列“西北B区”，没有国家或省市位置。 |
| `west-X` | 西北企业区 | `westDC2` | 附录只列“西北企业区”，没有国家或省市位置。 |
| `nm-A1` | A800专区 | `neimengDC2` | 产品专名没有地理位置；附录的“内蒙A区”对应 `neimengDC1`，不能替换成当前的 `neimengDC2`。 |
| `sh-A1` | 摩尔线程专区 | `shanghaiDC1` | 目前未找到官方文档对该专区当前部署国家的明确说明，不能根据标识中的 `shanghai` 推定。 |
| `beijing-C` | V100专区 | `beijingDC3` | 附录写“V100专区（原华南A区）”；历史名称不足以保证当前所在地，也不能根据代码写成北京。 |

[隐私政策](https://www.autodl.com/docs/privacy_policy/)对“在中国的服务”的个人信息存储作出说明，但没有把上述 GPU 专区逐一绑定到中国，不能拿它替代机房位置证据。未找到明确国家时，这些记录保留在 JSON、`market` / `catalog` 输出，`compact` 完整国家地区表继续排除。

市场目录覆盖与地理资料完整度单独统计：`hourly_market_pages_complete=true` 表示本次已核对市场总条数与所有唯一资源 ID；`country_verified_price_count` 表示其中有完整国家证据的报价数。前者不能用来宣称后者完整，也不能把无库存解释为未抓到价格。

2026-10-23 10:53:20（北京时间）再次使用独立 Python / HTTP 实采：3,383 / 3,383 条市场记录完成对账，其中 3,290 个 GPU 资源、6,580 条普通 / 会员小时报价，0 个小时价校验缺口；国家地区完整的报价为 3,372 条，其余 3,208 条对应上述 8 个缺证据地区。本轮未新增国家映射，也没有把未核实报价混入完整国家地区 CSV。
