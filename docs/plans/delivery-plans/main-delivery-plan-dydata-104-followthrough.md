# DYDATA-104：自然月、九月恢复与静态发布验收

> **版本**：v2
> **发布日期**：2026-10-20
> **适用范围**：已有 DYDATA-104；承接 DYDATA-97/102/103 的未验收项，不重复重做已修复内容。
> **开发模式**：团队协作，Codex 执行与集成，用户业务验收。
> **上游发现结论**：canProceed=true，slug=dy-data；2026-10-20 10:59 +08 在统一 main 新工作树重新扫描，无失败分支；大文件按相关章节读取。
> **授权**：用户已确认先整合 #50/#51，再由 Codex 在统一 main 上执行；不创建新 Linear，不改原工作区未提交内容。
> **来源**：[DYDATA-104](https://linear.app/keith-lim/issue/DYDATA-104)；既有 [九月计划](main-delivery-plan-dydata-102-september.md) 与 [静态发布计划](main-delivery-plan-unified-dashboard-publications.md) 保留历史证据。
> **代码基线**：`main@05a7e2455d3883d0587b3dcf8bd8f014cd7b579f`；#50、#51 已合并，最终树与 #51 已通过 CI 的树一致。

## 0. 本计划使用指南

先核对统一 main 和当前 Task，再读取子计划及其 PRD 双链。历史成功不能替代当前生产业务验收。

### 0.1 PRD 加载约束

- `docs/prd/mainprd-dy-data.md` 全局规则
- `docs/prd/subprd/02-subprd-store-settlement.md` §3–4
- `docs/prd/subprd/03-subprd-order-fee-details.md` 筛选与导出
- `docs/prd/subprd/05-subprd-finance-promotion.md` §3
- `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md` 账单/财务契约
- `docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md` 费用、调整与冻结来源
- `docs/api/dashboard-publications.md` 不可变发布与读取

### 0.2 读前门禁 / AI 自检清单

- PR #50 / #51 的最终提交通过 CI；独立工作树从合并后的 main 建立。
- 用户已授权执行，无需再次确认同一范围；未知金额契约不凭授权猜测。
- suite 锁、全局文件、计划结构/一致性、环境及当前任务门禁通过。

### 0.3 完成前验证门禁

定向回归、实际 PG、完整 CI、前端构建、真实页面/下载与生产证据分开记录。源码完成、合并、部署、业务验收是不同状态。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Python | 项目兼容版本 | `python -V` |
| Node.js | 项目兼容版本 | `node -v` |
| Docker | 本地隔离 PG 与限额验证 | `docker info --format "{{.ServerVersion}}"` |

## 1. 差距基线

| 差距 | 证据与影响 | 对应任务 | 状态 |
|---|---|---|---|
| 门店结算默认首个月、五处 SKU 下载丢弃错误 | 当前源码可复现，尚未修复 | T0.1 | 已定位 |
| API 768 MiB OOM 仍需负载验证 | Oct19 kernel 证明容器 OOM；代理日志将故障关联到打榜读取，但不能独立归因到单个请求；现 API 已含 PR53 的榜单内存补丁 | T0.2 | 待复现 |
| 自动 compaction 未接线 | 现有执行器受资源/租约保护，自动调度缺失 | T1.1 | 待实现 |
| 九月仍缺 9/14，范围与费用未闭合 | Oct20 10:15 当前代次 29/30；旧 finalize 三次深度64错误；当前深度23 | T2.1 | 待受控恢复 |
| 静态版本尚未生产生效 | 来源任务、退款契约及首版验证阻碍仍存在 | T3.1 | 待验收 |

## 2. 分工与边界

主线程负责方案、合并、金融边界和最终验证；独立 worker 只负责指定文件及有界测试。写任务使用隔离 worktree，保留协作者修改。用户审核业务结果，不承担技术排查。原运维分支仅挑选已审阅工具，禁止整体合并其 workflow。

## 3. 执行阶段

### Phase 0：页面与资源行为可验证

**Entry Criteria**：统一 main、用户授权及正式计划门禁通过。
**Exit Criteria**：T0.1 页面回归通过；T0.2 有归因能力和实测资源证据，未复现部分明确标注。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T0.2 | [API 内存归因与限额验证](sub-delivery-plan-dydata-104-followthrough-T0.2-api-capacity.md) | 并行实施 |
| T0.1 | [账期默认值与现有下载反馈](sub-delivery-plan-dydata-104-followthrough-T0.1-filters-exports.md) | 并行实施 |

### Phase 1：持续维护与九月业务恢复

**Entry Criteria**：受控工具、资源与保护事实已核实；未知财务契约不得转换成默认值。
**Exit Criteria**：日/月调度门禁验证、九月真实来源与账单按分对账，历史保护事实保持。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T1.1 | [自然月运行与结算链自动维护](sub-delivery-plan-dydata-104-followthrough-T1.1-monthly-maintenance.md) | 待验收 |
| T2.1 | [九月来源恢复、范围与费用对账](sub-delivery-plan-dydata-104-followthrough-T2.1-september-recovery.md) | 暂缓 |

### Phase 2：受保护发布

**Entry Criteria**：所有实际发布前置条件成立。
**Exit Criteria**：五模块、账期、导出、性能、磁盘和业务验收有证据。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T3.1 | [静态首版发布与生产业务验收](sub-delivery-plan-dydata-104-followthrough-T3.1-release-acceptance.md) | 进行中 |

## 4. 任务看板

- [当前任务看板](task-kanban-dydata-104-followthrough.md)；当前 T3.1；T0.1、T0.2、T1.1 代码已集成，生产验收仍保留。用户 2026-10-20 要求“实在恢复不了不要纠结”，T2.1 暂缓，不再作为新版上线的整体前置；部署前补齐未完成账期保护。隔离 worker 的当前 Task 可以不同，主线程只集成已独立验收的代码，不覆盖各自计划状态。

## 5. 发布闸门

- [ ] 最终合并树完整 CI / PG / Web build 通过。
- [ ] 当前来源资格、金额/退款范围与后处理可核实，不能用任务 success 替代。
- [ ] 财务及结算发布冻结账期就绪状态；未完成账期和包含它的累计查询明确拒绝展示/导出正常金额。九月恢复及按分对账保留为后续业务验收，不阻碍具有此保护的新版发布。
- [ ] 五模块首版完成后才切换 API，失败保留原版。
- [ ] 备份可校验、磁盘至少 15% / 10 GiB 且覆盖备份和构建峰值。
- [ ] 真实页面月份、下载、权限、版本与内存耗时验收。
- [ ] 用户业务验收后才关闭 DYDATA-104。

2026-10-20 发布范围调整：保留失败记录、原始证据和恢复预算，不再手动推进历史恢复。五模块仍须成功构建静态版本，来源写入互斥、首版门禁及容量门禁不放宽；版本构建成功与账期业务完整是两个独立状态。完整月允许真实零值，缺失日水位不得变成零值。月结生成继续使用原有完整性门禁。

## 6. 风险与应对

| 风险 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| 退款单位、范围及覆盖未知 | 误入账或重复扣费 | 保留原始证据，停止相关写入，不猜金额 | Codex | 持续 |
| 来源写入与静态首版并发 | 发布半完成数据 | 使用已有互斥、来源与后处理门禁 | Codex | 持续 |
| 首版分批核销聚合重复广域读取 | 构建过长，正常跟进更新使首版反复失效 | T3.1先按批次订单收窄查询，保持POI、撤销和时间口径，真实预热复验 | Codex | 修复中 |
| 源恢复触发广域重建 | 误改非九月结果 | 窄范围 metadata 在提交前写入，核对保护指纹 | Codex | 待核实 |
| 重试消耗有限预算 | 掩盖旧失败 | 原根固定键、最多两代；不得新根、重置次数或伪造成功 | Codex | 已明确 |
| 历史日志缺失 | 错误归因内存根因 | 留存事实边界，补有界观测后合成复现 | Codex | 待实现 |

## 7. AI 执行示例

先验证 API 读取路径和内存，再修复门店默认月份并验证真实下载；后续每一生产动作都先有有界预演、真实资源与明确目标，执行后独立核对。阻碍未消除时继续独立代码工作，不关闭任务。

## 8. PRD → 任务反向索引

| PRD / 契约 | Task | 子开发计划 |
|---|---|---|
| 门店结算/财务/导出 PRD | T0.1 | [账期默认值与现有下载反馈](sub-delivery-plan-dydata-104-followthrough-T0.1-filters-exports.md) |
| 静态发布 API 与资源规则 | T0.2 | [API 内存归因与限额验证](sub-delivery-plan-dydata-104-followthrough-T0.2-api-capacity.md) |
| 月结、版本与存储契约 | T1.1 | [自然月运行与结算链自动维护](sub-delivery-plan-dydata-104-followthrough-T1.1-monthly-maintenance.md) |
| 费用/冻结账单 API 与 Schema | T2.1 | [九月来源恢复、范围与费用对账](sub-delivery-plan-dydata-104-followthrough-T2.1-september-recovery.md) |
| mainprd 与静态发布契约 | T3.1 | [静态首版发布与生产业务验收](sub-delivery-plan-dydata-104-followthrough-T3.1-release-acceptance.md) |

