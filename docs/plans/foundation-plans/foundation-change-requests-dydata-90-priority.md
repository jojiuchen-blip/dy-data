# DYDATA-90 foundation 回捞

| 字段 | 内容 |
|---|---|
| ID | S4-FCR-001 |
| 来源 Task | T0.2 启用昨日优先调度 |
| 分类 | GAP |
| 改动项 | 调度用途、预算暂停计数、分接口共享计数及历史保护预留 |
| 原因 | 日配额暂停是正常调度状态；与三次真实失败上限混算会导致历史永久停滞。总领取次数和租约epoch仍须单调递增并保留审计序列。 |
| 指向代码块 | apps/worker/priority_budget.py:20；apps/worker/task_control.py；apps/api/dy_api/models.py:JobRun |
| 目标 foundation 文件:章节 | docs/prd/foundation/foundation-schema-dy-data.md 调度控制表；docs/api-contract.md 管理同步状态 |
| 严重度 | 建议 |
| 状态 | 待评审 |

0053以增量迁移增加预算暂停计数；默认0保持旧任务语义。正常故障仍最多三次。模式由部署配置显式选择，旧自动开关不控制新模式；管理API沿用字段并显示实际模式与日历调度。具体实现和上线证据以T0.2开发日志为准。
