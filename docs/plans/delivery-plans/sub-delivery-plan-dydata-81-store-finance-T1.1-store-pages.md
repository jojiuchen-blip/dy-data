# T1.1 门店端四页一致性子交付计划

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-81-store-finance.md](main-delivery-plan-dydata-81-store-finance.md)
- 任务看板：[task-kanban-dydata-81-store-finance.md](task-kanban-dydata-81-store-finance.md)

#### T1.1 实现全国门店榜单、单店分账、开票确认与发票状态查看

**Requirement ID**：DYDATA-81-STORE-RANKING / DYDATA-81-STORE-SETTLEMENT / DYDATA-81-STORE-INVOICE / DYDATA-81-INVOICE-STATUS

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` 全局设计规则
- `docs/prd/subprd/02-subprd-store-settlement.md` §2—§4
- `docs/prd/subprd/04-subprd-invoice-registration.md` §2—§4
- `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md` §0、§2、§4、§6
- `docs/prd/foundation/foundation-schema-dy-data/billing-invoice.md` §1、§4.1—§5
- Linear DYDATA-81 本轮开发范围锁、DYDATA-19 冻结业务规则，以及 2026-08-28 两个 Issue 中记录的用户最新明确确认

**核心逻辑**：
- 正式系统 `Shell`、设计 token、组件族和真实权限为页面骨架；4181 只提供门店四页内部模块、字段、状态、动作和流转的结构基线，演示数据和提示不进入正式系统。
- 全国门店榜单删除管理服务费和结算参考净额的卡片、表格列与排序项；累计榜单的销售和核销指标读取累计口径，不用单月值伪装累计值。
- 单店分账只展示后端冻结金额/版本，推广与管理方向独立确认；并发冲突清空旧版本并刷新。异议真实提交受 DYDATA-82 阻塞，必须明确未开放。
- 单店分账、开票确认与发票状态默认门店取当前账号绑定门店，默认账期取正式 API 返回的最新业务账期/最新账单月，不使用浏览器本地月份。
- 开票确认调用真实 `POST /promotion-invoices`，校验 20 位号码、完整账期、服务端金额和版本；系统一次选中该门店全部当前可开票且未开票的完整账期，合并开一张票，门店不可删减或切换；审核退回/重开时原票覆盖账期整体释放并整体重开。
- 购买方名称、纳税人识别号、地址、电话、开户行及账号、项目名称、税收分类编码和税率由门店手工填写，并按用户确认基准逐字段精确校验；哪个字段错误只提示哪个字段。
- 不含税金额、税额和开票金额由门店手工填写，只校验“不含税金额 + 税额 = 开票金额”；计算到小数点后三位后四舍五入到分，允许 0.01 元容差，不按 6% 从总额自动拆税。
- 开票日期不得早于所含账单确认/锁账日期，不得晚于服务器北京时间当前日期。
- 发票状态查看使用独立稳定 URL，读取 `GET /promotion-invoices` 与详情接口；删除“待开票”筛选；发票号码由服务端精确筛选后再分页，不在浏览器做子串或伪造全量过滤。
- 管理员/最高管理员不做角色硬禁；确认和登记仍由 B02、门店数据范围与既有操作权限共同校验。
- 不实现系统内审核、真实开票、附件、外部验真或红冲/作废假动作；既有真实生命周期登记与替换闭环保持不变；不改 `/finance/*`。

**核心文件**：
- `apps/web/src/App.tsx`
- `apps/web/src/components/Shell.tsx`
- `apps/web/src/pages/StoreSettlementPage.tsx`
- `apps/web/src/pages/StoreRankingPage.tsx`
- `apps/web/src/pages/StoreInvoicePage.tsx`
- `apps/web/src/pages/StoreInvoiceStatusPage.tsx`
- `apps/web/src/styles.css`
- `tests/test_frontend_store_finance_pages.py`
- `tests/test_frontend_store_settlement_confirmation.py`
- `tests/test_visual_smoke.py`
- `tests/test_visual_store_finance_pages.py`
- `docs/uat/dydata-81-store-finance-baseline.md`

**完成标准**：
- 二级导航保持系统现有顺序并新增“发票状态查看”，`/settlement/invoice/status` 可直达、刷新恢复且使用 B02 权限。
- 全国门店榜单仅保留销售、核销、当期推广服务费、累计推广服务费指标；表格和排序不再包含管理服务费或结算参考净额。
- 单店分账具备月度节奏、当前状态、双方向金额/确认卡、原始/调整/净额、展开明细、订单下钻和真实异议空态；指标包含当期与累计管理服务费；榜单页不显示管理服务费。
- 开票确认具备流程说明、系统锁定的全部待开完整账期、购买方逐字段填写/校验、三项金额填写/勾稽、日期边界、确认/提交/成功/失败和前往状态页。
- 状态页具备账期/号码/时间/金额/提交后状态/原因/结算归属、服务端精确筛选、详情、返回及加载/空/错误/无权限语义。
- 四页不出现 Mock、Demo、会议演示、F01—F10、DYDATA-82/83、演示角色、演示数据及同义提示；接口字段缺失、未生成或错误不以 0、日期或状态补齐。
- `/finance/*` 页面、API、测试和权限 diff 为零；共享 Shell 的财务数组和 admin 行为保持原文不变。

**Verification Method**：
- 先运行 `python -m pytest tests/test_frontend_store_finance_pages.py -q` 确认红灯，再完成实现并转绿。
- 运行 `python -m pytest tests/test_frontend_store_settlement_confirmation.py tests/test_api_store_billing.py tests/test_frontend_user_facing_contracts.py -q`。
- 运行 `npm --prefix apps/web run build` 与 `git diff --check`。
- 运行演示词扫描、`git diff --name-only origin/main...HEAD` 受保护范围检查。
- 浏览器验证 `/settlement`、`/settlement/invoice`、`/settlement/invoice/status` 的 390/768/1440 页面、路由刷新、横向溢出、图标层级与关键状态。

**Evidence**：
- `docs/uat/dydata-81-store-finance-baseline.md`
- `pwScreenShot/dydata-81-store-finance/baseline/`
- `pwScreenShot/dydata-81-store-finance/final/`
- `docs/devlog/20260828_dydata-81-store-finance.md`
- Linear DYDATA-81 验证记录评论

**Failure Handling**：
- 真实 API 字段不足时不前端推导金额或伪造成功；记录差异并保持只读/未开放。
- 任何变更触及 `/finance/*` 页面、财务端接口、财务端测试、财务导航或财务权限时停止，回退该变更并请求 Owner 裁决；门店侧既有账单/发票接口可按最新确认做最小契约修正。
- PRD/Foundation 与临时看板冲突时以 PRD/Foundation 为业务权威；与 2026-08-28 用户最新明确确认冲突时，以最新确认覆盖并登记 Foundation 漂移，不静默选择旧规则。
- 定向测试、构建、响应式、权限或受保护路径检查失败时不得切换最终 4181 或宣称完成。

**完成收尾：状态同步**：
- 本 Task 完成实现、验证和 Foundation 漂移判断后，把完成事实、验证证据、日期、漂移结论和建议下一步提交给 `ai-project-manager`。
- 由 `ai-project-manager` 调度 `delivery-planner` 同步本主计划、任务看板与子计划状态。
- 重新运行 `node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S4 --json`；用户逐页验收前保持“进行中”，不得关闭 DYDATA-81。

**Owner**：AI 执行 -> 人审核

**前置**：Linear DYDATA-81 In Progress；用户明确开始门店端开发；4181 三页基线、真实 API、PRD/Foundation 和设计系统已读取；独立工作树已建立。

**状态**：进行中

**执行状态更新（2026-08-30）**：用户已明确验收最新 UAT，并授权继续完成正式系统合并和生产部署。T1.1 现为唯一进行中 Task；旧自报测试仍不能替代本轮新鲜门禁证据。当前先关闭全量 pytest 中 Playwright 同步 API 与残留事件循环的运行时阻断，再执行完整正式页面、API、权限、构建、视觉和受保护范围验证；全部通过后才切换到 T1.3。
