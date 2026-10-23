# UCloud UHost 登录态小时价格

`UCLOUD_SOURCE=console` 对应原文档中的 [UHost GPU 配置报价页](https://console.ucloud.cn/uhost/uhost/gpu_create)。程序使用自己的已登录账号会话，读取官方配置目录，再逐个配置请求小时价格。它与 UCloud 优云智算 CompShare 是不同产品线，不会相互替代。

采集运行只需 Python HTTP，不启动浏览器、不调用 Codex 或大模型。浏览器用于本人登录并导出会话。接口是官网控制台实际使用的内部接口，没有公开 OpenAPI 的稳定性承诺；登录失效或接口变化会报出缺口，不用历史价格兜底。

## 导出自己的登录会话

需要 Python 3.11+。先在仓库目录运行 `python -m pip install .`，安装当前源码；此采集路径不需要 `browser` extra。

1. 在平时使用的 Chrome 登录 [UHost GPU 配置页](https://console.ucloud.cn/uhost/uhost/gpu_create)。不需要购买或创建实例。
2. 打开开发者工具的 **Network / 网络**，筛选 `GetDataForConsoleVersion`，刷新页面。在对应的 `https://api.ucloud.cn` 请求上右键，选择 **Copy → Copy as cURL**。
3. 把复制的文字粘贴到本地纯文本编辑器，保存为 `ucloud.console-request.txt`。这是供导入器读取的数据，**不要粘贴到终端执行**。
4. 在仓库目录运行下面的导入命令，路径替换成自己的文件：

```bash
chmod 600 /完整路径/ucloud.console-request.txt
python -m gpu_price_monitor.providers.ucloud_console_import \
  --curl-file /完整路径/ucloud.console-request.txt \
  --output playwright/.auth/ucloud.console-session.json
```

导入器只解析文本，不执行其中的 shell 命令、不联网。它只接受官方 API 域上的指定目录 / 询价请求，提取 Cookie 并丢弃其他请求字段，保存最小 JSON；新文件权限为 `0600`，已有输出文件不会被覆盖。也可使用官方 `GetUHostInstancePrice` 请求的 **Copy as cURL**，但不能复制创建实例或订单请求。

只从页面 JavaScript 导出 `document.cookie` 可能缺少 HttpOnly 登录 Cookie，无法代表完整有效会话。请使用上述官网请求导出方式，不读取浏览器个人配置目录或 Cookie 数据库。导入完成后清空剪贴板，移除不再需要的请求文本副本；保留最小会话文件供 Python 采集。会话过期时重新导出到新文件并更新配置。

## 本地配置

在自己的 `.env.ucloud.local` 中填写：

```dotenv
GPU_PRICE_MONITOR_PROVIDERS=ucloud
GPU_PRICE_MONITOR_SOURCE_POLICY=api_only
UCLOUD_SOURCE=console
UCLOUD_SESSION_PATH=playwright/.auth/ucloud.console-session.json
UCLOUD_CHECK_AVAILABILITY=false
UCLOUD_PROJECT_ID=
```

`UCLOUD_SESSION_PATH` 相对 `.env` 文件所在目录解析，也可以填写绝对路径。此模式不需要 `UCLOUD_PUBLIC_KEY`、`UCLOUD_PRIVATE_KEY` 或手写询价 targets。显式 `console` 不会因会话缺失而切换到 CompShare、活动月包或旧快照。

`UCLOUD_CHECK_AVAILABILITY=false` 为默认值，不请求库存接口，价格的 `availability` 保持 `unknown`。改为 `true` 可额外检查具体配置库存；库存检查失败仍保留已核实的地区报价，并记录库存未核实的缺口。该变量只接受 `true` / `false`，不接受空值或 `1` / `0`。地区询价成功与当前有库存是不同事实。

`UCLOUD_PROJECT_ID` 可选，填写后应用于所有与项目有关的请求；不填时使用官方 API 的默认项目。结果只标记 `configured_project` 或 `api_default_project` 范围，不返回实际项目 ID。

可选库存接口检查的是 GPU / CPU / 内存 / CPU 厂商与可用区组合，不检查网络模式、镜像和账号配额，不能据此保证最终订单一定可创建。

会话文件含账号凭据，仅留在本机，权限设为 `0600`。不要发到聊天、提交 Git、放入 CSV / JSON 价格结果或上传到网站。采集器只执行目录和询价请求，但会话本身可能具有更多账号权限；会话过期后由本人重新登录和导出。

## Python 与 CLI

```bash
gpu-price-monitor collect --env-file .env.ucloud.local --providers ucloud --pretty > ucloud-prices.json
gpu-price-monitor collect --env-file .env.ucloud.local --providers ucloud --format csv --csv-profile compact > ucloud-prices.csv
# 国家、地区与可用区条件须由同一条报价满足。
gpu-price-monitor collect --env-file .env.ucloud.local --providers ucloud --country CN --region cn-bj2 --zone cn-bj2-02 --format csv --csv-profile compact > ucloud-beijing.csv
```

```python
from pathlib import Path
import json

from gpu_price_monitor import Settings, collect_prices, prices_to_csv

settings = Settings.from_env(env_file=".env.ucloud.local")
result = collect_prices(["ucloud"], settings=settings)
Path("ucloud-prices.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
Path("ucloud-prices.csv").write_text(
    prices_to_csv(result, profile="compact"), encoding="utf-8", newline=""
)
```

Python 示例把同一次采集转成 JSON 和 CSV，便于保持时间与报价一致。两次独立 CLI `collect` 会分别发起实时请求，库存和价格可能变化。CSV 默认中英双语 10 列、UTF-8 BOM，保留每 GPU 小时价格、币种、配置、国家 / 地区 / 可用区、条件与来源；JSON 保留完整响应解析和缺口。

## 怎么确定地区与价格

所有请求发送到固定的官方 `https://api.ucloud.cn`，仅允许目录、可用性和询价操作。

| 官方操作 | 用途 |
| --- | --- |
| `ListRegions`、`ListZones` | 读取国家代码、地区与可用区名称，建立实际报价位置 |
| `DescribeAvailableInstanceTypes` | 读取 GPU 型号、卡数、CPU、内存、CPU 平台及可选网络模式 |
| `DescribeUHostMachineTypeAvailableZones` | 仅在 `UCLOUD_CHECK_AVAILABILITY=true` 时额外检查具体配置库存 |
| `DescribeImage` | 优先选择兼容的基础 Linux 镜像；必要时查询官方预装 GPU Linux 镜像 |
| `GetUHostInstancePrice` | 对具体地区、可用区、硬件、网络模式与磁盘配置请求 `Dynamic` 小时价 |

每条价格使用询价请求内的 `Region` / `Zone`，国家来自官方地区目录；不会把平台覆盖地区复制到一条目录价格上。同一型号在不同地区使用独立询价结果，即使碰巧金额一样，也不宣称全国或全球统一。

目录字段 `Status=Normal` 和地区询价成功均不等于实时有库存。默认库存未知；只有启用额外库存检查并收到有效响应后才记录可用状态。`Soldout` 表示暂时无库存，不是产品下线。库存缺口与价格缺口分别记录：库存检查失败不会丢弃已核实的地区报价，地区无法核实或询价失败则不能当作该地区成功报价。

## 本次采集范围

询价或目录请求失败时，JSON 缺口保留官方操作名 `provider_action` 和数值错误码 `provider_retcode`，便于逐项对照官网请求。原始响应文本、请求 ID 和账号信息不导出；错误码本身不用于猜测“无库存”“权限不足”或“厂商未定价”。登录过期会明确报 `authentication_error`，不会用上次结果冒充新报价。

枚举官方 UHost GPU 目录中列出的 GPU 数量 / CPU / 内存 / CPU 厂商与地区可用区组合，并逐项询价；库存检查是可选的独立步骤。同厂商的 CPU 代际选项保留在配置元数据中，不把未单独定价的代际反复计成独立报价。

每个硬件组合只选一种明确的基准网络模式：目录列出 `Normal` 时使用它；未列出 `Normal` 时，必须只有唯一的可选模式才采用该模式。询价始终显式传入 `NetCapability`，完整可选模式及所需镜像功能保留在元数据中，镜像必须满足所选模式要求。模式缺失或选择有歧义时记录缺口；接口拒绝该模式时，也不会删掉网络参数重试成另一种报价。网络模式会影响价格，不能只匹配 GPU / CPU / 内存就视为相同配置。

每个组合优先使用该地区官方目录内兼容的基础 Linux 镜像（`ImageType=Base`）。没有兼容项时，再查询 `ImageType=Business`、`FuncType=gpu` 的官方预装 GPU Linux 镜像；必须由 `SupportedGPUTypes` 明确列出该 GPU 型号，并满足官网对应的网络功能要求。不会仅凭镜像名称猜测兼容性。

两条路径均使用与镜像匹配的最小启动盘，并在实际询价中核实 `UMkt` / `UImage` 镜像及授权费用为零；有额外软件收费的组合不作为该基准报价。结果保留实际镜像、镜像类型、磁盘类型和容量。报价不含额外数据盘、公网 IP、带宽或其他未请求资源。与官网人工核对时，必须选择相同地区、可用区、卡数、CPU、内存、网络模式、镜像、磁盘和计费方式；官网默认附加磁盘或公网服务可能使总价不同。

主金额为 `PriceSet.Price / GPU 数量`，即该配置的计算资源与启动盘总费用分摊到每张 GPU，每小时以 CNY 计价；它不是 GPU 硬件组件单独售价。实例总价和 `PriceDetail` 的计算资源、磁盘等分项同时保留。不会从包月价格除以假定小时数，也不会把人民币当美元；美元换算由 RackRate 等调用方另行处理。账号优惠和价格条款以实际响应及元数据为准，不能把当前账号报价推广成所有客户均可获得的价格。

范围是当前账号可见的按量 UHost GPU 硬件配置，搭配一种明确的基准网络模式、兼容的免费镜像及最小启动盘。不穷举其他网络模式，也不包含 Spot、包月 / 包年、合同报价、任意磁盘容量、付费镜像或所有附加服务组合。成功遍历这一范围也不表示拿到了平台所有可能的最终订单价。批次是否完整请同时检查 JSON 的 `provider_results`、覆盖统计与缺口，而不能只看 CSV 行数。
