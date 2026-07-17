# dy-data 数据模型索引

> 当前结构以 `apps/api/dy_api/models.py`、Alembic 迁移和目标数据库实际 schema 为准。本文按业务域整理当前 37 个 SQLAlchemy 表模型，作为 S0.5 证据索引，不冒充尚未建立的 FOUNDATION schema。

## 1. 原始采集层

- `raw_douyin_orders`：抖音订单原始记录。
- `raw_douyin_order_coupons`：订单券明细。
- `raw_douyin_verify_records`：核销记录。
- `raw_aweme_bindings`：抖音号/职人绑定原始数据。
- `raw_douyin_clues`：抖音线索原始数据。

原始层用于保留采集证据和支持重算。采集脚本必须幂等处理业务主键或来源主键，不把临时导出文件当成数据库权威。

## 2. 门店、账号与配置

- `dim_stores`：内部门店主数据及线索分配资格、地区和位置属性。
- `users`、`user_store_scopes`：用户、角色和门店数据范围。
- `user_feedback_submissions`：用户反馈及处理状态。
- `dim_store_poi_mappings`：抖音 POI 到内部门店的映射。
- `dim_sku_product_rules`：SKU 到商品类型及相关规则。
- `dim_non_commission_owner_accounts`：不参与佣金归属的账号配置。
- `dim_aweme_accounts`：抖音账号维度。
- `sync_settings`：同步任务配置。
- `product_type_visibility_settings`：商品类型可见性配置。

门店权限由 `users` 与 `user_store_scopes` 共同约束；POI、账号和 SKU 映射是经营、结算和线索计算的共享基础，页面不得另建冲突口径。

## 3. 经营与结算

- `settlement_order_details`：可追溯的订单/券结算明细，承载销售归属、核销归属、跨店关系和金额依据。
- `agg_store_ranking`：门店经营排名聚合。
- `agg_store_monthly_settlement`：门店月度结算参考聚合。
- `data_quality_issues`：归属、映射、状态或数据完整性问题。

聚合表服务查询性能，不替代明细证据。刷新逻辑变化时必须同时验证明细、聚合和页面筛选口径。

## 4. 任务与运行

- `job_runs`：采集、刷新、重建和浏览器任务的开始、结束、状态、计数与错误摘要。

错误摘要不得保存密钥、Cookie、数据库 URL 或完整个人信息。

## 5. 线索运营与分配

### 主池、状态与跟进

- `clue_master_leads`：线索主池和当前分配/池位置状态。
- `clue_order_status_events`：线索订单状态事件。
- `clue_center_orders`：兼容线索中心投影。
- `clue_assignment_rounds`：兼容或展示用分配轮次投影。
- `clue_follow_up_records`：门店跟进记录。

### 评分

- `store_score_snapshot_runs`：门店评分快照批次。
- `store_score_snapshots`：某一批次的不可变门店评分结果。

### 规则与门店组

- `clue_store_groups`、`clue_store_group_members`：参与分配的门店组与成员。
- `clue_allocation_rules`：规则稳定身份。
- `clue_allocation_rule_versions`：可发布、退役和追溯的规则版本。
- `clue_allocation_strategy_configs`：规则版本下的策略配置。
- `clue_lead_rule_version_bindings`：线索与实际采用规则版本的绑定。

### 决策、轮次与审计

- `clue_allocation_decisions`：线索分配决策和原因。
- `clue_allocation_cycles`：预览、试运行或重建轮次。
- `clue_headquarters_pool_entries`：总部线索池记录。
- `clue_allocation_audit_logs`：线索分配操作和状态变化审计。

分配结果必须能够追到规则版本、评分快照、轮次、决策和审计证据。缺少有效锚点或映射失败时进入明确的待处理或总部池状态，不能伪造门店分配。

## 6. 迁移与一致性规则

- schema 变化通过新的 Alembic 迁移提交，SQLAlchemy 模型同步更新。
- 已在共享环境执行的历史迁移不回写修改；使用后续迁移纠正。
- 金额、时间、ID、枚举、唯一约束和外键语义以当前模型与迁移为准。
- 高风险迁移需评估旧数据、回填、索引、锁和恢复方式。
- 文档与模型冲突时先核对目标数据库；确认后更新模型、迁移或本文，不在页面做静默兼容。

## 7. FOUNDATION 缺口

本文没有逐字段复制 37 个表，避免形成第二份易漂移 schema。后续 `foundation-builder` 应从当前模型、迁移、真实 schema 和业务口径建立正式术语、关系、字段与 API foundation；完成后本文件保留为导航索引。
