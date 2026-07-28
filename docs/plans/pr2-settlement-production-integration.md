# PR #2 结算中心生产集成控制计划

## 目标与边界

- 来源分支：`origin/codex/commission-page-collab-20260707`
- 固定来源提交：`299f9f9cfdb0c7c008722a05d1ea995de7d8a43b`
- 集成基线：执行时最新 `origin/main`
- 目标需求：DYDATA-1、DYDATA-21、DYDATA-30、DYDATA-31、DYDATA-33、DYDATA-38
- 默认不合并 `main`；完成代码、真实环境验证、脱敏回填和推送后等待用户确认。

## 保留策略

1. 保留协作者的 SKU 规则统一、双费率、自然日版本、原子导入、商品同步、结算报表、四个页面和两阶段主键迁移实现。
2. 保留最新主线的账号权限、Agent/MCP、线索中心、设计系统、部署和治理实现。
3. 共享文件按功能并集合成；过期治理副本和历史主线合并提交不覆盖当前权威文件。
4. 仅针对真实验收失败、生产适配缺口和主线冲突做最小修复。

## 验收矩阵

| 需求 | 必须通过的生产验收 |
|---|---|
| DYDATA-1 | 数据库为唯一 SKU 规则源；产品范围筛选在 API 和页面一致；无 CSV 运行时依赖 |
| DYDATA-21 | 双费率自然日生效；CSV/XLSX 整批原子导入；错误定位、冲突拒绝和重试幂等 |
| DYDATA-30 | 真实抖音商品 API 成功、空页、末页、错误响应；同步任务、历史和进度可追踪 |
| DYDATA-31 | 2026-08 正式起算；推广/管理双费用；退款撤销调整；跨月、锁账、月度与累计投影 |
| DYDATA-33 | 榜单、单店结算、订单费用明细、开票指引；筛选、下钻、导出、空态/错误态；总部与门店权限 |
| DYDATA-38 | PostgreSQL 两阶段订单/券内部主键迁移；约束、行数、回滚和锁风险验证 |

## 质量门禁

- `git diff --check`
- `python -m pytest`
- `npm --prefix apps/web run build`
- Project Manager Suite 锁、全局文件、路由和专项测试
- PostgreSQL `upgrade -> downgrade -> upgrade`、单一 Alembic head、约束与数据守恒
- Playwright 390/768/1440 视口、无控制台错误、关键角色/API 流程
- 不提交真实数据、数据库地址、令牌、Cookie、日志、临时数据库、`dist` 或 `node_modules`
