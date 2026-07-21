# T3.3 商品、费率、导入与同步后台

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T3.3 在现有管理端落地已冻结的商品治理与安全发布能力

**Requirement ID**：DYDATA-ADMIN-WEB

**PRD 双链·读**：
- `docs/prd/foundation/foundation-api-dy-data/sku-fee-admin.md` §0-§13
- `docs/prd/foundation/foundation-api-dy-data/product-sync.md` §0-§4
- Linear DYDATA-1、DYDATA-21、DYDATA-30 的页面/验收范围

**核心逻辑**：
- 复用现有 `/admin/rules` 与 `/admin/sync` 管理布局，不凭空扩张独立页面 IA。
- 商品列表只编辑人工三字段；双费率查看版本并发布新版本；导入包含模板下载、上传预校验、逐行错误、结果文件和确认后原子提交。
- 商品同步展示运行列表/详情、计数、脱敏错误和 SKU 历史；触发成功只表示入队。

**核心文件**：
- `apps/web/src/pages/AdminSkuRulesPage.tsx`
- `apps/web/src/pages/AdminSyncPage.tsx`
- `apps/web/src/api/client.ts`
- `apps/web/src/types/dashboard.ts`
- `apps/web/src/App.tsx`
- `tests/test_frontend_user_facing_contracts.py`
- `tests/test_visual_smoke.py`

**完成标准**：
- 保存商品分类后重新加载回显一致；平台字段不可编辑，错误能定位到字段。
- 发布双费率明确显示自然日、两项费率、版本、原因和冲突；不再调用旧单费率覆盖式保存作为正式入口。
- 导入任一错误时明确“整批未写入”，展示行号/字段/原因并可下载结果；只有全量通过才允许原子提交。
- 同步任务显示 QUEUED/RUNNING/SUCCESS/FAILED/PARTIAL，不泄露 Cookie、token、原始游标或完整载荷。

**Verification Method**：
- 执行 `npm --prefix apps/web run build` 与前端契约/视觉 pytest。
- 真实 API 验证加载→修改→提交→重新加载；用合法/非法 CSV/XLSX 验证原子导入；轮询一次同步任务成功与失败状态。

**Evidence**：
- `<projectRoot>/pwScreenShot/dy-data-admin-rules-1440.png`、`dy-data-admin-import-error-1440.png`、`dy-data-admin-sync-1440.png`。
- `docs/devlog/` 管理端联调记录。
- 2026-07-21：后端/API/Schema/Alembic 回归 56 passed；完整浏览器/视觉回归 112 passed；新增数据库级商品同步幂等唯一约束与 `20260721_0026` 迁移；Web build、`git diff --check` 通过；独立复审无 Critical/Important。

**Foundation 漂移结论**：业务字段、状态机与错误契约无漂移；为关闭同键并发在任务快速完成后的重复创建竞态，`job_runs` 增加商品同步专用 `idempotency_key_hash` 与部分唯一索引，属于冻结幂等契约的数据库实现加固。

**Failure Handling**：
- 管理端交互超出 Foundation/Linear 已冻结范围时停止并回到需求定义，不临时新增业务动作。
- 缺高风险角色矩阵时保持最严格管理员依赖并阻断生产提交验收。
- 同步失败不覆盖最后成功快照，页面不得显示失败开始时间为成功时间。

**完成收尾：状态同步**：
- 完成实现、验证和 foundation 漂移判断后，将完成事实、证据、日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`，由其调度 `delivery-planner` 同步主计划、看板和本子计划；未完成三处同步不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T2.1、T2.2

**状态**：已完成（2026-07-21）；生产环境联调与业务验收保留到 T4.1
