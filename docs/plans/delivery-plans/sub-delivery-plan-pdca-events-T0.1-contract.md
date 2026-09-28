# T0.1 PDCA 证据契约 Sub Delivery Plan

## 任务来源
[主计划](main-delivery-plan-pdca-events.md)；[看板](task-kanban-pdca-events.md)

#### T0.1 独立只读快照接口
**Requirement ID**：LOCAL-PDCA-EVENTS-20260928
**PRD 双链·读**：
- `mainprd-dy-data.md` 全局设计规则

**核心逻辑**：新增版本化 GET 快照 API，数据库只读且单事务一致，冻结明确字段后分页；所有源缺口显式返回，永不自动发布。原接口和计算逻辑不变。
**核心文件**：
- `apps/api/dy_api/pdca_snapshot_schema.py`：严格响应模型。
- `apps/api/dy_api/pdca_snapshot_projection.py`：有界字段投影及缺口。
- `apps/api/dy_api/pdca_snapshot_store.py`：有界短期不可变分页。
- `apps/api/dy_api/routes/pdca_sources.py`：新增路由。
- `tests/test_pdca_snapshot.py`：合成数据与真实应用路径。

**完成标准**：完整返回限定订单母体，不因核销/分配/退款过滤；退款成功状态、部分退款、时间未知、核销撤销和重核关系不混淆；水位未知阻断发布；分页时修改源不改变已冻结快照；跨用户/过期/错游标拒绝；执行 SQL 无业务写入；原 v1 回归通过。
**Verification Method**：先红后绿执行 `pytest tests/test_pdca_snapshot.py`；随后运行 PDCA 专项及全仓 `pytest`；`git diff --check`；生成 OpenAPI schema 与合成样例。真实 PostgreSQL/生产未运行不得写成通过。
**Evidence**：`docs/devlog/20260928_refactor_log_Your_Name.md`
**Failure Handling**：缺库/表503；缺历史明确缺口；测试失败修复本任务范围，否则记录基线限制。
**完成收尾：状态同步**：同步主计划、看板、子计划和开发日志；本地代码通过不代表正式指标或生产部署验收。
**Owner**：本任务 AI 执行，用户审核
**前置**：用户本次免建票并授权继续开发
**状态**：进行中

## 执行步骤

本次券查询增量只将重复订单子查询替换为同事务已完整受限读取的订单 ID，不改变字段/券状态/排序/超时。新增结果等价、空集合、行数与传输保护测试先红后绿；PostgreSQL 并发快照和最多 20,000 订单绑定测试已补充，但本机无运行环境而尚未执行。实际有界查询仍需验证；未经再次确认不发布。

- [x] 失败测试：母体/事件/金额/缺口/快照/鉴权/只读。
- [x] 最小实现，专项回归。
- [x] 完整回归记录与契约 schema/样例/映射交接。
- [x] 真实PostgreSQL隔离CI：94通过、0跳过；见开发日志。
- [ ] 草稿PR代码交付待审核，不含生产发布与正式指标验收。
