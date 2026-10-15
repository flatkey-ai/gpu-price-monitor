# 配置与调用方接入

本项目交付价格采集库，不提供托管采集服务。当前可运行状态和配置检查 CLI；实时采集 API、`collect` CLI 及厂商适配器尚未实现。下述采集集成流程为设计说明。

## 当前可用的本地检查

Python 3.11+：

```bash
python3 -m pip install -e .
gpu-price-monitor status
gpu-price-monitor validate-config --config configs/collect.example.json
```

也可使用 `PYTHONPATH=src python3 -m gpu_price_monitor` 运行相同子命令。配置检查不访问厂商，不购买或创建资源；通过检查不表示采集器可用。

`configs/collect.example.json` 中各平台默认关闭。文件仅描述采集来源、地区 / 硬件 / 计费筛选和请求选项，不包含调度、数据库或上传设置。

## 环境变量

配置读取使用 `Settings.from_env()`，仅从进程环境读取变量。仓库的 [`.env.example`](../.env.example) 是字段参考；当前不自动加载 `.env`。调用方可使用现有配置系统、容器或运行器的 secrets 注入能力。

已实现的 Python 配置入口如下；读取配置不会联网或发起采集：

```python
from gpu_price_monitor import Settings

settings = Settings.from_env()
providers = settings.providers
```

| 变量 | 默认值 / 使用范围 |
| --- | --- |
| `GPU_PRICE_MONITOR_PROVIDERS` | `nebius,crusoe`，逗号分隔的来源列表 |
| `GPU_PRICE_MONITOR_TIMEOUT_SECONDS` | `30`，请求超时秒数 |
| `GPU_PRICE_MONITOR_MAX_RETRIES` | `2`，最大重试次数 |
| `LAMBDA_API_KEY` | Lambda 认证目录 |
| `NEBIUS_ACCESS_TOKEN` | Nebius 认证估价 API；公开计价文档不需要 |
| `UCLOUD_PUBLIC_KEY` | UCloud 询价 API 公钥 |
| `UCLOUD_PRIVATE_KEY` | UCloud 签名私钥，与公钥配对 |
| `AUTODL_TOKEN` | 按 AutoDL 具体 API 分支要求使用 |
| `AUTODL_STORAGE_STATE_PATH` | 授权 Playwright 浏览器会话文件路径 |

环境来源列表不覆盖配置文件中的关闭状态，也不会在读取时启动采集。认证是否必需取决于选中的来源和采集分支；公开页面和认证询价不能混为同一种权限要求。

超时、重试和来源名称应通过配置校验。地区、SKU、卡数、CPU、内存、磁盘、计费方式和币种通过采集筛选传入，不编码在凭据中。完整私钥、API key 和浏览器会话内容不能出现在返回值、日志、Issue 或工件中。配置检查只验证格式，不验证凭据有效性，也不联网。

完整规格筛选属于目标接口设计；当前检查器支持的字段以 `configs/collect.example.json` 为准，仅包含服务 / 销售国家、地区、可用区、GPU 型号、卡数、计费方式和币种。SKU、CPU、内存及磁盘筛选尚未加入当前配置格式。

## 调用与上传职责

未来调用方可通过 Python API `collect_prices(providers, filters)` 获取结构化结果，或执行 `collect` CLI 并读取 stdout JSON。日志输出至 stderr；错误包含来源和可重试性。当前没有可运行的采集命令，不能用状态检查命令代替真实采集。

调用方集成过程如下，上传属于调用方自己的代码：

```text
调用方加载配置和密钥
→ 调用采集库
→ 校验结果中各来源状态及筛选应用情况
→ 调用方上传函数（自有 URL、认证和重试策略）
→ 调用方数据库 / 历史 / 比价 / 展示
```

库中不配置上传 URL、上传令牌、数据库连接或 Webhook。Flatkey 可在自己的私有运行器实现这段流程；其他人可上传到自己的服务，或只消费返回结果。

## 运行环境选择

采集仅需普通 CPU。调用方可以在应用进程、自己的定时任务、服务器、容器或 CI 运行器中执行，负责运行频率、资源、超时预算、重跑和进程退出处理。库不规定每天运行时刻。

浏览器来源可能需要额外浏览器依赖和持久会话，由使用者授权提供。会话失效应返回认证状态；不绕过验证码或访问控制。[Playwright 认证状态文档](https://playwright.dev/python/docs/auth)

如调用方使用 GitHub Actions 调度，应自行考虑计划任务延迟或停用、凭据隔离和结果保存。[GitHub 调度规则](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

真实接入前按最小范围只读联调，只查询价格、规格和容量，不创建、启动或购买 GPU 实例。来源尚未完成联调时，明确报告未验证状态。
