# 开发日志 — 2026-09-10

## DYDATA-90 采集修复发布

- 用户明确授权提交、部署；修复提交6d130598，生产提交8a753e9f094b1b7546127921949c19e28d04571a，本地及远端main已同步。
- 集成origin/main以保留生产已有财务与浏览器依赖修复；新增20260909_0052汇合两个0051，不修改历史迁移。
- 原结算指标视觉失败来自即时count断言抢在异步文案渲染前执行；改用等待式断言，保留全部文案与布局断言。
- 本地211项集成、2项分支升级、6项界面验证通过；独立合并复查无阻断。
- [发布流水线](https://github.com/jojiuchen-blip/dy-data/actions/runs/34370984418)成功：真实PostgreSQL门禁、2685 passed / 152 skipped、前端与全部发布镜像构建通过。
- 生产于北京时间00:10:52完成发布；API、worker、browser、ops-agent、PostgreSQL健康，Web和proxy运行。
- 7份运行源文件与发布Git对象SHA256完全一致，订单修改查询入口可调用；数据库为20260909_0052，新增可空phone_source_fingerprint字段存在。
- 公网首页200，未登录auth/me及MCP401，agent manifest200。
- auto_sync_enabled=false，未开启旧同步；本次未证明完整日数据采集或历史补齐成功。新日批、两小时维度刷新和动态预算由DYDATA-90继续承接。

## 备份与恢复

- 环境备份：/opt/dy-dashboard/logs/backups/pre-production-cutover-20260909T160757Z.env。
- 数据库备份：/opt/dy-dashboard/logs/backups/pre-migrate-20260909T160823Z.dump。
- 原api、worker、web、browser、ops-agent镜像保留rollback-dydata90-20260909标签。必要时用原release的compose与保留镜像重建应用服务，--no-deps避免触发迁移；本次新增字段兼容原应用，不通过删列回滚。
- 详细脱敏核验：output/dydata90-production-postflight.json、output/dydata90-deploy-run.txt。

## 后续

- 实施并验收新的调度机制后，再开启自动同步。
- 本次没有新增foundation契约，迁移汇合仅整合既有字段设计。
- 经验：发布前核对运行制品和最新主线，不能只依据服务器仓库HEAD。仅记录，不新增全局规则。
---

## 补充更新 1（09:35 · 窗口 1）

### 任务 2：DYDATA-90 正式分配业务确认与严格资格修复
- **目标**：将用户确认规则补入 BRD，并接通正式首次分配
- **操作**：更新 BRD 第3.6节及其台账；支付成功必须有待使用证据；补齐数字状态候选；在隔离工作树实现运行时
- **结果**：资格和物化回归98项、分配/API回归55项、隔离本地 PostgreSQL 投影与跟进11项通过；运行时和全量验证仍在进行
- **涉及文件**：docs/brd/BRD-clue-center-20260721-2134.md、apps/worker/order_status.py、apps/worker/clue_allocation.py、apps/worker/clue_center.py
---

## 补充更新 2（09:47 · 窗口 2）

### 任务 3：正式首次分配运行时及 PostgreSQL 事务验证
- **目标**：接通每批正式分配，并以独立补偿覆盖历史待首次分配线索
- **操作**：中心投影每64条提交后通知；priority_daily 独立每60秒补偿，每轮最多100条与10秒处理预算；主记录锁后复核原始状态；跨进程排他、每条事务提交、持久游标和脱敏汇总；自动超期强制保持关闭
- **结果**：组合回归79项通过，含真实 PostgreSQL 并发排他和失败回滚恢复2项；后续新增旧轮次关联保护及调用接入测试通过；全仓回归仍在运行并出现待定位失败
- **涉及文件**：apps/worker/formal_allocation_runtime.py、apps/worker/daily_task.py、apps/worker/scheduler.py、tests/test_formal_allocation_runtime.py、tests/test_formal_allocation_runtime_postgres.py
---

## 补充更新 3（10:05 · 窗口 3）

### 任务 4：DYDATA-90 正式分配本地验收收口
- **目标**：完成用户确认的 BRD 与代码修复，保留生产证据边界
- **操作**：固定代码后完成最终组合复测，核对 PostgreSQL 排他与事务、BRD台账、治理文件和 Git 差异；测试 PostgreSQL 已停止
- **结果**：最终组合110 passed；PostgreSQL 13 passed。全仓初测2725 passed/156 skipped/5 failed：4项缺失TypeScript依赖，1项inspect.getsource因进程中源码行号变化读取整模块；补依赖并固定代码后五项均在110项组合复测中通过。未重新执行第二次完整全仓，不宣称一次全绿。BRD lint无失败，人工复核指标、角色和确认来源保持一致；suite锁和治理检查通过。BRD与代码本地完成，分支codex/dydata-90-formal，未合入main或部署。本任务无foundation漂移。
- **涉及文件**：docs/brd/BRD-clue-center-20260721-2134.md、apps/worker/formal_allocation_runtime.py、docs/plans/execution-plan.md
---

## 补充更新 4（10:19 · 窗口 4）

### 任务 5：正式分配发布前修正新旧调度开关隔离
- **目标**：完成用户明确授权的main合并、推送与生产部署
- **操作**：189c788f已快进到main并推送；生产只读基线发现priority_daily运行但legacy auto_sync_enabled=false，取消尚未部署的34428808996流水线；补偿入口改为跟随WORKER_SCHEDULER_MODE，不启用旧同步
- **结果**：部署前正式轮次最新仍为8月31日、9月可见0，待首次分配7924；36项调度/运行时回归通过，Web production build通过。该修正替代前轮关于旧自动同步开关控制新补偿的表述；新模式跟随自身模式与worker生命周期。暂无生产写入或新版本启用。
- **涉及文件**：apps/worker/scheduler.py、tests/test_formal_allocation_runtime.py
