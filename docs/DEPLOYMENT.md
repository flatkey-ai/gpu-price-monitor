# 安装和接入

本库只抓取并返回 JSON，调用者自行安排定时、保存、换汇和上传。支持的平台仅有 Nebius、Lambda、Crusoe、AutoDL、UCloud。

## 免费公开模式

Python 3.11+，无需密钥。建议使用独立虚拟环境：

```bash
git clone https://github.com/flatkey-ai/gpu-price-monitor.git
cd gpu-price-monitor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install '.[browser]'
python -m playwright install chromium
gpu-price-monitor collect --providers all --coverage --pretty > prices.json
```

Windows PowerShell 的前两步使用 `py -3 -m venv .venv`、`.\.venv\Scripts\Activate.ps1`。Linux 容器缺少浏览器库时使用 `python -m playwright install --with-deps chromium`。AutoDL 用本地 Chromium，其余四家公开来源用基础 Python 包即可。

`configs/collect.all.example.json` 启用全部五家；`collect.example.json` 保留两家 HTTP 来源最小示例；`collect.free.example.json` 保留 Lambda/AutoDL/UCloud 三家示例。`all` 不包含旧版本其他平台。

## 可选凭据及地区报价

复制 `.env.example`，填好再显式加载：

```bash
gpu-price-monitor status --env-file .env
gpu-price-monitor collect --env-file .env --providers all --pretty
```

Python 使用 `Settings.from_env(env_file=".env")`。进程环境覆盖文件设置，不执行变量插值或 shell，库不自动发现 `.env`。凭据存在也不会自动选择认证模式，必须指定来源。

- Nebius：设置 `NEBIUS_SOURCE=api`、access token、targets FILE/JSON。复制 `configs/nebius-targets.example.json` 到被忽略的 `*.local.json`，填写真实项目及支持平台的完整 GPU 预设/磁盘。先验证项目地区，再只读费用估算；不创建实例。国家与地区不一致会失败。
- UCloud：设置 `UCLOUD_SOURCE=api`、公私钥及 targets FILE/JSON；可选项目 ID。复制 `configs/ucloud-targets.example.json` 并核对实际可售配置。API 分支核对官方 Region/Zone/CountryCode 后询价，不把离线促销代替按需价格。
- Lambda：`LAMBDA_SOURCE=api` 与 API key 选择认证实例目录；容量地区不会变成逐地区价格。
- AutoDL：`AUTODL_SOURCE=market` 与 `AUTODL_STORAGE_STATE_PATH` 选择登录市场。会话由用户在自己的浏览器中准备；过期返回错误，不自动登录、不读已租资源、不租赁 GPU。

访问令牌、Cookie、私钥、项目和本地配置不要提交。`.env`、`configs/*.local.json`、`playwright/.auth/`、`*.storage-state.json` 已被忽略。示例模板仅说明字段，不证明示例配置可售或凭据有效。

## 调用者的发布流程

先检查进程退出码和 `provider_results`，再将成功批次提交自己的存储或上传函数。部分失败返回 exit 2；不要把失败写成零价，也不要把旧数据换上本次采集时间。结合原币、单位、配置、购买条件、价格范围及可用性比较，换汇另记汇率来源和日期。

本库不绑定 RackRate 或 Flatkey 上传地址。RackRate 自己的 GitHub Actions 每天北京时间 10:30 发起公开采集和发布；云任务可能排队，页面展示实际采集时间。授权账号模式若要交由调用方云任务运行，由调用方自行配置受控密钥和会话，不在库中添加业务凭据。

## 离线检查

```bash
python -m compileall -q src
python -m unittest discover -s tests -v
gpu-price-monitor validate-config --config configs/collect.all.example.json
```

单元测试和配置检查不访问账号或购买资源；真实五家公开采样与未完成的认证验证边界见 [文档对照](DOCUMENT_COVERAGE.md)。
