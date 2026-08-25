# 开发日志 — 2026-08-21

> 主题：T5.1 财务闭环 Schema 与版本迁移完成
> 操作人：jojiuchen-blip
> 关联计划：docs/plans/execution-plan.md

---

## 一、执行概要

| # | 任务 | 关联 | 状态 |
|---|------|------|------|
| 1 | T5.1 财务闭环 Schema 与版本迁移完成 | 本轮推进 | ✅ |
| 2 | T5.2 账单读取与分方向确认接口阶段完成 | 补充更新 | ✅ |
| 3 | DYDATA-19 T5.1/T5.2 Foundation 收口 | 补充更新 | ✅ |
| 4 | DYDATA-19 T5.3 财务查询与订单导出闭合 | 补充更新 | ✅ |
| 5 | DYDATA-19 T5.4 异议生命周期闭合 | 补充更新 | ✅ |
| 6 | T5.5 四类财务导入与更正闭合 | 补充更新 | ✅ |
| 7 | T5.6 生产页面、跨页流程与浏览器门禁闭合 | 补充更新 | ✅ |

**本日关键结论**：专项测试 22 passed；Alembic 单一 head 20260821_0029；S4-FCR-001 已采纳。建议将 T5.1 标记完成并进入 T5.2 门店确认与推广费发票登记。

---

## 二、操作详情

### 任务 1：T5.1 财务闭环 Schema 与版本迁移完成
- **目标**：完成 DYDATA-19 T5.1 的可版本化、可审计财务事实地基
- **操作**：复验模型、Alembic 迁移、账单 V1/Vn+1 兼容迁移、SQLite 升降级和 PostgreSQL DDL
- **结果**：专项测试 22 passed；Alembic 单一 head 20260821_0029；S4-FCR-001 已采纳。建议将 T5.1 标记完成并进入 T5.2 门店确认与推广费发票登记。
- **涉及文件**：无

<!-- 复杂决策型任务可展开分析：
### 任务 N：标题（决策类）
- **背景问题**：为什么要做这个决策
- **方案对比**：（表格或列表）
- **最终决策**：选了什么 + 为什么
- **涉及文件**：列表
-->

---

## 三、变更总览

### 文件变更清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建/修改/删除 | `path/to/file` | 一句话说明 |

> 收口时由 AI 从各任务「涉及文件」聚合去重生成。操作类型：新建 / 修改 / 删除。

### Git 提交记录

| 时间 | Commit | 内容 |
|------|--------|------|

---

## 四、发现的问题 / 缺陷

无

---

## 五、复盘

### 做得好的
- （列举）

### 遇到的问题
- **现象**：
- **根因**：
- **经验**：> 可执行的一句话
- **🔧 是否提炼为规则**：✅ 建议写入 `project-rules.md` / ⬜ 仅记录

### 今日经验总结
1. 经验 1 → 🔧 建议加入 project-rules.md
2. 经验 2 → 仅记录

---

## 五·附、方法论沉淀（可选）

> 当天工作中如果有可复用的方法论、设计原则、或跨项目通用的经验，在此抽象记录。
> 普通开发日不需要填写此章节。

---

## 六、待跟进事项

- [ ] 待补充
---

## 补充更新 1（10:22 · 窗口 1）

### 任务 2：T5.2 账单读取与分方向确认接口阶段完成
- **目标**：在不假定跨账期发票规则的前提下，交付可读取、可回溯、可幂等确认的门店账单接口
- **操作**：实现 #23–#25、账单确认幂等迁移、B02 页面权限映射，并通过 FastAPI 与 Alembic 回归验证
- **结果**：#23–#25 已实现；#29–#30 因 S4-FCR-002（跨账期发票规则冲突）待裁决而未实现。专项 API/数据模式测试 25 passed，迁移校验 2 passed，PostgreSQL DDL 编译通过。
- **涉及文件**：无

---

## 补充更新 2（11:12 · 窗口 1）

### 任务 3：T5.2 推广费发票重登版本闭环
- **操作**：补充被拒绝推广费发票的重新登记回归：旧发票与其分配行切为非当前，新记录创建 V2 并通过 `supersedesInvoiceId` 回链。
- **结果**：门店账单专项测试覆盖当前/历史账单、分方向确认、跨账期分配、拒绝后重登，共 5 项通过。
- **Foundation 漂移**：继续采用 `S4-FCR-002`；Linear 的跨完整账期分配规则优先，未覆盖工作树中既有的 Foundation 文档修改。

### 任务 4：T5.3 管理员财务查询与订单穿透
- **操作**：实现 #31～#34：管理员财务汇总、按方向的当前有效发票列表、按方向订单穿透和门店聚合。所有接口强制费用方向；累计从 `2026-08` 起算；只统计当前账单/发票版本。
- **指标口径**：已确认金额始终返回所选单月；累计待开票以累计确认减累计已开票计算并下限为 0。推广费登记待厂端审核和已结算均计入已开票，只有已结算计入已结算；管理费已开票与厂家扣款使用同一当前有效已结算事实。
- **权限与边界**：管理员与最高管理员均可查询；门店角色返回 403。订单明细不混合两种费用方向；门店 ID 是唯一筛选键，当前模型尚无 SAP 字段时返回空展示值，不按名称或 SAP 做匹配。
- **验证**：`tests/test_api_store_billing.py` 9 passed；`tests/test_api_dashboard.py` 17 passed；`tests/test_data_schema.py` 5 passed；账单版本/迁移图 2 passed；`git diff --check` 通过。
- **涉及文件**：`apps/api/dy_api/routes/dashboard.py`、`apps/api/dy_api/main.py`、`tests/test_api_store_billing.py`。
---

## 补充更新 3（10:56 · 窗口 3）

### 任务 4：DYDATA-19 T5.1/T5.2 Foundation 收口
- **目标**：完成财务领域地基和门店账单/推广费发票登记的收口证据
- **操作**：按 Linear 当前正文采纳 FCR-001/FCR-002；同步账单不可变版本与推广费发票头加账期分配契约；复跑专属 API 回归
- **结果**：FoundationReadyForPrd=true；FCR-001/FCR-002 已改；tests/test_api_store_billing.py 9 passed，已知 16 个视觉权限夹具失败不在本次回归范围
- **涉及文件**：无
---

## 补充更新 4（11:06 · 窗口 4）

### 任务 5：DYDATA-19 T5.3 财务查询与订单导出闭合
- **目标**：完成管理员财务汇总、发票、订单穿透、门店聚合及同口径订单导出
- **操作**：审计 #31-#34 后发现订单导出缺口；新增失败测试并实现 /api/v1/admin/finance/order-details/export，复用列表筛选和管理员权限
- **结果**：TDD 红灯为 404，修复后 test_api_store_billing.py 12 passed；test_api_dashboard.py 17 passed；test_data_schema.py 5 passed；两项相关迁移 2 passed。组合运行超时但分组均通过；16 个视觉权限夹具失败不属本次回归
- **涉及文件**：无
---

## 补充更新 5（11:22 · 窗口 5）

### 任务 6：DYDATA-19 T5.4 异议生命周期闭合
- **目标**：完成门店异议、管理员内部处理、不可变账单新版本与幂等迁移。
- **操作**：实现异议提交/撤回/管理员筛选与状态迁移；成立调整在单事务创建 Vn+1、复制快照并写入调整分录、自动确认和审计；增加异议及操作审计幂等字段和 0032 可逆迁移；确认仅冻结同方向实际争议金额。
- **结果**：技术验收通过：test_api_store_billing 14 passed；迁移图与 0032 可逆迁移 2 passed；git diff --check 通过。组合运行 tests/test_api_store_billing.py tests/test_alembic_migrations.py 曾在 124 秒环境超时，拆分结果作为有效证据。16 个视觉权限夹具失败未运行，保持独立后续项。
- **涉及文件**：无
---

## 补充更新 6（13:17 · 窗口 6）

### 任务 7：T5.5 四类财务导入与更正闭合
- **目标**：完成 DYDATA-19 T5.5 的四模板导入、预校验、原子提交、更正覆盖、错误下载、并发版本保护和规格漂移闭合。
- **操作**：实现四类 CSV/XLSX 流式导入与六个管理员接口；按最终业务唯一键精确匹配；落地五种预校验场景、全错误行持久化、整批零写入、上传/提交双层幂等、不可变 Vn+1 与审计；新增门店基础/SAP 快照、推广厂家结果事件和管理厂家扣款字段及 0034～0036 可逆迁移；通过 Foundation Builder 关闭 S4-FCR-003/S4-FCR-004。
- **结果**：最终四模板为基础信息、推广服务费厂家结果、管理服务费厂家结果、SAP 确认；管理费发票与厂家扣款合并为同一模板。`tests/test_api_finance_imports.py` 5 passed；`tests/test_api_store_billing.py` 22 passed；Alembic 单一 head 与 0033～0036 往返 2 passed；5001 行返回 413 且批次/逐行记录为 0；`git diff --check` 通过（仅既有换行提示）。旧四模板测试已迁移，不作为本次回归失败；16 个视觉权限夹具仍是独立后续项。
- **迁移风险**：0034～0036 均仅前向新增表/可空字段/唯一约束且已有往返测试；未执行任何真实库迁移或生产发布。
- **涉及文件**：`apps/api/dy_api/models.py`、`apps/api/dy_api/routes/dashboard.py`、`alembic/versions/20260821_0033*`～`0036*`、`tests/test_api_finance_imports.py`、Foundation/PRD/计划文档。

---

## 补充更新 7（T5.6 页面闭合）

### 任务 8：T5.6 生产页面、联调与浏览器验收
- **目标**：把 DYDATA-19 的门店发票登记、双费用财务看板、双订单页、门店汇总、异议和导入记录接入真实 API，彻底移除旧五节点开票流程。
- **操作**：接入 8 条生产路由；删除 `InvoiceGuidePage.tsx` 并保留 `/invoice` 单向兼容跳转；统一最终四类导入和推广费四态；增加基础信息/SAP 导入入口；推广费支持同一门店多个完整账期分配；修复成功提示随表单卸载的浏览器回归；将财务页面原生选择控件迁移到共享可搜索选择器；修正未注册 CSS 变量并统一财务枚举中文安全展示。
- **技术验收**：设计系统/前端契约 54 passed；`tests/test_api_store_billing.py` 22 passed；`tests/test_api_finance_imports.py` 5 passed；Web production build 通过（仅 545.96 kB chunk 非阻塞提示）；`git diff --check` 通过（仅既有换行提示）。
- **浏览器/系统验收**：相关浏览器 30 passed；真实 FastAPI 管理员空态、门店 403、发票 422 保留输入后成功回读、导入 409 重试均通过；8 路由在 390/768/1440 共 24 项通过，无横向溢出、内部枚举泄漏、控制台异常或意外 HTTP 失败。
- **证据**：`output/playwright/` 共 24 张生产路由截图；`tests/test_visual_smoke.py`、`tests/test_design_system_enforcement.py` 和 `tests/test_frontend_user_facing_contracts.py`。
- **Foundation 漂移**：本任务只消费当前已冻结 API/Schema 契约，无新增 Schema、API 或术语漂移。
- **遗留风险**：Web 单 chunk 545.96 kB 仅为性能提示；全量系统回归、发布/回滚清单与用户验收由 T5.7 承接；未执行生产数据库迁移或部署。
- **涉及文件**：`apps/web/src/App.tsx`、`apps/web/src/components/Shell.tsx`、`apps/web/src/components/FinanceImportActionPanel.tsx`、`apps/web/src/pages/StoreInvoicePage.tsx`、`apps/web/src/pages/Finance*Page.tsx`、`apps/web/src/api/client.ts`、`apps/web/src/types/dashboard.ts`、`apps/web/src/utils/userFacingLabels.ts`、前端/视觉测试、计划文档。

---

## 补充更新 8（T5.7 系统回归与 UAT 准备）

### 任务 9：T5.7 本地系统回归与验收矩阵
- **目标**：执行全量系统回归，修复 T5.6 引入的回归，并把真实业务验收项、证据和阻断条件固化为可签字清单。
- **操作**：首次执行全部 1003 项 pytest；定位新增财务移动端媒体查询抢占既有 CSS 静态测试匹配位置的问题，将该查询改为等价的 `screen and (max-width: 640px)`；建立 `docs/uat/dydata-19-uat-checklist.md`，覆盖系统外开票、推广费四态、管理费导入、分方向互不阻断、异议版本、四类导入、权限、指标和审计。
- **系统测试结果**：全量首轮 999 passed、4 failed；4 项均为上述 CSS 匹配回归。修复后失败项 4 passed、完整线索中心 29 passed、设计系统/用户文案 54 passed、财务/发票浏览器 30 passed、Web production build 通过。
- **当前验收结论**：需补充。尚未再次执行全部 1003 项，且缺少目标数据库升级、真实门店/财务样例、三角色联测和业务责任人签字，因此不关闭 DYDATA-19，不执行生产发布。
- **证据**：`docs/uat/dydata-19-uat-checklist.md`、`output/playwright/`、本日志及 Linear DYDATA-19 后续验证评论。
- **涉及文件**：`apps/web/src/styles.css`、`docs/uat/dydata-19-uat-checklist.md`、T5.7 交付计划与本日志。

---

## 补充更新 9（T5.7 Linear 正文差额复核与阻断项拆分）

### 任务 10：以 DYDATA-19 Linear 正文重新核对发布范围

- **目标**：纠正 T5.1～T5.6 窄版交付计划与 Linear 当前正文之间的遗漏，避免把“页面已接 API”误判为业务规格全部闭合。
- **操作**：在当前 `codex/dydata-19-page-loop` worktree 复核推广费发票、管理费单店更正、SAP、导入撤销和财务订单明细；形成 `G1a/G1b/G1c/G2/G3` 五份可测试任务简报，并更新控制器规格、T5.7 计划和执行计划。
- **发现的发布阻断项**：推广费固定购方/6%税率/北京时间结算批次；红冲/作废/替换事件；负数账期结转；管理费单店更正；SAP 建议和确认；四类导入撤销版本；订单明细完整字段、筛选、分页、同口径导出及导出审计。
- **独立规格复核**：首轮发现锁定月差额来源、逐业务键反向导入、历史主数据快照 3 个 BLOCKER 及 7 个其他问题；新增 G0 并修正 G1b/G1c/G2/G3 后二次复核返回 `RESOLVED`，仅表示规格可进入开发，不表示功能已验收。
- **权限边界纠正**：发现 UAT 清单残留“硬门禁通过后无需二次确认、直接生产”的旧文本，已改为“当前仅授权系统测试、UAT 和发布准备；生产迁移与部署前必须再次确认”。未执行任何生产迁移或部署。
- **验证**：治理锁、全局文件检查、S4 route check、T5.7 task context 与 env check 均通过；本任务仅完成范围审计和规格拆分，代码实现与测试结果将在各 G 任务完成后逐项记录。
- **涉及文件**：`docs/plans/2026-08-21-dydata-19-t5-controller-spec.md`、`docs/plans/dydata-19-task-g1a-brief.md`、`docs/plans/dydata-19-task-g1b-brief.md`、`docs/plans/dydata-19-task-g1c-brief.md`、`docs/plans/dydata-19-task-g2-brief.md`、`docs/plans/dydata-19-task-g3-brief.md`、`docs/plans/execution-plan.md`、T5.7 交付计划、`docs/uat/dydata-19-uat-checklist.md`。

---

## 补充更新 10（T5.7 G1a 推广费登记事实与结算批次）

### 任务 11：固定购买方、6% 税率与北京时间结算批次

- **目标**：推广费发票登记持久化固定购买方和 6% 税率，并以系统校验成功的北京时间确定结算批次。
- **实现**：新增 0037 单头可逆迁移；`PromotionInvoice` 保存购买方/税率，allocation 保存结算批次；10 日 23:59:59 及以前进入上一业务月批次，11 日 00:00:00 起进入当前月批次；多账期发票共享同一登记时间和批次；厂家结果导入产生的新状态版本完整复制三类事实。生产页展示购买方名称、纳税人识别号、税率和结算批次。
- **TDD 证据**：RED 为 8 failed（缺少字段、校验、边界、迁移和页面契约）；GREEN 为核心 8 passed、账单/导入 API 32 passed、迁移单头与往返 2 passed、前端契约 11 passed、浏览器提交回读 1 passed、Web build 和 `git diff --check` 通过。
- **独立审查**：APPROVED，无 BLOCKER/MAJOR。审查发现登记响应类型与真实 header+allocations 结构不一致，已新增 `PromotionInvoiceRegistrationResult` 并复跑前端契约 11 passed、build 通过。
- **剩余风险**：PostgreSQL 时区回填 SQL 已静态审查，但尚未在目标 PostgreSQL 执行；仅 SQLite 完成升级、回填和降级。Vite 546.47 kB chunk 与依赖弃用/CRLF 提示为非阻断既有警告。
- **生产边界**：未执行生产迁移、部署、commit 或 push。

## 补充更新 11（T5.7 G0 首轮实现与独立审查返修）

### 任务 12：锁定账期退款/取消核销顺延事实

- **首轮实现**：新增不可变 `SettlementCarryforwardSource`、版本化 `SettlementCarryforwardApplication` 和 0038 单头可逆迁移；锁期退款与取消核销保存差额来源，连续锁期后进入首个可处理账期。实施者相关全套为 60 passed；控制器复跑核心 worker 与迁移为 25 passed；`py_compile` 与 `git diff --check` 通过。
- **独立审查结论**：暂不通过。发现锁期退款后再取消核销可能重复扣减管理费；发票/厂家扣款事实尚未纳入统一不可变账期判断；异议账单 Vn+1 未生成应用 Vn+1；顺延调整受 `SettlementFeeResultCurrent` 换版影响可能从投影消失；安全待顺延仍记为 error 可能误伤门禁。
- **处理方式**：G0 保持进行中，不把首轮测试通过误判为验收完成。已补强任务简报并启动第二轮 TDD，要求用组合事件、发票事实、账单版本和费用结果换版用例逐项锁定后再复审。
- **第二轮修复**：统一有效差额集合，普通调整直接计一次、顺延来源无论待应用或已应用均只计来源一次；推广费当前分配和管理费当前发票/厂家扣款纳入不可变账期；异议 Vn+1 复制顺延调整并生成应用 Vn+1；worker 仅投影当前应用版本且不再依赖费用结果当前指针；安全待顺延降为 warning；0038 增加退款/取消事件引用一致性约束。
- **最终验证**：修复专项 9 passed；完整 `tests/test_data_settlement.py tests/test_api_store_billing.py tests/test_alembic_migrations.py` 为 90 passed、94 warnings；PostgreSQL dialect 下两张表和 6 个索引独立编译通过；`py_compile`、`git diff --check` 通过。二次独立审查 Critical/Important/Minor 均为 0，结论 Ready Yes。
- **剩余风险**：尚未在目标 PostgreSQL 执行两会话竞争集成测试；旧迁移 `20260616_0003` 在 Alembic 全链离线模式对 mock connection 调用 inspect，导致全链 `--sql` 被既有代码拦截，但 0038 自身 PostgreSQL DDL 编译通过。两项均保留到目标数据库发布前门禁。
- **生产边界**：未执行生产迁移、部署、commit 或 push。

---

## 补充更新 12（T5.7 G1b/G1c 冻结回归）

### 任务 13：推广费发票生命周期与跨账期负数结转

- **实现范围**：新增 0039/0040 单头可逆迁移；落地发票物理版本、全局号码登记、外部红冲/作废事实、完整替换链、释放账期恢复入口，以及负数账期优先抵扣最早未开票正数账期的确定性投影。系统仍只登记外部事实，不创建开票申请或系统内审核任务。
- **返修与根因**：补齐迁移歧义异常、并发幂等重放、替换链分叉约束、刷新后恢复、释放账期强制替换、数据范围校验和用户隔离；财务导入测试夹具同步建立物理发票登记事实，历史账单版本测试先 flush 当前版本号再插入退役版本，避免测试事务中的瞬时唯一键冲突。
- **冻结验证**：`tests/test_api_store_billing.py` 49 passed、`tests/test_alembic_migrations.py` 24 passed；前端契约 11 passed；可恢复替换浏览器流程 1 passed；Web production build 与 `git diff --check` 通过，仅有 554.72 kB chunk 非阻断提示。
- **第三轮审查返修**：审查发现 0039 有损降级、多来源替换死锁、回填链 current 位置和跨门店幂等侧信道；已增加生命周期/替换指针降级硬阻断、多来源替换关联、V1 根与唯一链尾 current 校验，以及范围校验优先级。最终独立复审结论 `Ready: yes`。
- **剩余风险**：目标 PostgreSQL 的真实升级、两会话并发与异常清单归零仍是发布前硬门禁；已知 16 个视觉权限夹具失败保持独立后续项，不计入本次回归。
- **生产边界**：未执行生产迁移、部署、commit 或 push。

---

## 补充更新 13（T5.7 G2 冻结回归）

### 任务 14：管理费更正、SAP 建议确认、导入撤销与管理费负数结转

- **实现范围**：新增 0041/0042 单头迁移；管理费单店更正使用共享可开票投影全额；门店 SAP 建议与管理员确认/修正/驳回采用独立不可变双版本；四类导入按逐业务键生成 VALUE/TOMBSTONE 反向版本；管理费负数结转生成不可变应用并在更正/撤销后确定性重投影。
- **审查返修**：三轮独立复审先后关闭建议处理原地修改、门店角色与 B02 权限链、旧应用未退出、虚假 `canReverse`、冲突未审计、无账单门店漏出 SAP 队列、并发版本分配、历史 tombstone 恢复沿用旧投影及效果类型错误。PostgreSQL 使用事务级 advisory lock，0042 部分唯一索引作为最终版本防线。
- **最终验证**：稳定快照运行 `tests/test_api_finance_g2.py tests/test_api_finance_imports.py tests/test_api_store_billing.py tests/test_alembic_migrations.py tests/test_api_access_control.py` 为 `104 passed, 137 warnings`；Web production build 通过；Alembic 单头为 `20260824_0042`；`git diff --check` 通过。最终独立复审无 Critical/Important，结论 `Ready: yes`。
- **迁移与并发风险**：0041 已验证存在不可变 SAP 事实时拒绝有损降级并保留数据；真实 PostgreSQL 双事务压力测试与目标库升级仍是发布前硬门禁，不以 SQLite 结果替代。
- **生产授权**：Owner 已授权全部测试、安全、迁移、CI、部署前备份与 smoke 硬门禁通过后无需二次确认，直接进入生产迁移与部署；任一门禁失败必须停止发布。当前 G3 未完成，尚未进入生产。

---

## 补充更新 14（T5.7 主线集成预检）

### 任务 15：DYDATA-19 与最新主线的发布前冲突审计

- **审计结果**：刷新到 `origin/main@af0afdd` 后，当前功能分支相对主线落后 55、领先 37；`git merge-tree --write-tree HEAD origin/main` 识别出 61 个真实冲突，覆盖历史 Alembic、财务共享后端、前端壳层、worker、测试和治理文档。
- **迁移判断**：主线与当前分支的 0023～0025 revision ID 相同但内容不同，必须保留主线生产安全版本；DYDATA-19 的财务迁移不得原样硬接旧链，需在主线当前 head 后重建连续迁移并保证单头。
- **处理决策**：不在当前脏工作树直接 merge。先完成并冻结 G3、形成可恢复提交，再从最新 `origin/main` 建立干净集成分支，按迁移、模型/API、worker、前端、测试、文档分块移植和验证。
- **发布门禁**：在干净主线集成、全量回归、目标 PostgreSQL 升级、CI、备份和 smoke 全部通过前不执行生产部署；该停止条件属于既有硬门禁，不改变 Owner 的“门禁全部通过后直接部署”授权。
