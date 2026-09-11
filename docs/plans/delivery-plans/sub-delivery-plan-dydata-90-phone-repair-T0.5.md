# T0.5 DYDATA-90 号码补偿

- 主开发计划：[main-delivery-plan-dydata-90-phone-repair.md](main-delivery-plan-dydata-90-phone-repair.md)
- 任务看板：[task-kanban-dydata-90-phone-repair.md](task-kanban-dydata-90-phone-repair.md)

#### T0.5 有界号码补偿和生产可用性

**Requirement ID**：DYDATA-90

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` §1
- `docs/prd/foundation/foundation-api-clue-center/lead-query-and-contact.md` 联系方式
- `docs/prd/foundation/foundation-schema-clue-center/clue_center_order.md` 号码派生字段
- `docs/prd/foundation/foundation-api-clue-center/jobs-security-and-migration.md` J01、J03

**核心逻辑**：
- 当前有效正式轮次的缺失/失效号码缓存由worker有界恢复，覆盖新分配与存量；独立游标公平回绕。
- 复用当前raw来源顺序与指纹，网络调用不持有业务事务；回写复核源与轮次，条件更新仅号码字段。
- 复用worker受治理客户端，短超时有限重试，失败冷却与脱敏统计；不改变分配与自动超期。

**核心文件**：
- `apps/worker/clue_phone_recovery.py`
- `apps/worker/scheduler.py`
- `tests/test_clue_phone_recovery.py`
- `tests/test_clue_phone_recovery_postgres.py`

**完成标准**：
- 新分配和旧指纹失效的号码可被恢复，已有有效缓存不重复请求。
- 失败重试、游标公平、并发唯一消费者、来源变化和终态变化均不会错误回写。
- 真实PG提交回读与真实API号码消费通过；生产缺口处理结果可复核。
- 不新增API凭证，不修改分配、原始、财务事实。

**Verification Method**：
- `python -m pytest -q tests/test_clue_phone_recovery.py tests/test_clue_phone_recovery_postgres.py`
- `python -m pytest -q tests/test_formal_allocation_runtime.py tests/test_worker_clue_center.py tests/test_api_clues.py`
- `python -m pytest`
- `npm --prefix apps/web run build`
- `git diff --check`

**Failure Handling**：
- 外部失败保持待恢复，冷却重试；日志仅类型及计数，无号码、密文、凭证。
- 数据库失败回滚，不推进错误检查点；旧源/失效轮次跳过回写。

**Owner**：AI

**前置**：T0.4已部署；用户确认修复电话问题。

**状态**：进行中

**完成收尾：状态同步**：
- 主代理复核后回填测试、发布和生产号码验收，用户验收前不自行关闭issue。
- 2026-09-10：已整合worker实现（独立工作树提交8adcca6b），主代理补充调度聚合日志与API消费、游标保留、超时不回写用例；专项50 passed，Web构建通过；全仓回归与生产恢复待完成。
