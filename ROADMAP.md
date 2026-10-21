# 实现状态与验证清单

更新：2026-10-21，版本 0.9.0。当前采集范围为 **Nebius、Lambda、Crusoe、AutoDL、UCloud、RunPod、DigitalOcean、Verda、Azure** 九家。保留原 Word 五家并按用户要求扩展四家，`--providers all` 运行九家；旧日期样本保留当时范围，不代表当前全市场支持。详细口径见 [需求对照](docs/DOCUMENT_COVERAGE.md) 和 [平台说明](docs/PROVIDERS.md)。

## 已实现并真实公开采样

- [x] Python `collect_prices`、默认兼容 JSON CLI、配置校验、逐来源错误与部分成功状态。
- [x] 0.9.0 新增标准库 CSV 文本导出：Python `prices_to_csv(result)` / CLI `collect --format csv`，UTF-8 BOM / CRLF，保留原币、周期、地区 scope、会员 / Spot / 下线及来源时间；文件写入、换汇和上传由调用者负责。CSV 仅报价，完整状态与 coverage 仍看 JSON。
- [x] 源码 clone 安装、显式 `.env`、进程优先及 FILE / JSON targets，默认无需凭据。
- [x] Nebius Compute 公开价目：GPU / CPU / RAM 分项、USD / ILS、按需 / Spot、生效日期与平台覆盖标记。
- [x] Lambda 公开实例页：单卡展示价、1 / 2 / 4 / 8 卡配置及原资源单位。
- [x] Crusoe GPU instances：隔离托管推理区块，区分按需 / Spot、起价及 Contact sales。
- [x] AutoDL 公开首页：普通 / 会员分别返回，保留会员折扣与资格要求，不猜位置。
- [x] UCloud 匿名具体月包：活动配置、原价 / 限购 / 下线标记、官方国家 / 地区 / zone 关联；国家筛选已开放。
- [x] RunPod 匿名 GPU Pods 目录：Secure / Community 档位分开，忽略未报价 / 禁用与分区 GPU，不推断地区。
- [x] DigitalOcean 官方按需 / Spot 表：完整实例按明确卡数分摊，B300 Spot 独立标注。
- [x] Verda USD / EUR 原币表：GPU instances 与 JSON-LD 共同核验实例单位、卡数及按需 / Spot，不推断地区。
- [x] Azure 官方匿名 Retail Prices：当前四固定 GPU SKU（T4 / GB200 / H100 NVL / A100 PCIe），连续分页、已生效基础 VM 地区按需 / Spot 费率，国家只用官方目录已核验映射，未知为空。
- [x] 联合位置筛选与 `price_scope` / `geographic_coverage`，区分未知目录、平台覆盖与真实位置绑定。
- [x] 保留原币种 / 周期 / 配置；无自动换汇、720 小时折算或旧报价兜底。

**2026-10-21 15:12:56（北京时间）九家公开实抓成功，共 833 条**：Nebius 36、Crusoe 24、Lambda 22、UCloud 374、AutoDL 24、RunPod 68、DigitalOcean 19、Verda 52、Azure 214。574 条有已核验国家关联，588 条有价格地区 / 可用区，其中 UCloud 374 条全部下线；36 条仅平台覆盖，209 条未定位目录。Azure 214 条覆盖 45 个价格地区，其中 14 条国家未知。以上不是全地域可购库存。 证据：[2026-10-21 JSON](examples/nine-providers-2026-10-21.json)。原 [五家历史采样](examples/five-providers-2026-10-21.json) 为 480 条，其中 374 条 UCloud 中国月包下线，36 条 Nebius 仅平台覆盖，70 条未定位；不能等同于当前九家全量或可购地区报价。

## 已实现，尚缺成功账号验证

- [x] Nebius `api`：只读核验项目地区、官方国家 / 平台 / 预设映射、完整配置 Estimate Batch、小时 / 月聚合、账号合同口径、分项与总价核对；14 项合成测试。
- [x] Lambda `api`：整机美分与 GPU 数分摊，容量地区保持独立；离线样本验证，不生成逐地区价。
- [x] UCloud `api`：客户端签名、完整单台 GPU 主机 Dynamic 目标、位置目录核验、整实例价分摊和折前价 / 明细；离线样本验证。
- [x] AutoDL `market`：授权 storage state、只读按量市场分页、可见价格 / 单位与地区 / 配置核对、会话失效报错；8 项合成测试。
- [ ] 使用有效 Nebius 账号执行最小成功估价，确认真实配置、聚合单位与账号条件。
- [ ] 使用有效 Lambda API key 执行成功目录查询，复核实际字段，不把容量当地区价。
- [ ] 使用有效 UCloud 公私钥执行成功配置询价，复核实际价、折扣、位置和配置。
- [ ] 使用有效 AutoDL 授权会话成功采集市场，复核真实 DOM / 分页、地区、普通 / 会员显示与单位。

以上未完成项需要调用者已授权的有效凭据，不以购买或创建 GPU 资源作为验收手段。测试夹具和官方文档示例不算真实账号成功记录。

## 明确边界

- Crusoe 暂无已确认的公共 VM 全价格 API；规格、账单与托管模型接口不能代替。
- AutoDL 已有实例 / 弹性部署 API 不等于全市场；当前不接入这些既有资源接口，也不保存 SSH 信息。
- 不承诺九家全国家、全配置、库存或结算资格；未知位置不补成 global，未知金额不补 0。
- 定时、存储、上传、美元换算、比价和发布由调用方实现；RackRate 的应用流程不属于本库路线范围。

运行验证：`python -m unittest discover -s tests -v`；来源变化后需再次实抓并保留观察时间与原始单位。历史样本说明见 [examples](examples/README.md)。
