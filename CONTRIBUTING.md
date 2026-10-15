# 贡献指南

当前处于初始化阶段，请先查阅 ROADMAP.md 和 docs/PROVIDERS.md，避免把文档示例或已有资源价格误做完整市场报价。

新增数据源时请说明：官方依据、认证范围、地区条件、金额单位、整机或组件口径、优惠条件及失败行为。提供经过脱敏的最小响应或页面样本。

配置字段新增时同步更新示例、检查器及文档。后续解析器测试应覆盖多卡换算、地区切换、历史生效日期、询价项、缺货和认证失败。

```bash
PYTHONPATH=src python3 -m gpu_price_monitor validate-config --config configs/monitor.example.json
python3 -m compileall -q src
```

不要提交真实账号凭据、浏览器会话或完整控制台响应。不要为获取价格启动收费实例。外部 PR 验证使用脱敏样本，不运行带部署凭据的真实采集。
