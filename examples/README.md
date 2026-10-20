# 真实返回示例

[nebius-crusoe-2026-10-15.json](nebius-crusoe-2026-10-15.json) 是 2026-10-15 真实请求官方公开来源得到的采样结果，筛选条件为 USD、按需计费。采样时刻以文件内 UTC `observed_at` / `collected_at` 为准。

共 18 条记录：15 条数值报价、3 条需询价。Nebius 返回 9 条、Crusoe 返回 9 条；数值单位为 USD / GPU / 小时，分项及购买条件以每条记录字段和 `notes` 为准。

这是接口返回样例，不是持续更新价目表，库不会将它作为实时请求的回退数据。请自行运行 `collect` 获取新报价。样例的存储由演示调用方完成，库的 API 不写入该文件或其他价格文件。

原始来源链接保留在记录中；第三方内容使用范围见 [数据说明](../docs/DATA_POLICY.md)。

## 0.6.0 全来源与型号覆盖，2026-10-20

[all-providers-2026-10-20.json](all-providers-2026-10-20.json) 是 0.6.0 全部 11 家已接入公开来源的综合采样：Nebius、Crusoe、Lambda、AutoDL、UCloud、RunPod、DigitalOcean、Verda、EBCloud、Azure 和 Suanli。实际采样时间、成功 / 失败状态及数量以文件内 `collected_at`、`provider_results` 和 `coverage` 为准。

```bash
gpu-price-monitor collect --providers all --coverage \
  --lambda-source public --ucloud-source public --pretty
```

`coverage.models` 保留默认 34 项主流 GPU 系列，分别标明已取得数值挂牌、仅不可用挂牌、仅需询价或未匹配；`coverage.extra_models` 展示目标清单以外的型号。每项 `quote_indices` 对应本文件 `prices` 数组，方便核对具体币种、单位、显存 / 接口变体、会员及其他条件。覆盖报告针对本次返回报价，不声称全市场或实时可购买，也不提供跨币种 / 跨单位最低价。

综合结果可以同时包含 GPU 分项、完整实例按卡分摊、单卡容器和共享算力卡时费率。UCloud 活动月价保持 `gpu_month`，其他小时价保持 `gpu_hour`；原始产品范围、资源和不可用标记不得在使用时丢失。Azure 当前只覆盖明确核对的 T4 / GB200 两个 SKU；其地域价格不代表实时库存。以下历史样例保留原采样的范围和数量，不能用综合采样结果改写。

## Lambda / AutoDL 免费公开采样，2026-10-20

[lambda-autodl-2026-10-20.json](lambda-autodl-2026-10-20.json) 是北京时间 14:55 的历史实抓，共 46 条：Lambda 22 条、AutoDL 24 条（普通 / 会员各 12 条）。会员条件和原始资源单位保留；两家公开价目未提供逐地区 / 逐机器价格或当前库存。它不证明可选认证 API 已完成真实验证。

## UCloud 免费公开月卡，2026-10-20

[ucloud-public-cn-bj2-2026-10-20.json](ucloud-public-cn-bj2-2026-10-20.json) 是北京时间 15:23 通过 CLI 匿名抓取官网公开接口的完整返回。无需密钥或登录，未加载本地 `.env`。

```bash
gpu-price-monitor collect --providers ucloud --ucloud-source public \
  --region cn-bj2 --zone cn-bj2-02 --gpu T4S --gpu-count 1 \
  --billing-mode monthly --currency CNY --pretty
```

来源共返回 358 个具体月卡套餐（活动 10204 / 10216），本次筛出北京2可用区B的 18 条单卡 T4S 配置。独立的 Python API 采集也成功返回全部 358 条，覆盖北京2、上海2、乌兰察布三个地区。

金额为整机套餐月价按卡数分摊后的 `CNY / gpu_month`，保留 CPU、内存、磁盘和带宽，不换算成小时。官方活动接口在该次采样中将所有相关可用区标为下线，返回 `availability=offline`；公开挂牌不能视为当前可购价格。活动资格和限购条件保留在 `promotion` 中，购买资格未经核验。
