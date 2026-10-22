# T0.1 权限、导出与批量筛选集成

## 任务来源

- [主开发计划](main-delivery-plan-dydata-105.md)
- [任务看板](task-kanban-dydata-105.md)
- [DYDATA-105](https://linear.app/keith-lim/issue/DYDATA-105)

#### T0.1 实现已确认的 A/B/C 有界集成

**Requirement ID**：DYDATA-105 A、B、C；确认原话“管理员可以有账号新增、变更权限，但不能删除；其他可以一致”。

**PRD 双链·读**：
- 机器可校验入口：`docs/prd/mainprd-dy-data.md`、`docs/rules/account-access-control.md`、`docs/prd/foundation/foundation-api-dy-data/common-contract.md`、`docs/prd/foundation/foundation-api-dy-data/sku-fee-admin.md`、`docs/prd/foundation/foundation-api-clue-center/lead-query-and-contact.md`、`docs/prd/foundation/foundation-schema-dy-data/existing-read-dependencies.md`、`docs/prd/subprd/09-subprd-finance-imports.md`。
- [mainprd 全局规则](../../prd/mainprd-dy-data.md#全局设计规则)；[账号访问规则](../../rules/account-access-control.md)。
- [API 公共权限与幂等](../../prd/foundation/foundation-api-dy-data/common-contract.md)；[SKU 费率](../../prd/foundation/foundation-api-dy-data/sku-fee-admin.md)。
- [线索查询公共条件与导出](../../prd/foundation/foundation-api-clue-center/lead-query-and-contact.md)；[门店/POI 既有映射](../../prd/foundation/foundation-schema-dy-data/existing-read-dependencies.md)。
- [财务导入 §3](../../prd/subprd/09-subprd-finance-imports.md#3-四类模板导入)；其他按钮按主计划索引进入对应 PRD，不改写金额口径。

**核心逻辑**：

| 切片 | 规则与实施责任 | 接受条件 |
|---|---|---|
| A 角色与账号 | 合并为 admin，固定全部页面，保留密码、启用状态、组织与手动门店范围及审计；迁移旧角色/页面 override 并使旧会话重验。全国管理员可新增/变更任何角色；受限管理员仅管理门店账号，目标全部门店须为自身授权集合子集，不能管理管理员或扩大授权。无账号删除能力。 | 服务端防绕过、并发最后有效全国管理员保护、旧 Web/CLI/MCP 令牌重验、普通门店不提权；UI 与 API 同规则 |
| A 全局写 | 页面可进入与数据可操作分离；全局 SKU/角色默认值/数据同步/全局重算仅全国范围管理员可写。受限管理员显示影响范围说明并禁用；发布错误按实际原因反馈。 | 单条/批量/导入/范围发布和手动重算各有权限及冲突用例；“重新计算结算结果”说明发布自动排队，不等于补采、确认或付款 |
| B 导出 | 仅在响应元数据边界移除内部展开授权数组并限定公开元数据容量；实际查询范围不动。覆盖共享 helper 的线索轮次、订单费用、订单明细导出；空结果与大量授权门店也安全。 | 实际文件内容与权限不变，元数据长度有硬边界；真实 Nginx 代理回归由 T1.1 验证 |
| B 按钮缺陷 | 核查财务固定 50 条、SAP 差异导出上限与别名参数等已调查风险，修复有真实证据的缺陷。 | >50 条分页可到达完整结果，筛选/重置/下钻与导出同口径；不将候选风险直接称为已复现缺陷 |
| C 批量筛选 | 按字符串规范宽度、解析混合空格/分号/斜杠/换行/tab；精确解析所属账户和 POI，保留长 ID 与前导零；同批 OR，与其余条件 AND，并入名称选择，去重、逐项移除、清空可见。解析服务端按当前授权重验。 | 一对多完整纳入；跨命名空间冲突取授权匹配并标来源；不存在/无权统一未匹配，全部未匹配保持零或阻止应用，不能返回全量 |
| C 一致条件 | 列表、总数、统计与已有导出复用有效选择条件；筛选变化页码归 1。容量上限经实际请求/数据库边界评估后明确报错，禁止截断。 | 直接构造越权请求仍拒绝或零结果；不把客户端 ID 列表当成授权范围；现有仅看自店核销条件继续独立 AND |

主线程做权限与跨切片判断（AI 执行 -> 人审核）。A/B/C worker 各自隔离写集，未获主线程复核的提交不能视为集成结果。

批量筛选实现合同由主线程在同一方案内确定：新增只读 `POST /api/v1/clues/assignment-rounds`、`POST /api/v1/clues/assignment-rounds/export` 与 `POST /api/v1/clues/filter-options/stores/resolve`，旧 GET 保持兼容；POST 只承载查询条件，不写业务记录。`assigned_store_ids=null` 表示未加所选门店条件，`[]` 明确表示零结果。ID 按 NFKC 规范化后的字符串精确匹配当前 `DimAwemeAccount.account_id` 或 `DimStorePoiMapping.poi_id`；不把任意内部 `store_id` 作为粘贴 ID 回退匹配。原始输入最多 128,000 字符、单个 ID 最多 128 字符、去重后最多 1,000 个输入 ID、最终最多 1,000 个所选门店，任一超限整次明确拒绝，不截断。此容量合同需在实际请求、映射查询与导出回归中验证；客户端不得提交内部 `scope_store_ids` 授权条件。

**核心文件**：
- A：`apps/api/dy_api/access_control.py`、`apps/api/dy_api/auth.py`、`apps/api/dy_api/routes/admin.py`、`apps/api/dy_api/routes/fee_admin.py`、`alembic/versions/`（新角色迁移）；`apps/web/src/pages/AdminAccountsPage.tsx`、`AdminSkuRulesPage.tsx`、`apps/web/src/components/AccountScopePicker.tsx`、`AdminSkuRuleImportDrawer.tsx`；`docs/rules/account-access-control.md`。
- B：`apps/api/dy_api/routes/_data.py` 的 `export_filter_header`、`apps/api/dy_api/routes/clues.py`、`dashboard.py`；`apps/web/src/pages/FinanceFeePage.tsx`、`FinanceStoresPage.tsx`、`FinanceDisputesPage.tsx`、`apps/web/src/App.tsx`。
- C：`apps/api/dy_api/routes/clues.py`、`_data.py`、`apps/api/dy_api/models.py` 的现有账户/POI 维度只读关系；`apps/web/src/pages/ClueCenterPage.tsx`、`apps/web/src/components/SearchableStoreSelect.tsx` 与必要的多选组件/API 类型。
- 测试：`tests/test_api_fee_admin.py`、`tests/test_api_clues.py`、`tests/test_api_clue_scope_regression.py`、`tests/test_finance_export_browser.py`；扩展当前权限/迁移测试并新增边界用例。

以上是责任工作面，主线程须在分派时把 `_data.py`、`clues.py` 等潜在共享文件指定给唯一切片或串行接线；不能让隔离工作树成为无审查重叠修改的理由。

**完成标准**：
- 两类旧管理员迁移后统一功能；数据库范围前后集合一致，密码哈希、状态、审计未丢失；旧会话按版本重验，门店账号没有新增页面或写能力。
- 全国/受限账号新增变更均有允许与拒绝回归；无法删除账号；最后有效全国管理员的并发变更不能使系统失去管理入口。
- 全局写后端对受限管理员拒绝，页面呈现具体原因；原发布失败未复现的具体场景保持证据缺口，不能以改名宣布修复。
- 3 个共享导出调用者经过大授权范围与空结果测试，响应头不含内部授权数组且尺寸固定受限；下载数据/权限与修复前目标口径一致。
- 批量解析混合分隔符、重复、空值、长 ID/前导零、部分/全部未匹配、一对多、冲突、越权、名称合并和清空都有回归；列表、总数、导出指向同一授权集合。
- 定向 pytest 与 Web build 通过；交接给 T1.1 的待验资产、foundation/API 漂移和未复现问题明确列出，未生产试写或部署。

**Verification Method**：
- 针对角色/范围/会话、发布/重算、迁移和账号事务分别运行相关测试；用合成用户/门店比较迁移前后集合与哈希，模拟并发变更与旧令牌。
- 对导出解析真实 CSV 字节而非仅 HTTP 状态；使用 170 个及更大授权数组、组织重叠、零行、多行、中文公开筛选及越权范围，检查内容和响应头长度。
- API 与前端对同一批 ID 样本核对精确匹配、去重、条件组合、页码和全部导出；明确候选选项前 50 条不能限制 ID 解析。
- `git diff --check`；`npm --prefix apps/web run build`；专项命令、退出码、跳过原因按实际执行记录。

**Evidence**：
- 具体测试命令、计数、集成提交、截图/文件断言和缺口记录在 `docs/devlog/20261022_refactor_log_Keith_Chen.md`；浏览器截图位于 `pwScreenShot/`，只保留合成数据。
- 初始状态：尚无本轮实现或验收成功证据。T1.1 接收冻结提交和实际测试输出，不复用历史 CI 冒充本轮结果。

**Failure Handling**：
- PRD/文件定位失败时停止受影响切片；契约与本轮确认冲突提交主线程裁决并同步当前说明，不猜业务。
- 缺 PG、浏览器或 Nginx 时保留相应未测/阻断；不得使用生产库进行写试验，不能删掉保护测试以变绿。
- 新业务范围或权限取舍不在此 Task 内自动决定；所有实际失败留下请求/错误码与合成复现证据，不记录密钥或真实导出数据。

**Owner**：主 Codex 集成与审查；隔离 worker 有界执行；Keith 审核业务结果。

**前置**：用户已审阅确认调查方案与上述账号修订；suite/计划/当前任务环境门禁通过。

**状态**：进行中

**完成收尾：状态同步**：
- 完成实现、验证和 foundation 漂移判断后，将完成事实、验证证据、完成日期、漂移结论和建议下一 Task（T1.1）提交 `ai-project-manager`。
- 由主入口调度 `delivery-planner` 同步主开发计划、看板及本子计划状态；同步 `docs/plans/execution-plan.md` 当前入口。
- 重新运行 `node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S4 --json` 确认三者一致；未完成该收尾不得标记 T0.1 已完成。
