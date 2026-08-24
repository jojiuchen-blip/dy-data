# DYDATA-19 G3 冻结与主线集成日志

## 2026-08-24 G3 冻结

- 关闭账单 Vn+1 未继承明细快照的问题；普通复制行与异议调整行均继承冻结展示字段。
- Alembic 0043 回填历史账单头和订单明细快照，无法确定的数据进入独立异常清单；订单详情只读取账单明细快照，不再回退可变主数据。
- 腾讯云部署脚本在迁移后、服务启动前检查两类未解决快照异常；计数非零或查询失败均中止部署。
- 修复迁移测试隔离：`test_statement_versioning_migration_preserves_and_versions_snapshots` 固定升级到其验证范围的 `20260821_0030`，保留 0043 独立降级保护用例。

## 新鲜验证证据

- 三个迁移隔离/0043 专项：`3 passed`。
- `tests/test_alembic_migrations.py tests/test_deploy_compose_config.py tests/test_frontend_user_facing_contracts.py`：`52 passed, 162 warnings`。
- `npm --prefix apps/web run build`：通过；575.12 kB chunk 为非阻断性能提示。
- `git diff --check`：通过，仅有既有 LF/CRLF 提示。
- `python -m alembic heads`：唯一 head 为 `20260824_0043`。
- 独立定向复审：Critical 0、Important 0、Minor 无新增阻断，`Ready: yes`。

## 下一阶段与停止条件

- 当前旧功能分支相对最新主线存在大量真实冲突和历史 migration revision 内容冲突，不直接硬合并发布。
- 先形成可恢复检查点，再从最新 `origin/main` 建立干净集成分支，保留主线生产迁移历史并重建 DYDATA-19 财务迁移链。
- 全量 pytest、Web build、治理门禁、目标 PostgreSQL 升级/并发、浏览器、CI、备份和生产 smoke 任一失败，立即停止部署并记录证据。
