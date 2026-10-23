# 原始五家价格入口与采集范围

核对日期：2026-10-23，版本：0.22.0。原始《GPU云算力_价格入口与API核查_2026-10-10.docx》指定 **Nebius、Lambda、Crusoe、AutoDL、UCloud**。验收范围是官网公开，以及调用者当前账号登录后能够读取的 GPU 小时报价。不包括未公布的销售合同价，也不通过创建云资源来取得价格。

所有金额由独立 Python 程序读取官方接口或按固定规则解析官网。运行时不调用 Codex / LLM。库负责采集、校验和返回 JSON / CSV；定时、私有凭据存储、换汇、历史数据、上传与网站发布由调用方负责。

## 五家实际来源

| 平台 | 入口与程序来源 | 本轮核对与边界 |
| --- | --- | --- |
| Nebius | [AI Cloud pricing](https://nebius.com/prices)：官网 JSON 普通目录、地区 Spot API；`catalog_api` 登录后读取已有项目、平台和 presets，逐项调用 EstimateBatch | 公开目录与账号配置报价分开保留；账号估价有真实请求地区，不把官网目录价复制到各地区。计算费为零但磁盘有价的配置不当作免费 GPU。报价不证明库存 |
| Lambda | [AI cloud pricing](https://lambda.ai/service/gpu-cloud)：`visible` 同时读取公开页和登录控制台目录 | 本轮公开 28 条、账号 36 条小时价均保留，合计是 64 条来源记录，不是去重 SKU。只有官方证实的可选地区 / 共享目录适用位置进入严格主表；官网无地区或当前无可选地区的记录仍保留原价 |
| Crusoe | [GPU instances pricing](https://www.crusoe.ai/cloud/pricing)：按固定规则读取 GPU instances 区块 | 本轮 7 个数值价、17 个 Contact sales 单元格。后者不是漏抓的数值价。已查看账号规格接口但没有价格字段；无配额和付款资料导致不可进入的资源配置不扩展为私人合同采集 |
| AutoDL | [算力市场](https://www.autodl.com/market/list)：`market` 读取自己的登录会话并调用市场 JSON 接口 | 本轮 3,383/3,383 条市场记录对账，3,290 个 GPU 资源的普通 / 会员两档价共 6,580 条。30 型号、17 地区代码；其中 3,372 条国家地区证据完整。其余有原始地区名称但国家未核实，不猜国家。已租完仍有展示价，不等于下线 |
| UCloud UHost | [GPU 配置报价](https://console.ucloud.cn/uhost/uhost/gpu_create)：`console` 读取官方地区、可用区、GPU / CPU / 内存 / 镜像目录，再逐个调用小时询价 | 本轮 758 个基础硬件配置都有真实报价，22 型号、11 地区、13 可用区、5 国家代码。默认不核查库存。8 个当前页面范围排除项单列；不宣称包含所有磁盘、网络增强、Spot、套餐和私人折扣组合。UHost 不与 CompShare 混用 |

UCloud 的 A800/H20 少卡配置原先因网络模式错误漏价，0.22.0 已按当前官网组件修复。新加坡 P40 的空网络选项按官网默认普通网络处理。A800 一卡、16 CPU、128 GiB、乌兰察布 A、Ubuntu 22.04 预装 NVIDIA 595.58.03/CUDA 13.2、40 GB RSSD、无数据盘及外网 IP，在官网和 API 均为 **28.83 CNY/实例小时**；一卡时等于每 GPU 小时。此为 2026-10-23 的核查证据，不是固定价或运行时默认值。

## 国家地区与计费口径

- 地区报价必须有同一来源的实际请求位置或明确适用位置，不能用厂商覆盖区域补报价地区。
- 官网只给一个金额，并不证明全国或全球统一价。只有官方明确说明共享价格及适用地区，才能作相应展示。
- Lambda 的标准 SKU 共享目录证据只适用于其明确列出的可选地区；容量字段本身不证明地区价格。
- AutoDL 的未知国家不按地区代码前缀、公司地址、币种或 IP 猜测。
- 全部返回原币，小时价不由月价除以 720 得出。整机价按来源明确的 GPU 数分摊，同时保留 CPU、内存、磁盘等计费范围。
- Nebius 账号计算报价与磁盘估价分开；UCloud 报价含明确的基础系统盘。这些配置条件必须随价格保留。

## 输出与验收

`collect_prices()` / CLI 返回价格和逐来源状态。`prices_to_csv()` 由库本身输出英中双语表头；默认 `market` 为 10 列小时表，`compact` 为严格地区小时表，`catalog` 保留来源目录信息，`full` 用于详细审计。Lambda `visible` 的 `market` 同样要求已证实的位置或适用地区。

“有报价”“当前有库存”“地区已核实”和“全部配置覆盖”是不同状态，不能用一个总行数替代。所有报价保留自己的采集时间；合并同一天的不同实采批次不重写旧记录时间，也不冒充一次全新抓取。

公开来源样例：

```bash
cp .env.five.example .env.five.local
gpu-price-monitor collect --env-file .env.five.local --pretty > prices.json
gpu-price-monitor collect --env-file .env.five.local --format csv > prices.csv
```

登录后来源需显式配置：参见 [Lambda](lambda-console.md)、[Nebius / Crusoe](nebius-crusoe.md)、[AutoDL](autodl-market.md) 和 [UCloud](ucloud-console.md)。选中的登录态失败会报告错误，不悄悄切换到公开页、另一产品线或历史价格。

## 定时任务边界

服务器 / CI 可以使用相同 Python 程序和有效私有凭据运行，不需要个人电脑保持开机。但本地保存的 Cookie 不会自动进入云端；登录态采集接入、续期与失败告警必须由调用方部署。当前库复用导出会话，没有验证码自动登录或永久 Cookie 保证。Nebius 的短期 token 需要调用方续期或配置官方服务账号机制。详见[部署说明](DEPLOYMENT.md)。

[历史 examples](../examples/README.md)只是对应日期的审计样例，不作为现价或运行时回退。RunPod、DigitalOcean、Verda、Azure 可额外选择，但不属于本页五家验收范围。
