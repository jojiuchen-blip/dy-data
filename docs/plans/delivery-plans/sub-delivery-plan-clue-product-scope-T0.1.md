# T0.1 商品范围与组织筛选

- 主开发计划：[主计划](main-delivery-plan-clue-product-scope.md)
- 任务看板：[看板](task-kanban-clue-product-scope.md)

#### T0.1 商品范围与组织筛选

**Requirement ID**：用户已授权开发部署，跳过Linear。

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` §全局设计规则
- `docs/plans/2026-09-23-clue-product-scope.md` §目标行为

**核心逻辑**：全部商品=精诚养车+比亚迪本品；NULL及未匹配属于本品；范围贯穿统计、缓存、下钻和导出。组织使用完整路径及当前权限交集；指标看板保持全局可见。

**核心文件**：ranking_business.py、ranking_snapshots.py、routes/dashboard.py、routes/clues.py、routes/_data.py、DouyinRankingPage.tsx、ClueCenterPage.tsx及API类型。

**完成标准**：四项变更可用，分类计数可分解，权限不扩张，测试、构建、CI、部署和线上冒烟通过。

**Verification Method**：pytest分类/缓存/组织权限回归、npm build、浏览器/Excel实测和生产健康检查。

**Evidence**：开发日志回填真实失败及通过结果、提交、CI及部署链接。

**Failure Handling**：验证失败停止发布；无数据迁移，保留旧版本回滚。

**Owner**：当前Codex任务。

**前置**：用户已确认开发部署及跳过建票。

**状态**：进行中

**完成收尾：状态同步**：回填计划、看板、开发日志及API合同漂移记录。
