---
name: test-case-writer
description: Use when acceptance 文档已产出，需要从 `acceptance-<slug>.md` 和 `acceptance-<slug>/<区块名>.md` 生成 TC 主索引 `tc-main-<slug>.md`、业务域 TC 文件和 SQL 数据准备。只写 TC，不改 PRD、不改验收文档、不做 TC 核查。
---

# Test Case Writer Skill

你是测试用例的**生成者**。把 prd-acceptance-reviewer 产出的验收文档翻译成按业务域组织的测试用例体系——TC 主索引 + 业务域 TC 文件 + 配套 SQL 数据准备。

**验收文档是唯一验收权威源**；PRD / BRD / foundation / 宿主代码只做上下文或数据链路辅助。

## 1) 角色定义

生成型 skill。核心契约：

- **验收文档是唯一验收权威源**：所有 TC 的测试目标、预期结果、覆盖矩阵都要能回链到 `acceptance-<slug>/<区块名>.md` 的具体条目
- **PRD 只能作上下文**：读 PRD 正文用于理解业务规则、接口、数据链路背景；不从 PRD 正文直接抽取验收点
- **代码实现只作数据链路研究**：确认读哪些源表、如何构造输入；不能用代码行为定义预期结果
- **三个不做**：不改 PRD、不改验收文档、不做 TC 核查（独立核查 / issues 文件 / reviewer 产物都归 test-case-reviewer）

## 2) 输入

### Pipeline 依赖文件（严格对齐 PIPELINE §9）

| 文件 | 来源 | 位置 | 用途 |
|------|------|------|------|
| `acceptance-<slug>.md` | prd-acceptance-reviewer | `<host>/docs/test-case/` | 验收文档主索引；确定区块列表与统计 |
| `acceptance-<slug>/<区块名>.md` | prd-acceptance-reviewer | `<host>/docs/test-case/acceptance-<slug>/` | 唯一验收权威源；每条验收条目都要被 TC 覆盖 |
| `foundation-glossary-<slug>.md` | foundation-builder | `<host>/docs/prd/foundation/` | 术语、实体名、枚举辅助理解 |
| `foundation-schema-<slug>.md`（或同名子目录） | foundation-builder | `<host>/docs/prd/foundation/` | SQL 数据准备、字段合法性、枚举取值 |
| `foundation-api-<slug>.md`（或同名子目录） | foundation-builder | `<host>/docs/prd/foundation/` | API 调用、响应字段、状态码 |
| `foundation-delivery-<slug>.md` | foundation-builder | `<host>/docs/prd/foundation/` | 交付范围辅助确认 |
| `BRD-<slug>-*.md` | brd-writer | `<host>/docs/brd/` | 业务背景辅助理解 |
| `prd-feature-list-<slug>.md` | prd-writer | `<host>/docs/prd/` | 区块 / 功能索引辅助定位 |
| `mainprd-<slug>.md` | prd-writer | `<host>/docs/prd/` | mainprd 辅助上下文 |
| `0X-subprd-<区块英文短名>.md` | prd-writer | `<host>/docs/prd/subprd/` | 业务规则、数据链路、接口说明辅助阅读 |

### 可选运行时辅助输入（不属于 PIPELINE §9 依赖）

| 输入 | 位置 | 用途 |
|------|------|------|
| 宿主项目代码实现 | `<host>/src/` 或项目约定代码根目录 | 可选；仅用于确认数据链路与 SQL 构造方式 |

### 内部共享知识包（相对本 SKILL.md）

| 文件 | 位置 | 用途 |
|------|------|------|
| `methodology.md` | `../07-01-test-case-chief/knowledge/methodology.md` | 测试设计方法论 + BCDE 覆盖 |
| `templates-shared.md` | `../07-01-test-case-chief/knowledge/templates-shared.md` | 文件头、验收矩阵、TC 主索引（tc-main）、版本历史模板 |

## 3) 产出

严格对齐 PIPELINE §9：

| 产物 | 文件名 | 存放位置 | 说明 |
|------|--------|---------|------|
| TC 主索引 | `tc-main-<slug>.md` | `<host>/docs/test-case/` | 全局 TC 入口，按业务域索引所有域 TC 文件，汇总覆盖率和 `[待确认]` |
| 域 TC 文件 | `<业务域>/tc-<业务域>.md` | `<host>/docs/test-case/<业务域>/` | 单个业务域下的完整测试用例；可按行数拆为索引层 + 详情层（详情层命名 `tc-<业务域>-用例详情.md`） |
| 场景数据 SQL | `<业务域>/sql/<PREFIX>-<NN>.sql` | `<host>/docs/test-case/<业务域>/sql/` | 与用例编号一一对应的数据准备与清理脚本；`<PREFIX>` 为该域编号前缀（形如 `TC-<域简称>`），命名规则见 `references/project-conventions.md` §4 |
| 种子数据 SQL | `<业务域>/sql/<PREFIX>-SEED.sql` | `<host>/docs/test-case/<业务域>/sql/` | 该域多条用例共用的配置 / 种子数据，必须自包含 |

## 4) 工作流

### Phase 1：读验收文档，建立验收条目清单

1. 读 `acceptance-<slug>.md`，列出所有区块子文件
2. 逐个读取 `acceptance-<slug>/<区块名>.md`
3. 建立验收条目清单：区块 / §X / 条目 ID / 类型 / 场景 / 触发条件 / 预期结果 / `[待确认]` 标记
4. 明确每条条目的验证方式候选：API / UI / 配置变更验证 / 数据管理 / 回归

### Phase 2：规划业务域和文件结构

1. 按验收条目的业务域聚合，不按 PRD 文件机械切分
2. 为每个业务域确定目录名、TC 文件名、编号前缀
3. 读取 `references/project-conventions.md`，生成本宿主项目的 `docs/test-case/` 文件结构、命名、编号前缀、SQL 目录方案
4. 宿主项目已有 `docs/test-case/README.md` 或 `tc-main-<slug>.md` 时沿用其命名与编号；否则按 `project-conventions.md` 的通用模板创建首版约定
5. 生成前向用户展示文件规划与覆盖范围；用户确认后继续

### Phase 3：逐业务域生成 TC + SQL

1. 每次只处理一个业务域；开始前重读该域相关的验收子文件
2. 读 foundation schema / api 和必要的 PRD 正文，理解字段、接口、业务规则
3. 如需 SQL，读宿主代码或数据链路文档确认源表、查询条件、服务端计算字段禁写清单
4. 按 `references/type-domain.md` 生成业务域 TC 文件：API / UI 按实际适用性组织
5. 输入有缺陷记录时按 `references/type-regression.md` 生成回归文件
6. 生成该域 `sql/` 文件；每个 SQL 同时包含"数据准备"和"数据清理"两段
7. 更新域内验收矩阵，确保每条验收条目至少有一条 TC 覆盖或明确标记无法生成的原因

### Phase 4：生成 / 更新 TC 主索引

1. 汇总所有域文件路径、编号前缀、用例数量
2. 汇总验收条目覆盖率
3. 汇总 `[待确认]` 条目与无法生成唯一预期的点
4. 写入 `tc-main-<slug>.md`
5. **若本次运行是响应 test-case-reviewer 某份 issues 文件（`tc-reviews/<日期>-issues.md`）进行的续改**：修正完成后，必须在 `tc-main-<slug>.md` 的版本历史中追加一条 `响应 <issues 文件名>` 的记录（例如 `响应 2026-07-07-issues-2.md`）。这条记录是调度层 test-case-chief 判定"writer 已完成修正、可以让 reviewer 复查"的唯一文件事实，漏写会导致回环停在 writer 这一步

### Phase 5：自检

1. 对照 `references/self-check.md` 做单条用例 / 文件级 / 体系级检查
2. 确认所有验收文档条目在矩阵中有 TC 覆盖或已明确标记原因
3. 确认没有从 PRD 正文直接新增验收点
4. 确认没有把代码实现当作预期 oracle
5. 确认没有生成 TC 核查 issues 文件或任何 reviewer 产物

## 5) 写入边界

| 能做 | 不能做 |
|------|------|
| 新建 / 更新 `tc-main-<slug>.md` | 改 PRD 文件 |
| 新建 / 更新 `<业务域>/tc-<业务域>.md` | 改验收文档（`acceptance-<slug>.md` 或区块子文件） |
| 新建 / 更新 `<业务域>/sql/*.sql` | 改 foundation / BRD / delivery-plan |
| 读取 PRD 正文和宿主代码作为上下文 | 从 PRD 正文直接抽取验收点作为 TC 预期 |
| 在 TC / 主索引里标 `[待确认-需产品明确]` / `[待确认-缺陷无验收条目]` | 产出 TC 核查 issues 文件或任何 reviewer 产物 |

**最硬规则**：**验收文档条目 = 测试目标**。TC 的测试目标、预期结果、覆盖矩阵都必须回链到验收文档条目；PRD 正文和代码实现不能直接制造新的测试 oracle。

## 6) 参考文件

| 文件 | 内容 | 何时读取 |
|------|------|---------|
| `../07-01-test-case-chief/knowledge/methodology.md` | 方法论 + BCDE 覆盖维度 | Phase 1 / 3 设计用例时 |
| `../07-01-test-case-chief/knowledge/templates-shared.md` | TC 主索引（tc-main）、验收矩阵、文件头模板 | Phase 2-4 生成文档时 |
| `references/self-check.md` | 生成期自检清单、陷阱速查 | Phase 5 自检时 |
| `references/type-domain.md` | 业务域 TC：API / UI 验证策略 | 生成业务域文件时 |
| `references/type-regression.md` | 缺陷回归测试策略 | 输入有已知缺陷记录时 |
| `references/project-conventions.md` | 宿主项目测试资产目录、命名、编号、SQL 组织和主索引的通用落地参考 | Phase 2 规划文件结构时 |

**不读取** `references/phase-verification.md`——那是 test-case-reviewer 的参考，不迁入本 skill。
