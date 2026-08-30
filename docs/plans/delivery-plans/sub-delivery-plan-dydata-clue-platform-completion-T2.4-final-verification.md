# T2.4 全量、等价性和 8GB 最终门禁

## 任务来源
- 主开发计划：[main-delivery-plan-dydata-clue-platform-completion.md](main-delivery-plan-dydata-clue-platform-completion.md)
- 任务看板：[task-kanban-dydata-clue-platform-completion.md](task-kanban-dydata-clue-platform-completion.md)

#### T2.4 完成全量回归、影子对比和资源验收

**Requirement ID**：DYDATA-58 T5.2；DYDATA-56/8/14/15/34/70 最终回归

**PRD 双链·读**：
- `docs/superpowers/specs/2026-08-06-dy-data-8gb-safe-sync-control-plane-design.md`
- `docs/prd/mainprd-dy-data.md`
- `docs/prd/foundation/foundation-delivery-dy-data.md`

**核心逻辑**：在相同输入下对比新旧结果；按约生产两倍脱敏数据在 4C/8GB Linux 连续三轮执行；记录峰值 RSS、swap、耗时、行数、失败原因和 API/PG/HTTPS/SSH 可用性。

**核心文件**：全量测试、资源压测脚本、shadow 报告、Compose 配置和最终交付报告。

**完成标准**：全量 pytest、Web build、单迁移头、真实 PostgreSQL、shadow 等价、连续三轮资源门禁全部通过；否则明确阻断项，不把 DYDATA-58 标为完成。

**Verification Method**：`git diff --check`、`python -m pytest`、`npm --prefix apps/web run build`、`python -m alembic heads`，以及 4C/8GB Linux 三轮压测脚本。

**Evidence**：最终报告包含修改文件、调度流程、幂等方案、测试结果、内存对比、部署风险和分阶段上线建议。

**Failure Handling**：任一硬门禁失败则保持 T2.4 进行中并给出可复现证据；不通过增加 swap 掩盖问题。

**完成收尾：状态同步**：通过后同步全部计划和 Linear 状态；生产部署仍使用独立发布授权与 canary。

**Owner**：主代理 -> Human Owner 最终验收

**前置**：T2.3

**状态**：待开发
