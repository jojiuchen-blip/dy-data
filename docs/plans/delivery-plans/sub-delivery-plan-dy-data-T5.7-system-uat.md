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

**完成标准**：
- 最低验收矩阵覆盖系统外开票边界、推广费四态、管理费当期导入上期、两个方向互不阻断、成立异议新账单版本、四类导入五结果和版本冲突。
- 发布阻塞差额全部关闭：推广费购买方/6% 税率、10/11 日批次边界、红冲/作废/替换重开、负数账期结转；锁定月退款/取消核销顺延；管理费直接更正；SAP 建议/确认；逐业务键导入反向批次；历史门店/SAP 快照；订单明细完整字段/筛选/导出。
- `python -m pytest`、Web build、治理/计划检查、目标数据库升级、真实浏览器和 smoke test 全部通过。
- Linear 回填测试、commit/PR/CI/部署或未部署原因、UAT 结论和剩余风险；责任人接受后才可 Done。
- v1-original 与 v2-clean 的 commit/hash、页面清单和证据可追溯；六类财务页面完成结构、交互、角色、路由、状态与 V0.2 组件/令牌追踪。
- 390px、768px、1440px 浏览器证据确认无全局横向溢出，正式界面没有演示专用文案和控件。
- 管理员的“财务”一级入口紧邻且位于“后台”之前，六个财务二级入口沿用既有路由；财务与后台激活态互斥。
- 门店账号看不到“财务”和“SAP 建议”，直接访问 `/finance/stores` 进入现有无权限页；`/finance` 仍只兼容跳转 `/finance/promotion`。

**Verification Method**：
- 执行 `git diff --check`、`python -m pytest`、`npm --prefix apps/web run build`、治理门禁、计划一致性和目标环境 smoke。
- 按 UAT 脚本分别以门店账号和管理员角色完成端到端操作并核对审计记录。
- 扫描生产构建与财务路由可见文本，验证演示模式未启用；逐页对照 v2-clean 结构/交互基线与 V0.2 运行时组件。
- 对 G4 先运行前端契约与浏览器失败测试，再实现最小导航/权限调整；在 390/768/1440 视口分别核对管理员财务页、后台页和门店直达拒绝场景。

**Evidence**：
- `docs/uat/dydata-19-uat-checklist.md`、`docs/uat/dydata-80-ui-baseline-v2-clean.md`、产品一致性追踪矩阵、`docs/devlog/` 最终系统测试记录、`pwScreenShot/` 最终截图、Linear DYDATA-19/80/81 验证评论及 PR/CI/部署链接。

**Failure Handling**：
- 任一数据正确性、权限、迁移、并发或原子性场景失败即阻断发布与关闭。
- 无目标环境或业务样例时只报告本地完成，不把缺失证据写成已验收。
- 发现原型与 V0.2 冲突时以 V0.2 为视觉权威；发现基线与 DYDATA-19/PRD/Foundation 冲突时停止对应实现并记录偏差，不以原型覆盖业务真相。
- 生产凭据、分支保护、CI、备份、目标 PostgreSQL 或线上 smoke 任一硬门禁失败时停止发布，不绕过、不泄露秘密。
- 新发现问题按是否阻断拆分 Linear follow-up，并保留主 Issue 风险记录。

**完成收尾：状态同步**：
- 完成系统测试、UAT 和 Foundation 漂移判断后，把完成事实、证据、日期、漂移结论和关闭建议提交给 `ai-project-manager`；由其同步主计划、看板、本子计划及 Linear，并重跑 S4/Done 门禁。三处未同步且用户未接受前不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T5.1～T5.6

**状态**：进行中（2026-08-26；Owner 已确认 v2-clean 页面结构与业务交互基线，并授权在全部硬门禁通过后无需二次确认，直接执行生产部署；任一硬门禁失败仍停止发布）

**最新验证**：G1a、G0、G1b/G1c、G2 与 G3 已完成并通过独立代码审查。G3 已关闭账单 Vn+1 明细快照继承、历史明细快照回填/异常清单和部署前异常归零门禁；最终完整相关回归 `152 passed, 170 warnings`，Web build、Alembic 单头 `20260824_0043` 和 `git diff --check` 通过，定向复审为 Critical 0、Important 0、Minor 0、`Ready: yes`。2026-08-28 G4 已在 `codex/dydata-81-finance-nav` 完成本地实现和产品一致性核对：前端契约 15 passed、聚焦视觉回归 6 passed、完整回归 `1418 passed, 2 skipped, 263 warnings`，Web build 通过，390/768/1440 及 949×466 参考视口验证通过；PR、CI、目标 PostgreSQL 真实升级、两会话并发、生产部署与线上 smoke 仍为最终发布门禁。
