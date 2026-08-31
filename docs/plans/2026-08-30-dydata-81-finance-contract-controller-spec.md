# DYDATA-81 财务页面合同实现 Controller Spec

Status: Active
Date: 2026-08-30
Controller: Codex 主控
Repo / workspace: dy-data 隔离工作树
Branch / target: `codex/dydata-81-finance-contract` -> PR -> `main` -> 受控腾讯云生产发布

## 1. User Goal

在主系统一级“财务”下，把推广服务费、管理服务费、订单明细、门店基础信息、SAP/账单异议和导入记录六类页面逐项对齐已冻结页面合同；业务数据仅来自正式 API、正式 Schema 和 Linear 已确认规则。完成实现、自动化验证、三视口 UAT、正式接口冒烟、PR/CI，并且只有全部发布门禁通过时才部署生产。生产验证后保持 DYDATA-81 未关闭，等待用户验收。

## 2. Current Evidence

| Area | Evidence | Source | Confidence | Notes |
|---|---|---|---|---|
| 页面合同 | 冻结提交为 `9a574faf33acf9200e9d35401580e65468aa61e6` | `codex/dydata-19-finance-mock`、`docs/prototypes/dydata-19-finance-flow-dashboard/` | High | 只约束页面内部结构/交互；演示数据不进入正式系统 |
| 视觉骨架 | Shell、导航、token、组件与响应式沿用主应用 | Linear DYDATA-81 最新评论；`docs/design-system/` | High | 不复制原型私有 CSS |
| 金额口径 | 推广费五卡及待开票口径、双方向结算状态已由用户确认 | DYDATA-81 2026-08-30 评论；DYDATA-31 | High | 列表、汇总、导出必须一致 |
| SAP | 财务导入值直接成为有效 SAP；保留门店原值、财务值、操作人、时间、版本；支持单条矫正 | DYDATA-81 2026-08-30 评论 | High | 历史账单/订单快照不回写 |
| 异步检测 | 状态、进度、结果、失败原因必须来自正式 API，刷新后可追溯 | DYDATA-81 2026-08-30 评论 | High | 自动检测只输出数据一致性证据，不替代管理员业务裁决 |
| 正式实现 | 六页、财务查询/导入/异议 API 和不可变版本基础已存在 | `apps/web/src/pages/Finance*.tsx`、`apps/api/dy_api/routes/dashboard.py` | High | 当前布局、字段、SAP 生效与异步检测仍有差异 |
| 已知发布阻塞 | 异议证明材料没有受控上传/读取/清理接口，存储策略未定义 | Linear DYDATA-82 | High | 若发布前仍未定义且影响本轮真实闭环，则停止部署 |

## 3. Scope

Included:

- 六个管理员财务页面的模块顺序、筛选、表头、状态、按钮、空/错/无权态和跳转。
- 推广费五卡口径；推广/管理订单结算状态的服务端统一筛选。
- 四类导入对应业务页入口、真实模板下载、基础信息/SAP 差异导出、导入记录只读入口。
- 财务导入 SAP 直接生效、单条 SAP 矫正、版本与审计回读。
- 账单异议真实异步数据一致性检测任务、持久化进度/结果/失败原因及刷新追溯。
- 正式 API/Schema/Foundation、类型、迁移、测试、UAT、PR/CI、受控发布与回滚证据。

Excluded:

- 演示金额、日期、门店、发票、SAP、状态或假成功。
- 真实开票、厂端审核、资金划拨、模糊匹配或历史事实覆盖。
- 未经定义的对象存储策略、手工生产数据库修改、绕过 CI/迁移/备份/权限。
- DYDATA-83/84 的门店端发票扩展，除非验证证明是六个管理员财务页面的直接发布依赖。

Scope control rule:

- 缺少 Linear/正式 Schema 依据且会改变金额、状态、有效值、权限或历史事实的规则，标记 BLOCKED 并停止相应发布；不得在前端推导。

## 4. Assumptions and Open Questions

| ID | Item | Type | Owner | Resolution |
|---|---|---|---|---|
| A1 | 异步检测的自动结论边界 | Assumption | Controller | 只核对正式数据库中异议订单范围、金额合计、账单版本与冻结分录一致性；不自动判定异议成立/不成立，管理员处理状态机保持不变 |
| A2 | SAP 有效值优先级 | Assumption | Controller | 最新一次财务导入或财务单条矫正成为当前有效值；后发生操作覆盖当前指针但永久保留旧版本与审计；历史账单快照不变 |
| A3 | 模板下载示例数据 | Assumption | Controller | 生产模板仅输出已冻结正式字段表头和填写说明，不包含原型示例值 |
| Q1 | DYDATA-82 对本轮生产放行的影响 | Question | Controller / User | 发布前按真实闭环验证；若仍缺安全定义且构成门禁，停止部署并集中报告 |
| Q2 | 目标正式接口 UAT 是否具备安全可写样例 | Question | Controller | 无受控样例时只做读/预校验/回滚安全验证，不在生产制造业务数据 |

## 5. Work Breakdown

| Task ID | Role | Owner | Responsibility | Write Set | Inputs | Required Output | Acceptance Gate |
|---|---|---|---|---|---|---|---|
| T0 | Controller | 主控 | 计划、权威边界、状态与证据 | `docs/plans/`、`project-profile.md`、`docs/devlog/` | Linear、PRD、Foundation、冻结看板 | 计划三件套与 S4 一致 | 治理/计划校验通过 |
| T1 | Implementer | 后端 worker | 财务查询、筛选、导出、SAP、异步检测 | `apps/api/`、`alembic/`、后端专项测试、API/Schema 文档 | §2～§4 | 失败测试、最小实现、迁移与 API 证据 | 定向 API/迁移测试通过 |
| T2 | Implementer | 前端 worker | 六页合同对齐 | `apps/web/src/pages/Finance*`、相关组件/类型/样式、前端专项测试 | 冻结页面、T1 API 契约 | 六页实现和前端测试 | 构建及静态合同测试通过 |
| T3 | Spec Reviewer | 独立 reviewer | 合同范围与业务边界复审 | Read-only | 本规格、diff、合同矩阵 | 缺失/越界清单 | Critical/Important 为 0 |
| T4 | Code Quality Reviewer | 独立 reviewer | 数据正确性、安全、迁移与回归复审 | Read-only | diff、测试、迁移 | 按严重度的发现 | 无发布阻塞发现 |
| T5 | Verifier | 独立 verifier | 三视口 UAT、正式接口、全量门禁 | Read-only evidence | 构建、运行时、测试账号/安全 fixture | 截图、GWT、命令结果 | 全部门禁通过或明确 BLOCKED |
| T6 | Controller | 主控 | PR/CI/部署/线上验证/Linear 回填 | 发布工作流与文档 | T3～T5 结论 | commit、PR、CI、部署、回滚和 smoke | 仅在所有硬门禁通过时部署 |

## 6. Subagent Task Packets

### T1: 后端合同与数据正确性

Role: Implementer

Context:

- 页面字段和动作必须由正式服务端事实支撑。

Ownership:

- 财务查询/导入/异议 API、模型、迁移、Foundation API/Schema 和后端专项测试。

Non-goals:

- 不编辑前端页面；不定义新的业务金额或自动异议裁决。

Required output:

- 每个行为先给出红灯测试和预期失败。
- 文件变更、迁移升级/降级、命令与结果。
- SAP 前后快照、版本、操作人和时间证据。
- 异步检测状态机、恢复读取和失败路径证据。

Acceptance gate:

- 列表/导出/汇总同口径；导入原子性、权限、幂等、并发和历史不可变回归通过。

### T2: 六页前端合同

Role: Implementer

Context:

- 主应用视觉骨架不变，内部模块与冻结合同逐项映射。

Ownership:

- 六页组件、共用导入动作、类型/客户端、财务样式和前端专项测试。

Non-goals:

- 不在前端计算财务金额、权限或异议结论；不写演示数据。

Required output:

- 每页模块/筛选/表头/按钮/状态/空错态对应关系。
- 失败测试、构建和自审结果。

Acceptance gate:

- 六页逐项合同无缺失；390/768/1440 无全局横向溢出，宽表仅在表容器内部滚动。

### T5: 独立验证

Role: Verifier

Context:

- 自动化通过不能替代页面合同和正式接口证据。

Ownership:

- 只读验证、截图、GWT、运行日志、发布门禁判定。

Non-goals:

- 不修代码、不扩大权限、不制造生产财务数据。

Required output:

- 环境、版本、命令、退出码、三视口截图、API 请求/响应摘要和 BLOCKED 项。

Acceptance gate:

- 每个关键动作均有 Given/When/Then、用户可见结果、API 事实、版本/审计证据。

## 7. Review Plan

1. 每个实现切片先自审。
2. 规格复审检查合同缺失与越界。
3. 规格通过后进行代码质量、数据正确性与安全复审。
4. 仅对确认问题做最小修复。
5. 每次修复后重跑对应规格/质量复审与定向测试。

## 8. Verification Plan

| Gate | Command / Method | Owner | Required For Done | Notes |
|---|---|---|---|---|
| Diff | `git diff --check`、范围 diff | Controller | Yes | 无无关改动 |
| 后端 | 定向 pytest + `python -m pytest` | Controller/Verifier | Yes | 基线与最终均记录 |
| 前端 | 静态合同测试 + `npm --prefix apps/web run build` | Controller/Verifier | Yes | 不启用 demo |
| 迁移 | Alembic 单头、空库往返、目标 PostgreSQL 受控升级检查 | Controller/Verifier | Yes | 不手工改库 |
| 浏览器 | Playwright 390/768/1440、加载/空/错/无权/写操作 | Verifier | Yes | 截图版本可追溯 |
| UAT API | 隔离 UAT 使用正式 API | Controller/Verifier | Yes | 禁止 Mock/fixture 冒充正式接口 |
| 治理 | suite lock、global files、plan structure/consistency、S4 route | Controller | Yes | 三处状态一致 |
| 发布 | PR checks、main CI、受控腾讯云 workflow、线上 smoke | Controller | If gates pass | 任一失败即不部署/回滚 |

## 9. Final Acceptance Checklist

- [ ] 用户目标与六页合同满足。
- [ ] 所有 BLOCKED 项已关闭或明确阻断发布。
- [ ] 后端与前端规格复审通过。
- [ ] 代码质量与数据正确性复审通过。
- [ ] 全量测试、构建、迁移、治理、三视口 UAT 与正式接口冒烟通过。
- [ ] 工作树和 diff 无无关改动。
- [ ] commit、PR、CI 与远端同步结果记录。
- [ ] 如部署：备份、部署 SHA、线上验证与回滚目标记录。
- [ ] Linear 已回填，DYDATA-81 保持未关闭，等待用户验收。

## 10. Decision Log

| Time | Decision | Reason | Evidence |
|---|---|---|---|
| 2026-08-30 | 旧“仅导航/不改 API”范围被本轮书面授权覆盖 | 用户明确授权六页合同的前后端、UAT 与受控生产实现 | DYDATA-81 评论 `ec78f24f-45fd-4b87-8607-61c5dfc83fb0` |
| 2026-08-30 | 不复用门店端脏工作树 | 避免覆盖并行任务未提交内容 | `git worktree list` / `git status` |
| 2026-08-30 | 异步检测不自动作出业务裁决 | DYDATA-19 管理员状态机仍是成立/不成立唯一裁决入口 | SubPRD 8 / Foundation API §3 |

## 11. Change Log

| Time | Change | Owner | Evidence |
|---|---|---|---|
| 2026-08-30 | 建立 G5 财务页面合同实现控制规格 | Codex 主控 | 本文件 |
