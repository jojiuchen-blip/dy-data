# T0.1 PDCA 独立只读证据接口

## 任务来源

- [主开发计划](main-delivery-plan-pdca-readonly.md)
- [任务看板](task-kanban-pdca-readonly.md)

#### T0.1 新增独立证据读取接口

**Requirement ID**：REQ-PDCA-READONLY-001（用户授权本次不建票）

**PRD 双链·读**：
- `mainprd-dy-data.md`
- `../../prd/foundation/foundation-schema-dy-data/existing-read-dependencies.md`
- `../../prd/foundation/foundation-schema-clue-center/raw_douyin_refund_record.md`
- [mainprd](../../prd/mainprd-dy-data.md)：全局权限、金额及错误边界。
- [既有只读依赖](../../prd/foundation/foundation-schema-dy-data/existing-read-dependencies.md)。
- [退款结构](../../prd/foundation/foundation-schema-clue-center/raw_douyin_refund_record.md)：与当前模型有漂移，必须核对。
- `apps/api/dy_api/models.py`、`ranking_source_evidence.py`、`routes/ranking_sources.py`、`auth.py`。
- `tests/test_ranking_source_evidence.py`：保留原行为，不能用其测试替代新接口测试。

**核心逻辑**：
- 独立新增 `GET /api/v1/admin/pdca-source-evidence`，不修改原证据接口。沿用最高管理员权限边界，不新增高权限 Token。
- 成交集合以 `create_order_time` 在上海时区所选闭开区间为准；没有券、核销或线索的原始订单仍保留。不按核销成功与否筛分母；缺下单时间的覆盖问题明确提示。
- 数据集拟包含 orders、coupons、verifications、refunds、sku_rules、poi_mappings；仅查询当前模型已存在且语义核实的字段。订单/券/事件稳定标识保持字符串；金额整数分，缺值为 null，未经证实的默认零不得当真实零。
- SKU 与商品 ID 显式映射；只读返回现有规则，20商品白名单与168/268合并在PDCA核验，不修改源配置。
- 退款原因如无可靠已采集字段，返回 unavailable；不扫描或输出任意 raw_payload，不新增采集。
- 查询最多7天、每页1–500条，绑定数据集/范围/截止/契约版本的 keyset 游标；PG查询8秒、锁等待1秒。事件截止仅为筛选参数，不能当源采集完成时间。
- 元信息明确非一致性快照、源覆盖未知、字段可用性。不能证明的完整截止为null。不写业务表，不自动刷新物化表，不触发采集或任务。

**核心文件**：
- 新建 `apps/api/dy_api/pdca_source_evidence.py`、`apps/api/dy_api/routes/pdca_sources.py`、独立 Pydantic 契约文件。
- `apps/api/dy_api/main.py` 仅新增 import/include_router；不得改旧路由。
- 新建 `tests/test_pdca_source_evidence.py`、`docs/api/pdca-source-evidence.md`。
- 不修改 `models.py`、worker、原 ranking 模块或迁移。

**完成标准**：
- 合成数据覆盖无券未核销、历史分配、撤销重核销、退款、孤立关联、长ID、缺金额及未知原因；无券订单在订单数据集中保留。
- 匿名401、非最高管理员403；错误不包含SQL、连接信息或原始业务载荷。
- 对新接口记录SQL操作，业务INSERT/UPDATE/DELETE为0；读前读后业务行对比一致。若认证依赖触发写入，不改变旧依赖而报告阻断。
- 分页无重复键，非法/跨查询游标拒绝，超时安全失败，未知截止始终不宣称完整。
- 原证据接口契约及已有看板测试保持通过；未验证项目不得标记完成。

**Verification Method**：
- 先运行新增专项测试观察失败，再实现并执行 `python -m pytest tests/test_pdca_source_evidence.py tests/test_ranking_source_evidence.py`。
- 执行 `git diff --check`、`python -m pytest`、`npm --prefix apps/web run build`。
- 在隔离测试库对同订单集合逐单核对订单、券、事件与退款；生产联调和部署不在当前授权范围。

**Evidence**：
- 实测结果、SQL零写入结论及兼容性结果通过项目 devlog 技能记录到 `docs/devlog/`，并在本节补相对链接；当前尚无源接口测试结果。

**Failure Handling**：
- 契约/文档漂移先核对，不猜状态枚举或金额优先级；缺失字段标未知。
- 需数据库迁移、改采集、改旧逻辑或生产部署才能继续时，停止请求新授权。
- 来源不完整、不可证明截止或对账不一致时，PDCA不切换主源。

**Owner**：AI 执行 -> 人审核

**前置**：本专项计划审阅通过；相关 foundation 补读和契约漂移处理；工作区冲突核对；计划一致性和环境门禁。

**状态**：进行中

### 当前执行更新（2026-09-21）

用户已恢复执行并批准独立只读认证、API专用发布与短暂API重启。此更新取代下方历史暂停及“生产部署不在授权范围”的当前效力；不扩大到迁移、采集、前端或业务数据修改。必要网关平滑重载仍待明确许可。

发布候选基于已核实线上提交d36d991b。旧证据接口和迁移基线85项通过；新增接口、真实应用路由及旧证据接口53项通过；隔离PostgreSQL强制只读测试3项通过；前端构建、治理122项通过。独立审查无Critical/Important，超长源键分页边界保留为Minor。首次候选全量运行在1445通过、31跳过后因测试启动编码不一致失败；统一UTF-8后失败用例通过，完整重跑中。没有修改旧业务代码或测试断言。

证据见[当日开发日志](../../devlog/20260921_refactor_log_Your_Name.md)、[接口说明](../../api/pdca-source-evidence.md)及[限定发布检查表](../../api/pdca-api-release-checklist.md)。已完成线上只读状态检查和网关配置检查；候选未上传、未部署、未启用主源切换。任务仍为进行中。

### 用户暂停检查点（2026-09-20）

用户要求暂停保存，等待回来继续。已停止全量测试并中断独立审查，不继续后台执行。新增接口及独立认证模块已保存；main.py仅新增路由注册。专项含旧接口回归46项通过，前端构建通过；全量测试中出现失败但在输出最终详情前被中断，不能称全量通过。PostgreSQL实测、独立审查、生产部署及PDCA新接口接入尚未完成。恢复后先核对失败记录与审查，再推进；不修改生产或旧业务逻辑。

用户已在上述风险说明后明确“确认”，批准新接口独立只读认证及只读事务。保留原认证、权限和数据库模块不变；复用签名验证但不调用带初始化副作用的原身份依赖。

## 开工检查发现：原认证依赖存在写入

- `auth.py:466` 的 get_current_user 调用 effective_page_keys。
- `access_control.py:68` 的 ensure_access_control_seed 会添加 AccessPage、RolePagePermission，并可能更新 D10 权限；显式 flush。最高管理员同样经 page_rows 进入此路径。
- `db.py:70` 的 session_scope 正常返回时 commit。因此原 GET 身份校验不能保证请求零写入；这是代码路径证据，未执行生产请求，不能宣称本次发生了生产写入。
- 按已审阅计划的失败分支停止源代码实施，不修改原 auth/access_control/db 或任何旧接口。
- 拟新增仅供 pdca-source-evidence 使用的只读认证与独立只读数据库事务；复用原会话签名校验，仍要求最高管理员，并核验账号启用、初始化和 auth_version 等条件；不触发权限初始化、不放宽权限、不更改登录流程。该安全设计需确认后继续。

**完成收尾：状态同步**：
- 完成实现、验证和 foundation 漂移判断后，将完成事实、验证证据、完成日期、漂移结论和下一步建议提交给 ai-project-manager。
- 由 ai-project-manager 调度 delivery-planner 同步本组主计划、看板和子计划。
- 同步后执行 `node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S4 --json`，并确认三份计划一致；未完成同步不得标记完成。
