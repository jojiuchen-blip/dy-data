# T2.2 SKU 商品、双费率与原子导入 API

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T2.2 实现商品人工分类、双费率版本、整批导入与结算范围接口

**Requirement ID**：DYDATA-1-ADMIN / DYDATA-21-RULES

**PRD 双链·读**：
- `docs/prd/foundation/foundation-api-dy-data/sku-fee-admin.md` §0-§13
- `docs/prd/foundation/foundation-api-dy-data/common-contract.md` §1-§6
- Linear DYDATA-1、DYDATA-21

**核心逻辑**：
- 商品人工更新只允许产品范围、商品类型、服务商品标记与审计列。
- 双费率按 SKU + 生效自然日只新增版本；首批 `2026-08-01`，后续到日；同日冲突 409，不回写历史结算。
- `.xlsx` 与 UTF-8 `.csv` 上传先全量校验，返回同一行全部错误；10 MiB、5000 行内任一行错误则正式规则零写入。通过后以幂等键原子提交整批。
- 结算范围按月、稳定归属账号 ID、`LIVE/SHORT_VIDEO` 分渠道发布不可变版本。

**核心文件**：
- `apps/api/dy_api/routes/admin.py`
- `apps/api/dy_api/routes/_data.py`
- `apps/api/dy_api/schemas.py`
- `apps/api/dy_api/auth.py`
- `tests/test_api_admin_sku_rules.py`
- `tests/test_api_account_permissions.py`

**完成标准**：
- Foundation §1-§13 的 SKU/费率/导入/范围管理接口可用，成功响应 camelCase，错误含稳定 code、requestId、行号、字段与原因。
- 单条发布、导入提交和范围发布支持 `Idempotency-Key`；同键异请求 409，同请求重试返回首次结果。
- 导入覆盖合法、模板错、类型错、名称-ID 不匹配、费率越界、批内重复、数据库冲突、提交期竞争和事务回滚。
- 旧 `/admin/sku-rules` 只保留明确兼容，不再成为正式双费率写入口。

**Verification Method**：
- 执行 `python -m pytest tests/test_api_admin_sku_rules.py tests/test_api_account_permissions.py -q`，并新增真实 TestClient 的导入/幂等/回滚用例。
- 对 5000 行边界文件执行预校验和原子提交，回读正式规则数量与批次逐行状态。

**Evidence**：
- 测试结果、脱敏导入结果样例、事务前后规则计数和 `docs/devlog/` 记录。

**Failure Handling**：
- 任一行非法或提交期发生冲突时整批回滚，`successCount=0`；不开放“仅写合法行”。
- 稳定归属账号 ID 或真实渠道枚举未确认时，不发布生产范围规则。
- 缺最终高风险角色矩阵时使用当前最严格管理员依赖并在 T4.1 阻断最终发布。

**完成收尾：状态同步**：
- 完成实现、验证和 foundation 漂移判断后，将完成事实、证据、日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`，由其调度 `delivery-planner` 同步主计划、看板和本子计划；未完成三处同步不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T1.2

**状态**：已完成（2026-07-20）
