# T5.7 系统测试、v2-clean 一致性与生产验收

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T5.7 完成 DYDATA-19 系统回归、DYDATA-80 产品一致性与 DYDATA-81 生产发布闭环

**Requirement ID**：DYDATA-19-UAT / DYDATA-80-PARITY / DYDATA-81-RELEASE

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` §4～§6
- `docs/prd/prd-feature-list-dy-data.md` 的 9 个已确认功能块
- `docs/prd/foundation/foundation-delivery-dy-data.md`
- Linear DYDATA-19、DYDATA-80、DYDATA-81 验收标准
- `docs/uat/dydata-80-ui-baseline-v2-clean.md`
- `docs/superpowers/specs/2026-08-28-dydata-81-finance-primary-navigation-design.md`
- `docs/plans/2026-08-30-dydata-81-finance-contract-controller-spec.md`
- 冻结原型 `codex/dydata-19-finance-mock@9a574fa` 与 `docs/prototypes/dydata-19-finance-flow-dashboard/`
- `docs/design-system/tokens.json`、`docs/design-system/README.md`

**核心逻辑**：
- 串联账单生成/版本、分方向确认、异议、推广费登记、管理员状态/管理费导入、指标查询、订单穿透和审计。
- 系统测试覆盖功能、权限、并发、原子性、迁移、响应式和回归；UAT 由门店和财务管理员按真实业务样例确认。
- 系统验收发现 Linear 正文与既有 T5.2～T5.6 计划存在实现差额时，以 Linear 当前正文为准，在本 Task 内先以 TDD 关闭发布阻塞项，再重跑三层验收。
- 仅在验证证据、剩余风险和用户接受均回填后关闭 DYDATA-19。
- DYDATA-80 基线只约束页面结构与业务交互；视觉统一继承 V0.2，运行时复用 `apps/web/src/design-tokens.css` 与共享组件，不从原型复制页面级颜色、间距、圆角、阴影或控件。
- 正式页面不得显示 Mock、会议演示、F01-F10、演示数据、本地角色切换或未接真实 API 的假动作；开发模式 fixture 必须显式隔离且生产构建不可启用。
- DYDATA-81 在 PR/CI 与全部硬门禁通过后执行腾讯云生产部署，并完成页面、静态资源、健康接口、权限、回滚入口的线上 smoke。
- G4 按 DYDATA-81 最终裁决把六个既有财务页面从“后台”拆为独立一级“财务”，桌面与移动端均位于“后台”之前；移除门店结算“SAP 建议”和 B02 访问 `/finance/stores` 的前端特例，不改变 API、业务与数据模型。
- G5 按已确认《财务页面合同矩阵》逐项实现六页内部结构、模块顺序、筛选、表头、状态、按钮、空错态与跳转；主应用只提供 Shell、导航、视觉 token、共享组件、响应式和权限骨架。
- G5 固定推广费 5 卡口径；待开票金额为审核未通过金额与账期未开票金额之和，页面、明细与导出必须同源。
- G5 以财务导入 SAP 为当前有效值；批量导入和单条矫正均生成新版本并保留门店原值、财务值、操作人、时间和审计，历史账单/订单快照不回写。
- G5 将“系统检测中 / 查看检测进度”实现为正式、可恢复的异步检测流程；持久化状态、进度、结果和失败原因，但自动检测只报告正式事实一致性，不自动作出异议业务裁决。

**核心文件**：
- `tests/`
- `apps/api/`
- `apps/web/`
- `alembic/`
- `docs/devlog/`
- `pwScreenShot/`
- `apps/web/src/components/Shell.tsx`
- `apps/web/src/App.tsx`
- `tests/test_frontend_user_facing_contracts.py`
- `tests/test_visual_smoke.py`
- `tests/test_api_admin_finance.py`
- `tests/test_api_store_billing.py`
- `tests/test_frontend_finance_contracts.py`
- `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md`
- `docs/prd/foundation/foundation-schema-dy-data/billing-invoice.md`

**完成标准**：
- 最低验收矩阵覆盖系统外开票边界、推广费四态、管理费当期导入上期、两个方向互不阻断、成立异议新账单版本、四类导入五结果和版本冲突。
- 发布阻塞差额全部关闭：推广费购买方/6% 税率、10/11 日批次边界、红冲/作废/替换重开、负数账期结转；锁定月退款/取消核销顺延；管理费直接更正；SAP 建议/确认；逐业务键导入反向批次；历史门店/SAP 快照；订单明细完整字段/筛选/导出。
- `python -m pytest`、Web build、治理/计划检查、目标数据库升级、真实浏览器和 smoke test 全部通过。
- Linear 回填测试、commit/PR/CI/部署或未部署原因、UAT 结论和剩余风险；责任人接受后才可 Done。
- v1-original 与 v2-clean 的 commit/hash、页面清单和证据可追溯；六类财务页面完成结构、交互、角色、路由、状态与 V0.2 组件/令牌追踪。
- 390px、768px、1440px 浏览器证据确认无全局横向溢出，正式界面没有演示专用文案和控件。
- 管理员的“财务”一级入口紧邻且位于“后台”之前，六个财务二级入口沿用既有路由；财务与后台激活态互斥。
- 门店账号看不到“财务”和“SAP 建议”，直接访问 `/finance/stores` 进入现有无权限页；`/finance` 仍只兼容跳转 `/finance/promotion`。
- 六页合同矩阵不存在未记录偏差；所有真实字段均可追到正式 API/Schema，演示金额、日期、状态与假动作未进入生产构建。
- 推广费 5 卡、订单结算状态、管理费全额扣减状态、SAP 当前值/版本审计和异步检测刷新恢复均通过 API、页面和导出一致性回归。
- 2026-08-31 用户裁决取消账单异议文件上传；新建异议改为具体原因必填并由正式 API 持久化，`evidence` 非空请求拒绝，历史 `evidence_json` 仅兼容读取。DYDATA-82 的对象存储门禁不再属于本轮发布依赖。

**Verification Method**：
- 执行 `git diff --check`、`python -m pytest`、`npm --prefix apps/web run build`、治理门禁、计划一致性和目标环境 smoke。
- 按 UAT 脚本分别以门店账号和管理员角色完成端到端操作并核对审计记录。
- 扫描生产构建与财务路由可见文本，验证演示模式未启用；逐页对照 v2-clean 结构/交互基线与 V0.2 运行时组件。
- 对 G4 先运行前端契约与浏览器失败测试，再实现最小导航/权限调整；在 390/768/1440 视口分别核对管理员财务页、后台页和门店直达拒绝场景。
- 对 G5 先运行后端 API/模型与前端合同失败测试，再做最小实现；以正式接口在隔离 UAT 完成六页 1440/768/390 截图和逐动作 Given/When/Then 记录。
- 在目标 PostgreSQL 执行升级/降级边界、SAP 并发版本、异步任务恢复、导入原子性和审计核对；任一差异、孤儿、空审计或版本覆盖均阻断发布。

**Evidence**：
- `docs/uat/dydata-19-uat-checklist.md`、`docs/uat/dydata-80-ui-baseline-v2-clean.md`、`docs/uat/dydata-81-finance-contract-g5.md`、产品一致性追踪矩阵、`docs/devlog/` 最终系统测试记录、`pwScreenShot/` 最终截图、Linear DYDATA-19/80/81 验证评论及 PR/CI/部署链接。

**Failure Handling**：
- 任一数据正确性、权限、迁移、并发或原子性场景失败即阻断发布与关闭。
- 无目标环境或业务样例时只报告本地完成，不把缺失证据写成已验收。
- 发现原型与 V0.2 冲突时以 V0.2 为视觉权威；发现基线与 DYDATA-19/PRD/Foundation 冲突时停止对应实现并记录偏差，不以原型覆盖业务真相。
- 发现合同字段无正式来源、业务裁决冲突、异步检测需要外部能力或 reason-only 异议闭环缺少真实 API 证据时，将对应项标记 BLOCKED，停止生产发布并集中报告，不自行补规则。
- 生产凭据、分支保护、CI、备份、目标 PostgreSQL 或线上 smoke 任一硬门禁失败时停止发布，不绕过、不泄露秘密。
- 新发现问题按是否阻断拆分 Linear follow-up，并保留主 Issue 风险记录。

**完成收尾：状态同步**：
- 完成系统测试、UAT 和 Foundation 漂移判断后，把完成事实、证据、日期、漂移结论和关闭建议提交给 `ai-project-manager`；由其同步主计划、看板、本子计划及 Linear，并重跑 S4/Done 门禁。三处未同步且用户未接受前不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T5.1～T5.6

**状态**：进行中（2026-08-30；G4 已生产部署，G5 获 Owner 明确授权完成实现、测试、隔离 UAT 和受控生产发布；任一合同、数据正确性、DYDATA-82 裁决或发布硬门禁失败仍停止发布，完成后等待 Owner 验收，不自行关闭 DYDATA-81）

**最新验证**：G1a、G0、G1b/G1c、G2 与 G3 已完成并通过独立代码审查。G4 一级财务导航已由 `df617e7` 经既有受控流程部署生产并完成 smoke。G5 已完成六页合同、SAP 有效值/审计、单条矫正、真实异步检测和三视口隔离 UAT；reason-only 异议增量的 API/前端回归 62 passed、三档真实 FastAPI UAT 3 passed、DYDATA-81 专项视觉回归 10 passed、全量视觉回归 245 passed，D-09 已转为 PASS。全量 pytest 已重跑通过：`1480 passed, 2 skipped, 271 warnings`（36:12）；此前 Windows `ERR_NO_BUFFER_SPACE` 未复现。生产放行不再受 DYDATA-82 对象存储合同阻塞，仍受 GitHub/CI 鉴权、目标 PostgreSQL/备份/部署门禁约束。
