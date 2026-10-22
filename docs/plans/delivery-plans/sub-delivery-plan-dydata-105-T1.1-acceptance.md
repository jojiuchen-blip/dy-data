# T1.1 全按钮、权限与文件结果验收

## 任务来源

- [主开发计划](main-delivery-plan-dydata-105.md)
- [任务看板](task-kanban-dydata-105.md)
- [DYDATA-105](https://linear.app/keith-lim/issue/DYDATA-105)

#### T1.1 验证最终集成版本的全部目标交互

**Requirement ID**：DYDATA-105 验收标准 A/B/C；本任务是已确认方案中的验证收尾，不代表生产写入或发布授权。

**PRD 双链·读**：
- 机器可校验入口：`docs/prd/mainprd-dy-data.md`、`docs/prd/prd-feature-list-dy-data.md`、`docs/prd/subprd/02-subprd-store-settlement.md`、`docs/prd/subprd/03-subprd-order-fee-details.md`、`docs/prd/subprd/04-subprd-invoice-registration.md`、`docs/prd/subprd/05-subprd-finance-promotion.md`、`docs/prd/subprd/06-subprd-finance-management.md`、`docs/prd/subprd/07-subprd-finance-store-info.md`、`docs/prd/subprd/08-subprd-finance-disputes.md`、`docs/prd/subprd/09-subprd-finance-imports.md`、`docs/prd/foundation/foundation-api-dy-data/billing-invoice.md`、`docs/prd/foundation/foundation-api-clue-center/lead-query-and-contact.md`、`docs/rules/account-access-control.md`。
- [mainprd 全局规则](../../prd/mainprd-dy-data.md#全局设计规则) 与 [功能列表](../../prd/prd-feature-list-dy-data.md)。
- [账单确认](../../prd/subprd/02-subprd-store-settlement.md)、[费用明细](../../prd/subprd/03-subprd-order-fee-details.md) 的筛选/导出、[发票登记](../../prd/subprd/04-subprd-invoice-registration.md)。
- [推广费](../../prd/subprd/05-subprd-finance-promotion.md)、[管理费](../../prd/subprd/06-subprd-finance-management.md)、[门店信息](../../prd/subprd/07-subprd-finance-store-info.md)、[异议](../../prd/subprd/08-subprd-finance-disputes.md)、[四类导入](../../prd/subprd/09-subprd-finance-imports.md)。
- [财务 API](../../prd/foundation/foundation-api-dy-data/billing-invoice.md)、[线索查询/导出](../../prd/foundation/foundation-api-clue-center/lead-query-and-contact.md)、本轮已更新的账号访问规则。

**核心逻辑**：

验证冻结集成提交，按实际路由展开按钮台账。当前源码至少覆盖下表 11 个逻辑页、12 条正式路径与 2 个别名；共享组件可以复用证据，但推广/管理方向及参数保留必须分别验证。盘点发现其他入口时补入，不能把本表当成允许遗漏的封闭清单。

| 路径/逻辑页 | 必验动作类别 | 初始状态 |
|---|---|---|
| `/ranking` | 月度/累计、账期/产品/门店筛选、重置、排序、下钻、下载 | 未测 |
| `/settlement` | 筛选、版本、双费方向、确认/取消、异议入口、订单下钻、下载 | 未测 |
| `/details` | 两费用方向、全部筛选、查询/重置、分页/页大小、详情、导出全部命中 | 未测 |
| `/settlement/invoice` | 上下文、登记/校验/提交/取消、历史和错误反馈 | 未测 |
| `/settlement/invoice/status` | 筛选、状态、详情/历史、下载 | 未测 |
| `/finance/promotion` | 单月/累计、指标/筛选/分页、发票/订单下钻、下载 | 未测 |
| `/finance/management` | 单月/累计、指标/筛选/分页、厂家扣款/发票/订单下钻、下载 | 未测 |
| `/finance/orders/promotion`、`/finance/orders/management` | 方向固定、筛选/查询/重置、分页 20/50/100/200/500、详情、全结果导出 | 未测 |
| `/finance/stores` | 基础/SAP 两页签、搜索、分页、大于 50 条、差异过滤、下载 | 未测 |
| `/finance/disputes` | 搜索/筛选/分页、查看/处理、确认/取消、版本冲突与结果回读 | 未测 |
| `/finance/imports` | 四模板下载、CSV/XLSX 上传、预览、错误分页/下载、首次/无变化/差异、提交/取消、更正/历史、重复/冲突 | 未测 |
| `/invoice`、`/finance` | 跳转目标、查询参数和可返回上下文 | 未测 |

补充验证 `/admin/accounts`、角色权限、SKU 手工/批量/导入发布、结算范围发布、手动重算和 `/clues/details` 批量筛选。Shell 公共按钮登记一次后验证各角色权限，不重复冒充业务按钮数量。

每条按钮证据至少包含：`页面/按钮、代码版本、角色、数据范围、合成前置数据、预期、实际、证据、结果`。结果只使用通过、失败、未测、阻断及明确原因；浏览器 mock 测试注明局限。

**核心文件**：
- `apps/web/src/App.tsx`、`apps/web/src/components/Shell.tsx` 与上述路由对应的页面。
- `tests/test_finance_export_browser.py`、`tests/test_api_finance_imports.py`、`tests/test_api_fee_admin.py`、`tests/test_api_clues.py`、`tests/test_api_clue_scope_regression.py`、`tests/test_project_governance.py`。
- `scripts/verify_postgres_finance_import_concurrency.py` 及既有真实 PG 门禁；候选导出 API 与实际 Nginx 代理配置。
- `docs/devlog/20261022_refactor_log_Keith_Chen.md`、本计划组与 Linear 验证记录。

**完成标准**：
- 当前路由与实际 UI 的全部按钮均进入台账，未测/阻断不包装为通过；别名、隐藏有效路由、抽屉/弹窗和确认/取消均有记录。
- 管理员全国、管理员组织/手动受限、门店、页面无权及失效会话场景验证；服务端不接受 URL/客户端门店参数授予越权。
- 四类导入均使用可丢弃数据，核对预览/提交/幂等/版本冲突/更正后实际业务行和金额；任一非法行正式表零写入，所有错误可下载，取消不提交正式业务版本。预览自身批次与审计写入在隔离库内发生。
- 所有导出核对真实下载文件、列/编码、行数、整数分汇总、完整筛选和授权门店；大于一页时导出所有命中。零数据与来源未就绪/无权限/会话失效区分，不改写既有端点的合理空导出合同。
- 真实 Nginx 回归至少包括 170 个以上授权门店、组织范围重叠、空 CSV 与普通多行 CSV；候选 API 200 与代理 200、实际内容一致。无真实代理资产时该项为阻断。
- 账户/POI 一对多、跨命名空间冲突、混合分隔符、长 ID/前导零、重复、部分/全无匹配、越权、名称合并、移除/清空、分页和导出均以合成数据证实。
- 最终 `git diff --check`、相关/全仓 pytest、Web build、suite 锁/协议/全局文件/路由门禁和必要真实 PG 验证结果已记录；失败或跳过写明实际原因与影响。
- 本地实现、CI、部署、业务验收状态分开；原最高管理员发布失败仍不能复现时保留具体证据缺口；未获具体发布授权不部署、不关闭 issue。

**Verification Method**：
- 浏览器操作本地或隔离候选服务，下载真实 CSV/XLSX 并解析内容；写操作提交后从业务 API/测试数据库回读版本、行数、金额与审计。
- 以真实 Nginx 反代候选 API，构造大范围空数据请求与有效数据请求，记录代理状态/头部字节及 CSV 断言；不能只测序列化函数。
- 真实 PostgreSQL 验证账号最后管理员并发保护、必要导入原子性与冲突；现有脚本仅覆盖单一模板的部分并发场景时补足或标明缺口。
- `python -m pytest`、`npm --prefix apps/web run build`、治理检查和最终提交 CI 按实际执行记录，不复用基线的历史通过计数。

**Evidence**：
- 台账、命令/退出码、测试计数、文件断言、真实代理/PG 证据与剩余风险追加 `docs/devlog/20261022_refactor_log_Keith_Chen.md`，必要时在主线程已分配的新验收文件中细化并回链。
- 浏览器截图放 `pwScreenShot/`，只用合成数据；不提交真实财务导出、凭据、生产基础设施标识或个人路径。
- 当前所有验收项尚未执行，无本轮代码/文件/按钮成功证明。

**Failure Handling**：
- 缺文档或契约冲突回到主线程，保留未测条目；不得按历史百分比声称全部覆盖。
- 环境/测试资产缺失阻断对应发布闸门；不能使用生产写入替代，不能忽略真实代理或 PG 缺口。
- 失败项回交 T0.1 对应切片修复并定向回归，再验证最终集成提交；新的范围提案另行确认。

**Owner**：主 Codex 验证与证据整理，Keith 审核业务结果；技术判断为 AI 执行 -> 人审核。

**前置**：T0.1 完成并通过主线程复核；隔离 API、Web、测试数据、PG/代理/浏览器验证资产按项就绪。

**状态**：待开发

**完成收尾：状态同步**：
- 将验收完成事实、证据、完成日期、foundation 漂移结论及下一步（具体发布准备或业务接受）提交 `ai-project-manager`。
- 由主入口调度 `delivery-planner` 同步主计划、看板与本子计划，并同步驾驶舱和 Linear；未完成同步不得标记已完成。
- 运行 `node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S4 --json` 复核三者一致；仅技术验收完成不得关闭需求或推断生产已生效。
