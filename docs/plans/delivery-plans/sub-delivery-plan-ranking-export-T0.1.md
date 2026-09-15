# T0.1 排序与分指标导出

- 主开发计划：[主计划](main-delivery-plan-ranking-export.md)
- 任务看板：[看板](task-kanban-ranking-export.md)

#### T0.1 排序与分指标导出

**Requirement ID**：用户直接授权，本次跳过Linear。

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` §全局设计规则

**核心逻辑**：按店均、24小时跟进、核销排行；每指标一个工作表，各层级独立附表，复用单一快照与权限。

**核心文件**：apps/api/dy_api/ranking_export.py、ranking_snapshots.py、routes/dashboard.py、apps/web/src/pages/DouyinRankingPage.tsx、components/DouyinRankingExportDialog.tsx、tests/test_ranking_preview_api.py。

**完成标准**：层级/指标多选、时间范围、全量导出、辅助指标、同一排名口径、权限隔离；CI和部署通过并核验线上。

**Verification Method**：pytest、npm build、浏览器真实后端、xlsx回读、CI、生产冒烟。

**Evidence**：测试先复现404，基线5项通过；完整证据回填开发记录。

**Failure Handling**：保留原数据口径；失败停止发布；回滚代码无需数据迁移。

**Owner**：当前Codex任务。

**前置**：用户已确认开发部署。

**状态**：进行中

**完成收尾：状态同步**：API合同、开发日志、当前执行计划记录验证和部署结果，本次经用户确认跳过Linear。
