# 开发日志 — 2026-07-21

> 主题：DYDATA-36 线索中心 BRD V1.0 冻结
> 操作人：Keith Chen
> 关联计划：docs/plans/execution-plan.md

---

## 一、执行概要

| # | 任务 | 关联 | 状态 |
|---|------|------|------|
| 1 | DYDATA-36 线索中心 BRD V1.0 冻结 | 本轮推进 | ✅ |
| 2 | DYDATA-41 FOUNDATION 术语阶段 | 补充更新 | ✅ |
| 3 | DYDATA-41 FOUNDATION Schema 阶段 | 补充更新 | ⏳ 待确认 |

**本日关键结论**：生成 docs/brd/BRD-clue-center-20260721-2134.md；专项台账进入 DONE；未修改业务代码。下一步补齐线索中心 FOUNDATION、PRD 和正式交付计划，再进入 DYDATA-34 旧引擎下线

---

## 二、操作详情

### 任务 1：DYDATA-36 线索中心 BRD V1.0 冻结
- **目标**：将已确认的线索中心业务口径、指标和现状追踪矩阵正式落盘，并切换项目状态到下游规格阶段
- **操作**：读取专项台账、两轮 QA、现有规格与当前代码证据；生成并通过 save-brd 结构校验；同步 project-profile、execution-plan 和权威映射；校正治理测试中落后于已验证套件锁的版本期望
- **结果**：生成 docs/brd/BRD-clue-center-20260721-2134.md；专项台账进入 DONE；未修改业务代码。套件、锁文件和安装清单均为 2.0.1 且锁校验有效，治理测试已同步。下一步补齐线索中心 FOUNDATION、PRD 和正式交付计划，再进入 DYDATA-34 旧引擎下线
- **涉及文件**：`docs/brd/BRD-clue-center-20260721-2134.md`、`docs/brd/ledger-state-clue-center.json`、`docs/brd/brd-ledger-clue-center.md`、`project-profile.md`、`docs/plans/execution-plan.md`、`docs/governance/authority-map.md`、`tests/test_project_governance.py`

---

## 三、变更总览

### 文件变更清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `docs/brd/BRD-clue-center-20260721-2134.md` | 冻结线索中心业务模型 V1.0 和现状追踪矩阵 |
| 新建 | `docs/brd/ledger-state-clue-center.json` | 保存专项 BRD 决策状态，当前为 `DONE` |
| 新建 | `docs/brd/brd-ledger-clue-center.md` | 提供专项决策台账只读展示 |
| 修改 | `project-profile.md` | 将当前阶段切换到 FOUNDATION、PRD 与正式交付计划补齐 |
| 修改 | `docs/plans/execution-plan.md` | 更新执行驾驶舱和紧邻下一步 |
| 修改 | `docs/governance/authority-map.md` | 登记线索中心专项 BRD 的业务域权威范围 |
| 修改 | `tests/test_project_governance.py` | 将治理测试版本期望同步到已验证的套件锁 2.0.1 |

> 收口时由 AI 从各任务「涉及文件」聚合去重生成。操作类型：新建 / 修改 / 删除。

### Git 提交记录

| 时间 | Commit | 内容 |
|------|--------|------|

---

## 四、发现的问题 / 缺陷

- 两轮 QA 的结论只证明当前仓库和本地隔离数据状态，不代表生产部署；BRD 追踪矩阵已显式保留该证据边界。
- 总体核销率新口径、自动正式分配闭环、地理数据质量和旧引擎删除仍需下游规格与交付计划承接。

---

## 五、复盘

### 做得好的
- 业务定义与当前实现状态分栏记录，避免把已确认需求误写成已完成能力。
- 追踪矩阵直接引用两轮 QA、控制规格和当前代码路径，保留后续验收入口。

### 遇到的问题
- **现象**：部分能力已有代码和单元测试，但端到端正式分配、生产数据与真实门店运营证据仍不完整。
- **根因**：历史交付以功能点推进，缺少统一业务口径和同一套生产验收数据集。
- **经验**：> 专项 BRD 必须同时冻结目标业务语义和当前实现差距，不能用代码存在代替业务完成。
- **🔧 是否提炼为规则**：⬜ 仅记录

---

## 五·附、方法论沉淀（可选）

> 当天工作中如果有可复用的方法论、设计原则、或跨项目通用的经验，在此抽象记录。
> 普通开发日不需要填写此章节。

---

## 六、待跟进事项

- [ ] 确认 Schema 并继续补齐线索中心 FOUNDATION API、任务、权限与运行方案。
- [ ] 补齐线索中心 PRD。
- [ ] 生成正式交付计划，将追踪矩阵缺口映射到 Linear、代码、测试和上线门禁。
- [ ] S4 门禁通过后执行 DYDATA-34，全面删除旧线索分配引擎。
---

## 补充更新 1（22:21 · 窗口 1）

### 任务 2：DYDATA-41 FOUNDATION 术语阶段
- **目标**：以已冻结线索中心 BRD 为权威源建立统一术语，进入 FOUNDATION 技术规格
- **操作**：完成现有模型与接口覆盖评估；生成 foundation-glossary-clue-center.md；将项目画像和执行计划切换到 DYDATA-41 Phase 2
- **结果**：术语表 212 行已落盘并通过 git diff --check；当前等待业务确认，未提前进入 Schema/API，也未修改业务代码
- **涉及文件**：`docs/prd/foundation/foundation-glossary-clue-center.md`、`project-profile.md`、`docs/plans/execution-plan.md`、`docs/devlog/20260721_refactor_log_Keith_Chen.md`

---

## 补充更新 2（Phase 3 · 窗口 1）

### 任务 3：DYDATA-41 FOUNDATION Schema 阶段
- **目标**：把已确认术语和 BRD 业务规则落成唯一数据模型、状态分层、索引、页面字段来源及一次性迁移边界
- **操作**：读取现有 SQLAlchemy 模型、迁移、页面类型、BRD 与数据库规范；建立 Schema 索引及 23 个单表定义；将现有混合结构拆分为原始证据、业务事实、分配账本、查询投影和操作审计五层
- **结果**：Schema 共 23 张目标表，新增原始线索逐行映射、退款原始证据、联系方式隔离、完整主池指标事实、批次明细和候选快照；明确只迁移新引擎正式轮次并在 DYDATA-34 删除旧引擎，不生成 DDL、不修改业务代码；当前等待业务确认后进入 Phase 4 API
- **验证**：23/23 单表文件齐全；必备三字段、索引定义和使用接口占位完整；索引页 23 个链接有效；所有文档均低于 400 行
- **涉及文件**：`docs/prd/foundation/foundation-schema-clue-center.md`、`docs/prd/foundation/foundation-schema-clue-center/*.md`、`project-profile.md`、`docs/plans/execution-plan.md`、`docs/devlog/20260721_refactor_log_Keith_Chen.md`
