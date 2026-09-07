# 开发日志 — 2026-09-07

> 主题：DYDATA-87 持久重算并发修复验证
> 操作人：jojiuchen-blip
> 关联计划：docs/plans/delivery-plans/sub-delivery-plan-dy-data-T5.7-system-uat.md

---

## 一、执行概要

| # | 任务 | 关联 | 状态 |
|---|------|------|------|
| 1 | DYDATA-87 持久重算并发修复验证 | T5.7 / DYDATA-87 | 进行中，生产验收待完成 |
| 2 | DYDATA-87 发布前验证收口 | 补充更新 | ✅ |

**本日关键结论**：生产遗留重算仍阻塞；本地并发修复通过真实数据库验证，部署门禁尚未完成；Foundation漂移继续由S4-FCR-011承接。

---

## 二、操作详情

### 任务 1：DYDATA-87 持久重算并发修复验证
- **目标**：恢复规则发布后的重算与门店榜单、单店分账闭环；不改变订单归属分佣口径
- **操作**：恢复生产登录核验；补充真实 PostgreSQL 并发故障注入；修复心跳元数据覆盖、锁等待后过期提交、发布事实对账与旧重试合并；刷新治理索引并完成独立审查
- **结果**：真实 PostgreSQL 9 passed；元数据、续租、发布、完成和失败过期场景修复前均复现失败；SQLite 发布对账与旧重试合并4 passed；Web build及套包122项通过。完整pytest和受影响模块回归、第二次独立复审仍进行中。尚未部署，不宣称榜单恢复。
- **涉及文件**：apps/worker/settlement_rebuild.py、apps/worker/projection_publish.py、apps/worker/queued_jobs.py、tests/test_settlement_rebuild_postgres.py、tests/test_worker_collection_pipeline.py、.github/workflows/tencent-lighthouse-deploy.yml

<!-- 复杂决策型任务可展开分析：
### 任务 N：标题（决策类）
- **背景问题**：为什么要做这个决策
- **方案对比**：（表格或列表）
- **最终决策**：选了什么 + 为什么
- **涉及文件**：列表
-->

---

## 三、变更总览

### 文件变更清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `apps/worker/settlement_rebuild.py` | 持久认领、续租、提交围栏、发布对账及重试合并 |
| 修改 | `apps/worker/projection_publish.py` | 发布锁等待后重新校验数据库租约 |
| 修改 | `apps/worker/queued_jobs.py` | 消费持久任务和恢复失联任务 |
| 新建 | `tests/test_settlement_rebuild_postgres.py` | 真实 PostgreSQL 并发故障注入 |
| 修改 | `tests/test_worker_collection_pipeline.py` | 发布、重试和提交边界回归 |
| 修改 | `.github/workflows/tencent-lighthouse-deploy.yml` | 发布前纳入真实数据库并发门禁 |

> 收口时由 AI 从各任务「涉及文件」聚合去重生成。操作类型：新建 / 修改 / 删除。

### Git 提交记录

| 时间 | Commit | 内容 |
|------|--------|------|

---

## 四、发现的问题 / 缺陷

发现并已在本地修复：心跳覆盖发布标记、锁等待后使用过期租约、旧执行者覆盖新认领、活动指针前移导致误重算、旧重试未合并，以及旧代际清理在租约校验后等待写锁。生产重算恢复尚未验证。

---

## 五、复盘

### 做得好的
- 用真实 PostgreSQL 两会话和数据库锁状态复现竞态，再用相同测试验证修复。

### 遇到的问题
- **现象**：本地第一次受影响组合回归中两项调度测试失败；超短租约测试也出现一次调度敏感失败。
- **根因**：调度测试继承了本机商品同步配置，额外创建商品任务；0.6 秒租约用例单独复测通过，但重负载组合中失去租约，需要使用足够调度余量并直接断言持久续租事实。
- **经验**：清理测试环境中的外部业务配置；时序测试使用数据库锁条件和续租事实，不依赖亚秒级执行速度。
- **🔧 是否提炼为规则**：仅记录，沿用已有测试和数据正确性门禁。

### 今日经验总结
1. 全量重算的执行权必须持久化，成功状态应以已发布事实为依据。→ 仅记录，契约由 S4-FCR-011 承接。
2. 代码审查通过、自动化测试通过与生产业务验收是独立结论。→ 仅记录，沿用现有规则。

---

## 五·附、方法论沉淀（可选）

> 当天工作中如果有可复用的方法论、设计原则、或跨项目通用的经验，在此抽象记录。
> 普通开发日不需要填写此章节。

---

## 六、待跟进事项

- [ ] 完成回归与独立复审后提交发布；上线观察失联任务恢复及投影发布，再核对2026-08榜单和单店样本。
---

## 补充更新 1（10:17 · 窗口 1）

### 任务 2：DYDATA-87 发布前验证收口
- **目标**：记录修复的真实数据库、模块回归和审查证据，进入受控发布
- **操作**：修复旧代际清理锁顺序与有界等待；清理本机业务环境配置后重跑；使用跨两个续租周期的数据库事实断言；完成独立复审
- **结果**：受影响6文件225 passed；最终真实PostgreSQL10 passed；补充提交边界7 passed；PostgreSQL迁移与事务锁release gate通过，head=20260903_0050；独立复审Critical/Important/Minor均0。Web build及治理122项已通过。完整本地pytest仍运行，生产未部署。
- **涉及文件**：apps/worker/settlement_rebuild.py、tests/test_settlement_rebuild_postgres.py、docs/plans/execution-plan.md
