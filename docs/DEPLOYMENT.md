# 部署计划

本文件是部署设计；当前仅能运行配置检查 CLI，尚无 Docker 镜像、定时采集、看板或通知服务。

## 推荐运行方式

固定 CPU 主机运行 Docker 采集服务，持久化 SQLite、授权浏览器会话和私有证据。公开数据通过白名单导出，再发布静态看板。无需 GPU。

未来提供 GitHub Actions 模式用于适合在托管 runner 中执行的公开来源。Actions schedule 可能延迟或丢任务，公开仓库长期无活动可停用计划任务，需补采与独立新鲜度检查。

- [GitHub 调度规则](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [Playwright 认证状态](https://playwright.dev/python/docs/auth)

## 计划运行参数

- 时区：Asia/Shanghai；入库时间统一带时区，展示可换算。
- 主采集：09:17；补采：11:47；数据过期阈值：30 小时。
- 补采只处理缺失目标，保留真实采样时刻。
- 数据库定期备份；公开日快照长期归档，私有证据按独立期限清理。

## 凭据准备

Lambda API key、UCloud 询价凭据、AutoDL 授权会话按实际启用的平台配置。Nebius 公开文档无需估价凭据；启用估价分支时另行配置认证和续期。

仅向部署环境注入凭据，CI 外部 PR 不访问厂商凭据。采集与发布权限分开，不在日志、公开 CI 工件、配置示例和 Issue 中保存会话、签名、私钥或账号原始响应。

正式启用前完成最小范围只读联调，不创建收费实例获取价格。认证失效、参数无效、单位不明和服务限速分别报告。
