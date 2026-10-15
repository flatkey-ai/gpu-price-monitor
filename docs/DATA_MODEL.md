# 数据口径和模型草案

设计草案，尚未实现数据库或迁移。

## 记录类型

| 类型 | 主要内容 |
| --- | --- |
| MonitorTarget | 平台、产品线、SKU、位置、配置、计费和报价条件 |
| PriceObservation | 原价、单位、组件、派生价、时间、状态及来源 |
| CapacityObservation | SKU、地区、容量状态、观察时间及来源 |
| CollectionRun | 目标、开始结束时间、重试、成功状态与错误类别 |
| Evidence | 脱敏证据位置、哈希、解析器版本；私有证据不可公开导出 |

## 条件标识

报价目标的规范化条件包括：

```text
provider / product_type / source_site / sales_country /
compute_country / region / zone / raw_sku /
gpu_model / gpu_variant / vram_gib / gpu_count / allocation_type /
cpu / memory_gib / disks / network_profile /
billing_mode / commitment / currency / tax_scope /
price_scope / account_scope / discount_conditions
```

以上条件变化形成新序列。价格生效日期属于报价版本，不改变同条件目标身份。无法确定的值保存为 null 或明确的 unspecified；不能从币种、语言或访问 IP 猜测服务国家。

`price_scope` 区分 public_catalog、authenticated_catalog、account_quote、contract。认证目录不自动等于账号专属价，也不能未经核对直接视为公开价。

`geographic_scope` 另行表示 region、zone、global、unspecified，不能将其与价格身份混为同一字段。容量有地区但价格未细分时，分别存储，不派生地区报价。

## 报价字段

- original_amount：十进制金额字符串，避免二进制浮点误差。
- currency、original_unit、billing_period、minimum_charge：原币和原始计费口径。
- price_basis：instance_total、gpu_component、advertised_per_gpu、starting_price。
- included_components：价格包含的 GPU、CPU、内存、磁盘等及条件。
- normalized_gpu_hour：仅条件充分时生成；保留公式和假设。
- observed_at、effective_from、effective_until：带时区时间；未知生效日期留空。
- source_url、parser_version、evidence_ref：可追溯来源。
- quote_status：quoted、contact_sales、unavailable、unverified。
- availability：available、unavailable、unknown，与价格是否存在独立。

采集失败属于运行记录，不造一条零元报价。过期是根据最近成功时间派生的展示状态。跨币种显示另存 fx_rate、fx_source、fx_observed_at；原币调价检测不使用换汇价格。

## 去重与历史

使用目标 ID、采样窗口及数据来源防止同一任务重试重复入库；真实 observed_at 始终保留。不同时间有效采样可以保留，daily 视图按规则选取并记录选择策略。补采不是追溯历史价格。

不以一次空结果判断下架；先确认采集成功和覆盖完整，再经多次发现确认。保留供应商原始 SKU，不仅凭标准化 GPU 名称拼接历史。
