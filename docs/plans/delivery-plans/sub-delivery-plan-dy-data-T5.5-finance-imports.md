# T5.5 四类财务导入与更正

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T5.5 完成流式预校验、原子提交、错误下载和更正版本

**Requirement ID**：DYDATA-19-IMPORT

**PRD 双链·读**：
- `docs/prd/subprd/09-subprd-finance-imports.md` §3～§4
- `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md` §5

**核心逻辑**：
- 实现接口 #37～#42 和推广费审核结果、推广费结算结果、管理费发票明细、厂家扣款结果四类模板。
- 以业务唯一键、标准化内容和文件摘要判断幂等；流式解析并保存所有错误，任一错误时正式业务表零写入。
- 差异提交和更正统一使用读取版本、原子事务和新版本覆盖；禁止来源行 ID、模糊匹配、部分写入、自动截断和人工待匹配池。

**核心文件**：
- `apps/api/dy_api/routes/`
- `apps/api/dy_api/schemas.py`
- `apps/api/dy_api/models.py`
- `tests/`

**完成标准**：
- 6 个接口覆盖首次可提交、无变化、差异待确认、整批失败和版本冲突五种结果。
- 多行多字段错误全部落库，可分页查看和下载；大文件处理不一次性保留全部行对象。
- 管理费导入上期账期，提交时间同时为审核通过/结算时间；厂家扣款和确认金额严格相等，不允许部分扣款。

**Verification Method**：
- 使用 CSV/XLSX fixture 验证四模板、重复上传、差异确认、并发提交、更正覆盖、全部错误下载和事务回滚。
- 以受控大文件 fixture 记录峰值内存、处理行数和错误数，确认错误不截断。

**Evidence**：
- `docs/devlog/` 中 T5.5 导入矩阵、行数/错误数/写入数、内存与并发测试记录。

**Failure Handling**：
- 文件格式、门店 ID、业务键或任一字段错误即整批失败，正式目标表写入数必须为 0。
- 提交版本变化返回 409 和最近操作信息，不自动重放旧预览。
- 性能证据不足时限制文件上限并阻断大文件发布，不牺牲全部错误可见性。

**完成收尾：状态同步**：
- 完成实现、验证与 Foundation 漂移判断后，把完成事实、证据、日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`；由其同步主计划、看板和本子计划并重跑 S4 路由检查。三处未同步前不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T5.1～T5.4

**状态**：待审阅
