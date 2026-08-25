# 开发日志 — 2026-08-24

> 主题：补充更新 15（T5.7 G3 冻结回归）
> 操作人：jojiuchen-blip
> 关联计划：docs/plans/execution-plan.md

---

## 一、执行概要

| # | 任务 | 关联 | 状态 |
|---|------|------|------|
| 1 | 补充更新 15（T5.7 G3 冻结回归） | S4 / T5.7 | ✅ |

**本日关键结论**：G3 已完成并冻结，可进入最新主线干净集成；尚未完成全量、目标 PostgreSQL、CI、生产 smoke 和业务验收，不得宣称发布完成

---

## 二、操作详情

### 任务 1：补充更新 15（T5.7 G3 冻结回归）
- **目标**：完成历史账单与订单明细冻结快照、财务订单明细完整投影和发布异常归零门禁的最终闭合
- **操作**：修复并复核 0043 快照迁移、Vn+1 快照继承、财务订单明细列表与导出、导出审计、前端完整字段与筛选分页状态，以及部署脚本 unresolved exception 归零检查；对旧迁移测试的保护性错误信息做最小兼容更新
- **结果**：最终完整相关回归 152 passed, 170 warnings；Web production build 通过；Alembic 单头 20260824_0043；git diff --check 通过；独立七项复审 Critical 0、Important 0、Minor 0，Ready yes
- **涉及文件**：alembic/versions/20260824_0043_statement_store_snapshots.py、apps/api/dy_api/models.py、apps/api/dy_api/routes/dashboard.py、apps/worker/settlement.py、apps/web/src/pages/FinanceOrderDetailsPage.tsx、deploy/tencent/deploy.sh、tests/test_api_store_billing.py、tests/test_data_settlement.py、tests/test_alembic_migrations.py、tests/test_deploy_compose_config.py、tests/test_frontend_user_facing_contracts.py

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
| 新建/修改/删除 | `path/to/file` | 一句话说明 |

> 收口时由 AI 从各任务「涉及文件」聚合去重生成。操作类型：新建 / 修改 / 删除。

### Git 提交记录

| 时间 | Commit | 内容 |
|------|--------|------|

---

## 四、发现的问题 / 缺陷

无

---

## 五、复盘

### 做得好的
- （列举）

### 遇到的问题
- **现象**：
- **根因**：
- **经验**：> 可执行的一句话
- **🔧 是否提炼为规则**：✅ 建议写入 `project-rules.md` / ⬜ 仅记录

### 今日经验总结
1. 经验 1 → 🔧 建议加入 project-rules.md
2. 经验 2 → 仅记录

---

## 五·附、方法论沉淀（可选）

> 当天工作中如果有可复用的方法论、设计原则、或跨项目通用的经验，在此抽象记录。
> 普通开发日不需要填写此章节。

---

## 六、待跟进事项

- [ ] 形成可恢复 checkpoint 后，从最新 origin/main 建立干净集成分支，重建财务迁移链并执行全量发布门禁

---

## 七、2026-08-25 发布前验证记录

- **集成提交**：`bea1f70 test: align finance import conflict smoke contract`
- **CI 运行**：[32796993246](https://github.com/jojiuchen-blip/dy-data/actions/runs/32796993246)
- **治理门禁**：suite lock、全局文件校验、阶段路由校验均通过；0 errors、0 warnings。
- **数据库发布门禁**：真实 PostgreSQL 下两路并发 `alembic upgrade head` 通过；迁移头为 `20260824_0043`。迁移锁改为 `pg_try_advisory_lock` 轮询，避免阻塞等待期间与并发 DDL 形成死锁。
- **全量测试**：`1369 passed, 2 skipped`；前端构建通过；API、Worker、Browser、Web 四个 Docker 镜像构建通过。
- **财务导入冲突契约**：409 冲突返回安全的用户提示，清除旧预览和文件，禁止沿用过期预览重复提交；对应视觉冒烟测试已同步并通过。
- **当前状态**：代码与 CI 门禁已完成；生产合并、部署、生产冒烟及 Linear 回填仍待本轮发布流程完成，不能提前宣称生产已完成。

## 八、2026-08-25 发布审阅修复

- **独立审阅结论**：发现 2 项 Important，已暂停生产发布。
- **迁移回滚保护**：0028、0031、0034、0038 的 `downgrade()` 现在在发现财务事实后拒绝有损删除；空库仍可逆，并增加四类有数据拒绝回滚测试。
- **Railway 发布门禁**：启用 Railway 发布时，token、API/Worker/Browser/Web 服务 ID 和 Web smoke URL 均为必填；缺失配置直接失败，不再产生“验证通过但未完整部署”的绿色结果。
- **定向验证**：迁移回滚保护 4 项与部署契约 1 项通过；部署/Agent 契约回归 `19 passed`。全量 CI 待修复提交完成后重新执行。
- **真实 PostgreSQL 历史数据门禁**：新增有数据的 `20260824_0042 → 20260824_0043` fixture，验证可确定回填门店快照、无法匹配记录进入 `UNRESOLVED` 和异常表。
- **真实 PostgreSQL 并发门禁**：新增两个同账期财务导入批次并发提交的 API 路径验证，要求版本严格分配为 `1、2`，并保留两条操作审计。
- **目标库发布保护**：Railway 发布前新增目标库备份、现有 Alembic lineage 校验、显式迁移和未解决快照异常检查；备份作为 Actions artifact 留存。
- **迁移边界**：API Docker 镜像不再在进程启动时隐式执行迁移，迁移由 Compose `migrate` 服务和目标库发布门禁显式负责。
