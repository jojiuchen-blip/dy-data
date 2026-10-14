# T0.1 磁盘与榜单生命周期

- 主开发计划：[主计划](main-delivery-plan-disk-ranking-retention.md)
- 任务看板：[看板](task-kanban-disk-ranking-retention.md)

#### T0.1 磁盘与榜单生命周期
**Requirement ID**：用户2026-10-09明确授权清理与开发，无需Linear。
**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` §全局设计规则
**核心逻辑**：导出读取匹配范围的最新成功版本，只记访问时间、不重算，无快照则提示先刷新；刷新无源变化复用（覆盖时间驱动指标）；普通版本留最新两版、短期读保护、过期查询范围淘汰；关键版本显式归档，不擅定业务时点。备份默认预演、路径与保留校验、成功备份后淘汰、容量门禁和通用协作规则。先清理旧备份，数据库清理分批可恢复且不把逻辑删除称为空间回收。
**核心文件**：ranking_business.py、ranking_lifecycle.py、dashboard.py、Alembic迁移、维护脚本、tests、AGENTS.md、docs/rules。
**完成标准**：静态导出不新增榜单事实；源变化和时间边界触发刷新；普通保留和归档保护正确；备份清理不越界且保留有效恢复点；测试通过，线上与本地状态明确。
**Verification Method**：针对性pytest、PostgreSQL事务/迁移验证、完整pytest及Web构建、生产清理前后空间和健康检查。
**Evidence**：[清理与验证记录](../../devlog/20261009_disk_ranking_retention.md)，含全量初轮、失败项复验、专项、迁移和 PostgreSQL 并发验证。
**Failure Handling**：校验失败停止删除；不截断业务表，不执行磁盘不足下的全表重写。
**Owner**：主线程与隔离备份worker。
**前置**：用户确认方案并授权执行。
**状态**：进行中（清理、开发、main 合并、部署及技术验收已完成；待业务使用验收）
**完成收尾：状态同步**：同步计划、看板、开发日志及契约。
