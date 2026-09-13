# DYDATA-96 Foundation 变更待评审

| 字段 | 内容 |
|---|---|
| ID | S4-FCR-001 |
| 来源 Task | DYDATA-96 T0.1 |
| 分类 | GAP |
| 改动项 | 同步管理API的资源保护与日批时效只读字段；quota_pause_count扩为两类调度让出计数 |
| 原因 | 需要区分可运行服务与实际同步阻塞，资源暂停不消耗业务失败预算 |
| 指向代码块 | apps/api/dy_api/schemas.py:532；apps/worker/task_control.py |
| 目标 foundation 文件:章节 | docs/prd/foundation/foundation-api-clue-center.md §4 宿主共享同步契约 |
| 严重度 | 建议 |
| 状态 | 待评审 |

运行契约已由 docs/api-contract.md 和 docs/runbook.md 记录；此记录不直接改写上游冻结财务及分配契约。
