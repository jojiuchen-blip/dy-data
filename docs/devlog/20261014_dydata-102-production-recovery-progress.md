# DYDATA-102 / DYDATA-103 生产发布与定向恢复进展

## 已验证

- 生产应用版本 `b81c71b248771a72f9f3754578313d67f5bda069` 于 2026-10-14 15:20（Asia/Shanghai）完成发布：[发布记录](https://github.com/jojiuchen-blip/dy-data/actions/runs/38526984533)。五个应用镜像的完整不可变摘要对应同一已验证构建，恢复流程复用这些镜像；环境和数据库备份、容量门禁、迁移、worker 与服务健康检查保留。
- 发布前全量验证为 3575 passed、185 skipped：[验证与原发布记录](https://github.com/jojiuchen-blip/dy-data/actions/runs/38500239200)。首次和第二次发布均在数据库迁移前被容量门禁拦截，未将失败记录视为部署成功。
- 仅回收 unused builder cache：[维护记录](https://github.com/jojiuchen-blip/dy-data/actions/runs/38526379826)。容器 ID、镜像 ID、运行状态、回滚标签和数据卷清单的前后不变量通过，未清理业务数据或降低容量门槛。
- 生产只读核验：[来源与保护基线](https://github.com/jojiuchen-blip/dy-data/actions/runs/38531033697)。九月原始有效核销来源为 10909 行；原始支付金额分布不等于结算实收基数，也不等于合格费用结果。
- 通过 `plan_day_recovery` 为 9 月 14、16、20、25、28 日原失败链创建第 1 代恢复计划：[入队记录](https://github.com/jojiuchen-blip/dy-data/actions/runs/38531465272)。固定请求键保证幂等；原状态、attempt 和 lease 不重置，追加 system 维护审计，不冒充管理员。
- 恢复前后八月费用结果、调整、账单、账单明细、确认五类完整行指纹一致。所有 SQL 核验均在数据库强制只读事务中执行，不导出订单或客户明细。

## 当前未完成

- 九月 30 个自然日中仍有上述 5 日未发布，当前九月费用结果和正式账单仍为空。恢复入队不等于补跑成功，不能用原始数据或累计金额代替九月账单。
- 普通 history 调度受正在运行的 8 月 16 日 settle 任务及更早历史缺口影响。没有清除该任务 lease、改变 attempts、强制并行或终止其运行。
- 已启动仅覆盖五个九月恢复代的定向执行器：[启动记录](https://github.com/jojiuchen-blip/dy-data/actions/runs/38534975273)。它继承原配额类别，使用现有候选、资源检查、`run_daily_child` 和 PostgreSQL 全局 heavy claim 保护；检查 cancel/pause，单实例，有等待上限。启动成功仅说明执行器投递成功。
- [存活核验](https://github.com/jojiuchen-blip/dy-data/actions/runs/38535527676) 确认执行器存活且无异常类记录，仍等待已有 heavy 任务释放执行槽。九月账单、费用明细和金额对账未验收通过。
- 浏览器已观察到财务默认账期为 `2026-09`，推广费用空结果导出显示“已下载仅含表头的文件”。尚未完成非空导出文件内容核对、所有导出按钮和单月/累计一致性验收；Chrome 控制连接中断，等待恢复。

## 后续验收

1. 核实五日恢复代真实 claim、attempt、collect/materialize/settle/finalize 和发布完成。
2. 验证九月月结就绪、自动发布及账单生成，核对来源、费用、调整、账单明细、总览和导出金额。
3. 比较八月及确认/锁账事实保护基线，解释合法变化，禁止自动确认、开票或付款。
4. 恢复浏览器连接后核对默认上月、显式月份筛选、八月起累计和各导出文件内容。
5. 回填 Linear 与 PR；当前保持 In Progress，不宣告完整交付。
