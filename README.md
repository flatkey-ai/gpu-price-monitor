# GPU Price Monitor

**竞品算力价格监控** — 按国家、地区、GPU 规格与计费条件追踪云算力租赁价格。

[English](README.en.md) · [完整方案](docs/PLAN.md) · [数据口径](docs/DATA_MODEL.md) · [平台核查](docs/PROVIDERS.md) · [路线图](ROADMAP.md)

## 当前状态

项目初始化阶段，已提供方案、配置示例、配置检查 CLI 和 CI。**尚未实现厂商采集器、价格数据库、看板或通知；每日采集尚未启用，仓库不包含实时价格。**

首期覆盖 Nebius、Lambda、Crusoe、AutoDL 和 UCloud，采用官方 API、公开价格页面及授权浏览器采集相结合的方式。

## 项目目标

- 每日记录报价，保留历史、来源和价格生效日期。
- 将服务国家、地域、可用区与销售国家、币种分开保存。
- 按 GPU 型号、显存、卡数、配置和计费方式筛选，比较口径相近的报价。
- 区分整机价、GPU 分项价、起价、合同价与询价，避免错误排名。
- 提供变化提醒、CSV / JSON 导出和公开价格看板。
- 代码开源；账号凭据、合同报价和私有响应保存在私有环境。

## 首期接入策略

| 平台 | 计划主源 | 关键边界 |
| --- | --- | --- |
| Lambda | 官方实例目录 API | 实例总价需按卡数折算；容量地区不是逐地区报价 |
| Nebius | 官方计价文档；估价 API 补充 | 历史生效价、GPU 分项与整机价分开 |
| Crusoe | 官方 GPU instances 价格区块 | 不混入托管推理；询价项留空 |
| UCloud | 可售规格查询 + 完整配置询价 | 固定地区、卡数、CPU、内存和磁盘 |
| AutoDL | 市场页面；官方 API 辅助 | 已有实例价不等于完整市场目录 |

本表是文档核查后的接入计划，不代表已经完成账号实测。详见 [平台核查](docs/PROVIDERS.md)。

## 本地查看

要求 Python 3.11 或更高版本。初始化 CLI 仅使用标准库，无需安装依赖。

```bash
git clone https://github.com/flatkey-ai/gpu-price-monitor.git
cd gpu-price-monitor
PYTHONPATH=src python3 -m gpu_price_monitor status
PYTHONPATH=src python3 -m gpu_price_monitor validate-config --config configs/monitor.example.json
```

配置中的厂商默认关闭，`targets` 为空。后续实现采集器后，再填入经过验证的地区与规格并启用；此时配置检查通过也不表示已有可运行的采集器。

## 目录

```text
configs/                 监控配置示例
docs/                    方案、数据模型、平台核查、部署和数据发布说明
src/gpu_price_monitor/   初始化 CLI 与配置检查
.github/workflows/       CI，仅检查语法和示例配置
ROADMAP.md               实施阶段与验收标准
```

## 参与开发

请先阅读 [贡献指南](CONTRIBUTING.md)。真实接口联调仅使用只读能力；不创建或购买 GPU 资源来获取报价。提交解析器时提供脱敏样本与价格单位依据。

## 许可证

代码采用 [Apache-2.0](LICENSE)。第三方价格、页面、截图与账号数据的使用及再发布范围另见 [数据说明](docs/DATA_POLICY.md)；代码许可证不扩展第三方内容的权利。
