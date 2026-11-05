# T0.1 北星基础编码补齐

## 任务来源

- [main-delivery-plan-dydata114.md](main-delivery-plan-dydata114.md)
- [task-kanban-dydata114.md](task-kanban-dydata114.md)

#### T0.1 精确补基础编码

**Requirement ID**：DYDATA-114

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` 全局设计规则
- `docs/prd/foundation/foundation-schema-dy-data/existing-read-dependencies.md` 门店与 POI

**核心逻辑**：
- AI 执行 -> 人审核。用户确认 BYDSC133W，组织历史同码且 POI 一致。只在基础编码为空、无其他店占用时写入；已有正确值幂等跳过，其他值拒绝。
- 不新增店、不覆盖组织版本、不改变 POI 和行政区域。县区暂无对应基础字段，不把新都区误填为业务区域。
- 事务内锁定目标、校验组织与 POI，保存修改前行至权限受限的生产专项证据文件；完成后读回。

**核心文件**：
- `scripts/ops/repair_dydata114_store_code.sql`
- `docs/devlog/20261105_dydata114_history.md`

**完成标准**：
- 只更新目标一行或正确幂等；错误编码、重复编码、组织/POI 不符时失败回滚。
- 生产读回基础编码与组织编码一致，现有门店 ID 和 POI 保持。

**Verification Method**：
- 只读校验、事务预演、生产受限执行及独立读回；git diff --check。

**Evidence**：`docs/devlog/20261105_dydata114_history.md`，仅记录脱敏结果与生产证据路径。

**Failure Handling**：断言失败不提交；保留前值与错误，不扩大更新范围。

**完成收尾：状态同步**：完成后同步主计划、看板、子计划并重跑一致性检查。

**Owner**：AI 执行 -> 人审核

**前置**：无

**状态**：已完成
