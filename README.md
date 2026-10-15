# GPU Price Monitor

**GPU 云算力价格采集库**：通过官方 API、公开价格页面和授权浏览器会话获取报价，向调用方返回统一的结构化结果。

[English](README.en.md) · [完整方案](docs/PLAN.md) · [返回数据口径](docs/DATA_MODEL.md) · [平台核查](docs/PROVIDERS.md) · [接入配置](docs/DEPLOYMENT.md) · [路线图](ROADMAP.md)

## 当前状态

项目处于初始化阶段，提供平台核查、配置示例、环境变量读取、配置检查 CLI 和 CI。**厂商采集器及 `collect_prices` / `collect` 接口尚未实现，没有实时价格；当前版本尚未发布到 PyPI。**

首期计划接入 Nebius、Crusoe、Lambda、UCloud 和 AutoDL。配置检查通过仅代表配置合法，不代表相应平台已经支持采集。

## 职责边界

本库负责读取采集配置、访问价格来源、应用或核对筛选条件、校验金额与单位，并返回报价、来源、时间及每个平台的成功或错误状态。

调用方自行实现定时运行、数据库与历史记录、上传、价格比较、换汇、告警和展示。Flatkey 与其他使用者通过各自环境变量配置凭据，使用同一套采集能力；本库不内置 Flatkey 上传地址或业务凭据。

```text
调用方：定时 / 手动触发
               ↓
本库：配置 → API / 网页采集 → 条件校验 → 结构化结果
               ↓
调用方：存储 / 上传 / 比价 / 通知 / 看板
```

## 计划支持的平台

| 平台 | 计划主源 | 关键边界 |
| --- | --- | --- |
| Nebius | 官方计价文档；估价 API 补充 | 保留生效日期；区分 GPU 分项与整机价格 |
| Crusoe | 官方 GPU instances 价格区块 | 询价项不生成金额；购买条件单独返回 |
| Lambda | 官方实例目录 API | 保留实例总价和卡数；容量地区不等于逐地区报价 |
| UCloud | 可售规格查询 + 完整配置询价 | 地区、卡数、CPU、内存、磁盘及计费方式共同确定报价 |
| AutoDL | 授权市场页面；官方 API 辅助 | 核对地区选择；已有实例价格不代表完整市场 |

以上是接入计划，尚未完成账号实测。官方依据见 [平台核查](docs/PROVIDERS.md)。

## 本地查看与配置检查

要求 Python 3.11 或更高版本。当前检查 CLI 仅使用标准库：

```bash
git clone https://github.com/flatkey-ai/gpu-price-monitor.git
cd gpu-price-monitor
PYTHONPATH=src python3 -m gpu_price_monitor status
PYTHONPATH=src python3 -m gpu_price_monitor validate-config --config configs/collect.example.json
```

也可以在本地安装开发版本后使用 `gpu-price-monitor` 命令。安装不代表实时采集能力已完成。

```bash
python3 -m pip install -e .
gpu-price-monitor status
```

`configs/collect.example.json` 仅包含来源、筛选条件和请求选项；所有厂商默认 `enabled=false`。环境变量示例见 [`.env.example`](.env.example)。**当前程序从进程环境读取变量，不自动加载 `.env` 文件**；由调用方、容器或运行器注入。

| 环境变量 | 用途 / 默认值 |
| --- | --- |
| `GPU_PRICE_MONITOR_PROVIDERS` | 以逗号分隔的来源列表；默认 `nebius,crusoe` |
| `GPU_PRICE_MONITOR_TIMEOUT_SECONDS` | 请求超时；默认 `30` 秒 |
| `GPU_PRICE_MONITOR_MAX_RETRIES` | 最大重试次数；默认 `2` |
| `LAMBDA_API_KEY` | Lambda 目录 API 凭据 |
| `NEBIUS_ACCESS_TOKEN` | Nebius 认证估价分支凭据；公开文档采集不需要 |
| `UCLOUD_PUBLIC_KEY` / `UCLOUD_PRIVATE_KEY` | UCloud 只读询价凭据 |
| `AUTODL_TOKEN` | AutoDL API 辅助分支令牌，按实际接口启用 |
| `AUTODL_STORAGE_STATE_PATH` | 授权浏览器会话文件路径 |

来源列表供调用方显式使用，不会启用示例配置中已关闭的厂商。地区与硬件条件放在采集配置中；密钥不写入配置文件。配置检查不验证凭据能否访问真实接口。

## 采集接口设计

计划提供 Python API `collect_prices(providers, filters)`，以及将 JSON 写入标准输出、将日志写入标准错误的 `collect` CLI。**两者均尚未实现，本节仅描述目标接口。**

返回结果应包含原始金额、币种、计费单位、实例配置、报价适用范围、采集时间、生效日期、来源链接、筛选应用情况和每个平台的结构化错误。地区未知时保留未知值；部分平台失败时允许返回其他平台的成功结果。详见 [数据模型](docs/DATA_MODEL.md)。

调用方可在自己的程序中执行采集，再将返回值交给自己的上传函数；上传 URL、认证、重试和存储策略都由调用方维护。

## 目录

```text
configs/                 采集配置示例
docs/                    接口设计、平台核查和集成说明
src/gpu_price_monitor/   配置与 CLI 框架
.github/workflows/       CI 检查，不运行每日采集
ROADMAP.md               采集库实施阶段与验收标准
```

## 参与开发与许可证

请先阅读 [贡献指南](CONTRIBUTING.md)。真实接口联调仅使用只读能力，不通过创建或购买 GPU 资源来获取报价。解析器提交需要脱敏样本和价格单位依据。

代码采用 [Apache-2.0](LICENSE)。第三方价格及账号数据的使用与再发布范围见 [数据说明](docs/DATA_POLICY.md)。
