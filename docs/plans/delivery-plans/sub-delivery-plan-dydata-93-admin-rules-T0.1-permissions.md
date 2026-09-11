# T0.1 管理员分账规则发布权限

## 任务来源

- [主开发计划](main-delivery-plan-dydata-93-admin-rules.md)
- [任务看板](task-kanban-dydata-93-admin-rules.md)

#### T0.1 最小权限发布闭环

**Requirement ID**：DYDATA-93

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md`：全局设计规则
- `docs/prd/foundation/foundation-api-dy-data/sku-fee-admin.md`：§5、§9、§13
- `docs/prd/foundation/foundation-api-dy-data/common-contract.md`：§5
- `docs/rules/account-access-control.md`：§1～4、§6、§9

**核心逻辑**：

发布前置增量（2026-09-10 用户同意）：从已提交 aa3373a、bab2612、52500ae 恢复 DYDATA-87 已验证采集分页、门店归属保护与相关回归，仅对这些明确文件做集成；保留当前主线线索代码。重新运行最终整合树的采集、权限、线索与全量门禁；不触发真实补算，不带入 DYDATA-87 未提交代码。
已授权 D03 的有效普通管理员可创建单条费率和提交导入批次；手工多选继续使用单条 API。get_current_user 的页面准入不得绕过；最高管理员原能力不变，门店账号不得发布。
手动重建与结算范围发布继续最高管理员。检查前端会话角色，隐藏或明确禁用无权重建入口，不自动升级账号、不要求以最高管理员重新登录。保留规则校验、审计、幂等和入队事务。AI 执行 -> 人审核。

**核心文件**：
- apps/api/dy_api/routes/fee_admin.py
- apps/api/dy_api/auth.py（核对，避免全局修改）
- apps/api/dy_api/access_control.py（核对 D03 映射）
- apps/web/src/pages/AdminSkuRulesPage.tsx
- tests/test_api_fee_admin.py
- docs/rules/account-access-control.md
- docs/prd/foundation/foundation-api-dy-data/sku-fee-admin.md

**完成标准**：
- 实际登录的 admin 有 D03 时，单条发布和导入 commit 成功，刷新回读相同版本；同幂等键不增加版本或重算任务。
- 未登录、失效会话、无 D03 的管理员、门店角色发布失败，规则和任务计数不变。
- admin 手动重建和发布结算范围仍 403；最高管理员原能力通过回归。
- 无效生效日、费率、批次冲突仍拒绝；原子导入失败无部分写入。
- 隔离页面普通管理员无需重新以最高管理员登录即可发布；无权手动重建不伪装成可操作。
- 全量测试、构建、审查和发布证据记录；业务金额与 DYDATA-87 分开验收。

**Verification Method**：
先运行 git diff --check；采用现有 tests/test_api_fee_admin.py 隔离数据库和真实登录模式增加 RED/GREEN 权限矩阵，再运行相关权限测试、python -m pytest、npm --prefix apps/web run build。隔离浏览器操作合成 SKU，核对回读与按钮状态；禁止生产测试写入。

**Evidence**：
测试输出及脱敏观察回填 Linear DYDATA-93，必要开发记录置 docs/devlog/；浏览器截图置 pwScreenShot/dydata-93/，不提交账号凭据或真实业务导出。当前仅静态取证，尚无 RED/GREEN 结果。

2026-09-10 实装后：两项真实登录发布红测403，最小修复后67项相关回归通过；GET回读追加2项通过。Web build退出0（既有大包警告）；独立审查Critical/Important均0。新增 tests/test_visual_admin_rule_permissions.py 使用真实FastAPI、内存隔离库与浏览器真实登录，普通管理员发布、刷新回读、重复日期冲突及手动重建禁用1项通过。全量pytest正在运行，日志 logs/dydata93-full-tests.xml；未提交或部署。

**Failure Handling**：
上游契约缺失、未经确认的权限扩展、页面授权与角色冲突时停止对应修改并记录；验证环境缺失时不部署，不用生产代替隔离测试。其他窗口重叠文件须先协调。

**Owner**：当前 AI 执行 -> 用户审核

**前置**：本计划审阅通过；环境与一致性门禁通过

**状态**：进行中（2026-09-10 用户审阅通过）

**完成收尾：状态同步**：
实现、验证及 foundation 漂移判断后，向 ai-project-manager 提交完成事实、证据、日期和下一 Task 建议；由 delivery-planner 同步主计划、看板、子计划，运行 route-check.mjs --target-stage S4 --json。同步和用户验收未完成，不标记已完成。
