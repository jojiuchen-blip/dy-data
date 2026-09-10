# DYDATA-91 Clue Visibility Delivery Plan

> **版本**：v1
> **发布日期**：2026-09-10
> **适用范围**：线索看板 `/clues`、线索明细 `/clues/details` 及其查询汇总
> **开发模式**：isolated-worktrees
> **上游发现结论**：canProceed=true, slug=dy-data

## 0. 本计划使用指南

1. 先读取本主开发计划，确认阶段顺序、任务索引、发布闸门与风险。
2. 再打开任务看板，定位当前 Task 对应的子开发计划。
3. 执行前只加载当前 Task 的子开发计划和 `PRD 双链·读` 指向的真实文件。

### 0.1 PRD 加载约束

- 先读 `docs/prd/mainprd-clue-center.md` 建立线索中心全局地图。
- 每个 Task 只读取子开发计划中列出的 PRD、foundation 和实际代码文件。

### 0.2 读前门禁 / AI 自检清单

- 当前 Task 必须能从任务看板定位到一个子开发计划。
- 子开发计划必须声明 `PRD 双链·读`、`核心逻辑`、`核心文件` 和 `完成标准`。
- 生产行为只能按正式分配时间过滤；来源生成时间、首次分配资格、财务和后台审计不得被此任务改写。

### 0.3 完成前验证门禁

- 完成前必须执行子开发计划里的 `Verification Method`。
- 证据必须写入子开发计划的 `Evidence` 指定位置。
- 集成前必须复核列表、汇总、详情、导出、清空筛选与账号范围的边界一致性。

## 当前驾驶舱

| 字段 | 内容 |
|---|---|
| 当前活跃 Phase / Task | T0.1 DYDATA-91 线索可见分配日期下界 |
| 当前子开发计划 | [sub-delivery-plan-dydata-91-visibility-T0.1-clue-visibility.md](sub-delivery-plan-dydata-91-visibility-T0.1-clue-visibility.md) |
| 隔离分支 | `codex/dydata-91-visibility` |
| 可见下界 | 上海时间 `2026-09-01 00:00:00`，按 `assigned_at` 且包含边界 |

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Node.js | >= 18 | `node -v` |
| Python | >= 3.12 | `python --version` |

## 1. 差距基线

| 差距 | 影响 | 对应任务 | 状态 |
|---|---|---|---|
| 线索查询面未统一正式分配日期下界 | 清空日期或跨月订单可能显示旧轮次，筛选项、列表、汇总和详情口径不一致 | T0.1 | 处理中 |
| 演示样例仍使用历史日期 | 新下界会令静态演示数据不可见，无法引导 `/clues` 和 `/clues/details` | T0.1 | 处理中 |

## 2. 分工与边界

| 角色 | 职责 |
|---|---|
| 本 Task | 线索查询/API、前端 demo/mock 可见过滤、专项测试与证据 |
| 主代理 | DYDATA-90 生产只读验收、交接日志、集成和最终验收 |
| 人类 Owner | 已确认“8 月产生、9 月正式分配仍显示”，以分配日期为准 |

## 3. 执行阶段

### Phase 0：DYDATA-91 线索可见范围

**Entry Criteria**：线索中心 PRD、foundation API/schema、实际路由文件和隔离 worktree 已确认。

**Exit Criteria**：T0.1 的服务端和演示查询面按同一上海正式分配下界工作，专项测试和构建证据已落盘。

| Task | 子开发计划 | 状态 | 完成日期 |
|---|---|---|---|
| T0.1 | [sub-delivery-plan-dydata-91-visibility-T0.1-clue-visibility.md](sub-delivery-plan-dydata-91-visibility-T0.1-clue-visibility.md) | 进行中 | - |

## 4. 任务看板

- 看板入口：[task-kanban-dydata-91-visibility.md](task-kanban-dydata-91-visibility.md)

## 5. 发布闸门

- [ ] T0.1 的 `Verification Method` 已执行并记录命令结果
- [ ] 8 月 31 日 23:59:59 隐藏、9 月 1 日 00:00 保留、清空筛选不泄漏已验证
- [ ] 跨月来源、同订单旧轮次、分页/导出、财务隔离已验证
- [ ] 任务看板、子开发计划和驾驶舱状态一致

## 6. 风险与应对

| 风险 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| 旧轮次与新轮次共用一个订单 | 详情可能把旧动作带回用户面 | 详情轮次和跟进记录按同一 `assigned_at` 下界过滤；后台审计沿用独立路径 | 本 Task | 处理中 |
| 静态 mock 与 demo repository 口径漂移 | 演示与真实 API 显示不同 | 共享前端可见判断，静态样例迁到 9 月 | 本 Task | 处理中 |
| 过滤下界影响资格或财务 | 业务写入、财务金额或历史审计变化 | 只在 clue user-facing 查询和汇总路径加条件，保留写入与后台 ORM 路径 | 本 Task | 持续约束 |

## 7. AI 执行示例

1. 从任务看板选择 T0.1。
2. 打开 T0.1 对应的子开发计划，核对 PRD 双链和实际路由。
3. 在隔离分支实现查询下界、演示数据过滤和专项测试。
4. 执行子计划中的验证命令，回写证据并交主代理集成。

## 8. PRD → 任务反向索引

| PRD / Foundation | Task | 子开发计划 |
|---|---|---|
| [mainprd-clue-center.md](../../prd/mainprd-clue-center.md) §1 | T0.1 | [sub-delivery-plan-dydata-91-visibility-T0.1-clue-visibility.md](sub-delivery-plan-dydata-91-visibility-T0.1-clue-visibility.md) |
| [foundation-api-clue-center.md](../../prd/foundation/foundation-api-clue-center.md) Q01/Q02/Q05/Q06/Q07/Q08 | T0.1 | [sub-delivery-plan-dydata-91-visibility-T0.1-clue-visibility.md](sub-delivery-plan-dydata-91-visibility-T0.1-clue-visibility.md) |
| [foundation-schema-clue-center/clue_assignment_round.md](../../prd/foundation/foundation-schema-clue-center/clue_assignment_round.md) §字段/页面映射 | T0.1 | [sub-delivery-plan-dydata-91-visibility-T0.1-clue-visibility.md](sub-delivery-plan-dydata-91-visibility-T0.1-clue-visibility.md) |



## 2026-09-10 主代理整合验收

- 两项业务修复固定后，全仓 `python -m pytest -q --tb=short`：2775 passed、144 skipped、0 failed，耗时29分04秒。完整记录为本地 `output/handoff-full-pytest.log`。
- 后补缺中心专用PG测试：1 passed、2 deselected；整合验证的既有真实PG13项通过。真实PG日期边界及“缺中心→补投影→正式分配→九月API可见”两项场景通过，重跑无重复；前端构建通过。
- 全仓运行后仅追加测试及文档，业务代码保持受测版本。代码 `23ca7287` / `11f974c5`，PG补充 `e633b165`，BRD `5b9192c7`。
- 当前只完成本地交付，未推送或部署；计划保持进行中，剩余发布与用户验收真实存在，不标为业务上线完成。


## 2026-09-10 生产发布验收

- 用户明确授权提交并部署；发布提交 `1e91f4dc`，北京时间15:42:28完成。
- [发布流水线](https://github.com/jojiuchen-blip/dy-data/actions/runs/34448207755)成功：2762 passed / 158 skipped，真实PostgreSQL、Web与镜像构建通过。
- 215条有效遗漏处理为214条正式分配、1条无符合条件门店进入总部池；缺中心与待分配有效候选均0。九月页面2204条，跨月来源482条保留；八月查询0，清空筛选仍保留下界。
- 服务健康、7份运行源码与发布提交一致，重复活动轮次及新增自动超期0；数据库迁移仍0053，备份及回滚镜像已保存。
- 本项生产检查完成，等待用户验收；不自行关闭任务。DYDATA-90的5620条旧引擎退役轮次处置、历史限流恢复与72小时观察继续独立跟进。
