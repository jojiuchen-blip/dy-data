# DYDATA-90 中心投影缺口增量交付计划

> **版本**：v1
> **发布日期**：2026-09-10
> **适用范围**：正式分配 worker 的历史 active/pending 主线索中心投影回补
> **开发模式**：isolated-worktrees
> **上游发现结论**：增量物化没有覆盖无新 JobImpact 的历史缺中心主线索

## 0. 本计划使用指南

1. 先读取本主开发计划，确认 T0.4 的边界、契约、验证和回滚条件。
2. 再打开任务看板和 T0.4 子开发计划，按子计划执行 worker 与回归测试。
3. 本计划只覆盖中心投影缺口，不改 API 路由、前端、生产数据和全域 cockpit。

### 0.1 PRD 加载约束

- 先读 `docs/prd/mainprd-dy-data.md` 建立全局地图。
- T0.4 只读取子开发计划列出的 BRD、Foundation J01/J03 和状态解析约束。

### 0.2 读前门禁 / AI 自检清单

- 当前 Task 必须能从任务看板定位到 T0.4 子开发计划。
- 子开发计划必须声明 PRD 双链、核心逻辑、核心文件、完成标准和 Verification Method。
- 正式分配的中心存在、订单/券证据、formal/legacy 防重、总部池限制和排他锁属于不可放松的既有门禁。

### 0.3 完成前验证门禁

- 必须完成 T0.4 子计划中的 SQLite 专项和独立 PostgreSQL 缺中心回归。
- 必须执行 `git diff --check`，并把结果与真实 PostgreSQL 是否执行分开记录。
- 不以生产数据写入或部署代替代码和测试证据。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Python | >= 3.12 | `python --version` |
| PostgreSQL | 独立测试库，可选 | `python -m pytest -q tests/test_formal_allocation_runtime_postgres.py -k missing_center_with_coupon` |

## 1. 差距基线

生产发现 234 条 active/pending 主线索缺少 `clue_center_orders`，其中 215 条按当前订单、核销和券证据解析仍为 active。当前 `priority_daily` 使用增量物化路径；中心阶段只消费本轮 JobImpact closure 中的 `order_id`，历史主线索没有新的 impact 时不会进入中心投影。正式分配 runtime 又把中心行作为硬资格门槛，因此这些线索稳定落在候选查询之外。

| 差距 | 影响 | 对应任务 | 状态 |
|---|---|---|---|
| 历史 active/pending 主线索缺中心行 | 正式分配候选查询永远看不到这些订单 | T0.4 | 实现与专项验证完成，待整合验收 |

## 2. 分工与边界

| 角色 | 职责 |
|---|---|
| AI | 执行 worker 回补、测试、计划证据和独立提交 |
| 主代理 | 生产调查、整合提交、全仓验证和最终验收 |
| DYDATA91 | API/前端展示下界及其文档 |

## 3. 执行阶段

### Phase 0：DYDATA-90 缺中心投影回补

**Entry Criteria**：T0.3 正式分配闭环已存在；生产调查已确认缺中心存量；独立 worktree 已建立。

**Exit Criteria**：T0.4 通过 SQLite 与独立 PostgreSQL 缺中心回归；不改变 API、前端或生产数据。

| Task | 子开发计划 | 状态 | 完成日期 |
|---|---|---|---|
| T0.4 | [sub-delivery-plan-dydata-90-projection-gap-T0.4.md](sub-delivery-plan-dydata-90-projection-gap-T0.4.md) | 进行中 | 2026-09-10 |

## 4. 任务看板

- 看板入口：[task-kanban-dydata-90-projection-gap.md](task-kanban-dydata-90-projection-gap.md)

## 5. 发布闸门

- [x] T0.4 的 SQLite `Verification Method` 已执行。
- [x] 缺中心 + 有效券 + 正式分配 + 重跑幂等的独立 PostgreSQL 回归已执行。
- [ ] 主代理整合后完成计划、看板、子开发计划状态回写。
- [ ] 生产部署、生产补偿观察和 215 条存量实际恢复由主代理整合阶段执行。

## 6. 风险与应对

| 风险 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| 订单状态为支付成功但缺有效券证据 | 误建中心或误分配 | 先复用物化器解析；不满足 active 时不投影 | AI | 已覆盖 |
| 首部历史行终态或来源异常 | 饿死后续有效行 | 独立持久 cursor 推进、末尾回绕 | AI | 已覆盖 |
| 物化/投影超过批次预算 | 补偿阻塞正式分配 | 每批最多 100 条、阶段 deadline、PG statement/lock timeout | AI | 已覆盖 |
| 已有 formal/legacy 轮次或总部池 | 重复投放 | 保留原 `_eligible()`、历史轮次和总部池排除 | AI | 已覆盖 |
| 生产补偿循环未运行 | 存量恢复延迟 | 上线后由 priority_daily 定时补偿；必要时按同一 max_items/deadline 受控启动 | 主代理 | 待生产观察 |

## 7. AI 执行示例

1. 从任务看板选择 T0.4，加载本子计划和列出的 PRD。
2. 在独立 worktree 执行回补代码与专项回归，不运行生产写入。
3. 先跑 SQLite，再用独立 PostgreSQL schema 验证缺中心订单的中心创建、首次正式分配和重跑幂等。
4. 将 commit、测试结果和未执行的生产动作交给主代理整合。

## 8. PRD → 任务反向索引

| PRD | Task | 子开发计划 |
|---|---|---|
| `docs/prd/mainprd-dy-data.md` §1 | T0.4 | [sub-delivery-plan-dydata-90-projection-gap-T0.4.md](sub-delivery-plan-dydata-90-projection-gap-T0.4.md) |
| `docs/prd/foundation/foundation-api-clue-center/jobs-security-and-migration.md` J01/J03 | T0.4 | [sub-delivery-plan-dydata-90-projection-gap-T0.4.md](sub-delivery-plan-dydata-90-projection-gap-T0.4.md) |

## 完成收尾：状态同步

- T0.4 实现基础提交：`c69072ec`；本次 PostgreSQL 回归和计划文件增量提交待主代理整合。
- 本次没有修改 `docs/devlog/20260910_refactor_log_Keith_Chen.md`，不执行生产写入、部署或手工数据修复。
- 生产上线后的 215 条存量恢复由 priority_daily 的有界补偿逐页处理；5620 条 `legacy_engine_retired` 历史轮次继续排除。


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
