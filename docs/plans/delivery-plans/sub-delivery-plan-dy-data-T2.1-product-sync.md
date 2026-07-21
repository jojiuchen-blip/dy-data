# T2.1 商品在线同步与历史

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T2.1 实现商品同步适配器、运行记录、历史快照与管理接口

**Requirement ID**：DYDATA-30-SYNC

**PRD 双链·读**：
- `docs/prd/foundation/foundation-api-dy-data/product-sync.md` §0-§5
- `docs/prd/foundation/foundation-schema-dy-data/product-rule-source.md` §1-§2
- Linear DYDATA-30

**核心逻辑**：
- 在现有 `DouyinOpenApiClient`、worker pipeline 和 `job_runs` 基础上增加商品在线同步适配器；正式 URL、鉴权、游标和枚举只从用户提供的脱敏样例/文档冻结。
- 每次观测写历史快照；仅完整合法提交后更新当前平台字段和最近成功时间，绝不覆盖人工分类。
- 同目标仅一个 RUNNING；增量游标随事务推进；下架/删除需稳定状态或完整对账，单页缺失不得推断删除。

**核心文件**：
- `src/dy_data/douyin_client.py`
- `apps/worker/pipeline.py`
- `apps/worker/repositories.py`
- `apps/api/dy_api/routes/admin.py`
- `apps/api/dy_api/schemas.py`
- `tests/test_douyin_openapi_client.py`
- `tests/test_api_admin_sync.py`

**完成标准**：
- 成功、空页/末页、重复页、非法响应、限流/重试和上游失败均有 fixture 测试；错误与游标脱敏。
- 同步成功后当前平台字段与历史一致，人工三字段保持原值；失败/部分失败不更新最近成功时间。
- 4 个内部管理查询/触发接口满足幂等、并发与权限契约。
- 生产验收包含用户提供的至少一份脱敏成功响应、一份空页/末页、一份错误响应和渠道枚举说明。

**Verification Method**：
- 先以脱敏 fixture 补红灯测试；执行 `python -m pytest tests/test_douyin_openapi_client.py tests/test_api_admin_sync.py -q`。
- 在隔离目标环境执行一次全量和一次增量同步，核对 observed/inserted/updated/unchanged/failed 数量与历史/当前表。

**Evidence**：
- 测试 fixture（不含凭据/真实导出）、`docs/devlog/` 同步计数摘要、Linear DYDATA-30 验证记录。

**Failure Handling**：
- 外部样例/文档未提供时可完成内部结构和 fixture 测试，但本 Task 不得标记生产验收完成。
- 未知状态映射为 `UNKNOWN`，未知渠道进入质量问题，不扩大为有效。
- 响应包含敏感值时仅保留白名单字段和摘要，不写日志或 API。

**完成收尾：状态同步**：
- 完成实现、验证和 foundation 漂移判断后，将完成事实、证据、日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`，由其调度 `delivery-planner` 同步主计划、看板和本子计划；未完成三处同步不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T1.2；生产验收需外部商品 API 脱敏样例

**状态**：已完成本地实现与验证（2026-07-20）；真实外部商品 API 的生产验收仍依赖用户提供的脱敏样例
