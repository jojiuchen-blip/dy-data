# T3.1 结算筛选、榜单、单店与订单费用 API

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T3.1 将目标双费用事实暴露为可授权、可分页、可导出的生产查询契约

**Requirement ID**：DYDATA-33-API

**PRD 双链·读**：
- `docs/prd/foundation/foundation-api-dy-data/common-contract.md` §1-§6
- `docs/prd/foundation/foundation-api-dy-data/settlement-reporting.md` §0-§5
- `docs/prd/subprd/01-subprd-store-ranking.md` §3-§6
- `docs/prd/subprd/02-subprd-store-settlement.md` §3-§8
- `docs/prd/subprd/03-subprd-order-fee-details.md` §3-§8
- Linear DYDATA-33

**核心逻辑**：
- 扩展 `/meta/filters`；更新榜单和单店接口；新增 `/order-fee-details` 与 `/export`。成功业务字段使用 camelCase、标准分页和 requestId。
- 服务端验证产品组合、正式账期、排序白名单、账单/预览来源上下文、费率/版本集合和门店范围。
- 全国前 20 例外只返回榜单行；单店、订单和导出继续重验授权。导出与列表同口径，空结果 409。
- 旧 `/order-details` 保留通用订单查询，不混入双费用新语义。

**核心文件**：
- `apps/api/dy_api/routes/meta.py`
- `apps/api/dy_api/routes/dashboard.py`
- `apps/api/dy_api/routes/_data.py`
- `apps/api/dy_api/schemas.py`
- `apps/api/dy_api/auth.py`
- `tests/test_api_dashboard.py`
- `tests/test_api_account_permissions.py`

**完成标准**：
- 目标 5 个查询/导出入口返回 Foundation 指定字段、空态、分页、错误和权限行为；内部主键不出现在响应/文件。
- 榜单 totals 与完整过滤集合一致，稳定名次不按页重置；正式累计从 `2026-08` 开始。
- 订单明细一券一方向唯一；锁账上下文只读冻结来源，预览读取当前指针；修改 URL 费率/版本返回 422 而非重算。
- 导出重新验权、含 BOM 和完整追溯列，不受当前页影响；空结果返回 `EXPORT_EMPTY`。

**Verification Method**：
- 执行 `python -m pytest tests/test_api_dashboard.py tests/test_api_account_permissions.py -q`。
- 用 TestClient 覆盖普通门店、多店/总部、全国前 20 例外、未授权、过期上下文、空导出和多页稳定排名。

**Evidence**：
- API 自动化结果、脱敏响应/CSV 样例和 `docs/devlog/` 契约核对记录。

**Failure Handling**：
- DYDATA-32 最终矩阵未确认时不得放宽现有权限，只可使用更严格角色。
- 投影或账单一致性异常时返回结构化错误，不在查询时临时重算。
- 旧调用方回归失败时保留旧路由并修复兼容映射，不让新旧同一路径混用语义。

**完成收尾：状态同步**：
- 完成实现、验证和 foundation 漂移判断后，将完成事实、证据、日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`，由其调度 `delivery-planner` 同步主计划、看板和本子计划；未完成三处同步不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T2.2、T2.4、T2.5

**状态**：已完成本地实现与验证（2026-07-20）

**完成证据**：目标 5 个查询/导出入口、camelCase 契约、正式累计边界、稳定全局排名、单店双费用汇总、预览/current 与锁账/frozen 上下文、完整费率/版本校验、服务端门店范围、全国前 20 例外、同口径 BOM CSV 导出及结构化错误均已实现。目标回归 30 passed，全 API 回归 135 passed，`compileall` 与 scoped `git diff --check` 通过；独立审查 Critical 0、Important 0。Foundation 业务语义无漂移。
