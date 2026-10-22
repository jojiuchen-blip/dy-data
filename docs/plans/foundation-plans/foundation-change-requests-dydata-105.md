# DYDATA-105 Foundation 契约回捞请求

| 字段 | 内容 |
|---|---|
| ID | S4-FCR-001 |
| 来源 Task | DYDATA-105 T0.1 权限、导出与批量筛选集成 |
| 分类 | DRIFT |
| 改动项 | 统一 admin 角色；显式账号/全局管理能力；范围内账号管理与禁删；0064 审计和会话失效迁移 |
| 原因 | 用户确认管理员可新增、变更但不可删除账号；原最高管理员/管理员分级及页面覆盖不再准确 |
| 指向代码块 | `apps/api/dy_api/auth.py:69`；`apps/api/dy_api/account_permissions.py:23`；`alembic/versions/20261022_0064_unify_administrators.py:19` |
| 目标 foundation 文件:章节 | `docs/prd/foundation/foundation-api-dy-data.md` 认证与授权；`docs/prd/foundation/foundation-schema-dy-data.md` 账号权限与迁移 |
| 严重度 | 建议 |
| 状态 | 待评审 |

| 字段 | 内容 |
|---|---|
| ID | S4-FCR-002 |
| 来源 Task | DYDATA-105 T0.1 权限、导出与批量筛选集成 |
| 分类 | GAP |
| 改动项 | 只读 POST 线索列表/导出、账户及 POI 批解析、显式空选择语义；有界导出元数据 |
| 原因 | 批量 1000 ID 不适合 URL；内部范围数组导致真实 Nginx 502，响应头不能承载完整查询授权 |
| 指向代码块 | `apps/api/dy_api/clue_store_filters.py:22`；`apps/api/dy_api/export_metadata.py:15`；`tests/test_dydata105_export_nginx.py:97` |
| 目标 foundation 文件:章节 | `docs/prd/foundation/foundation-api-clue-center/lead-query-and-contact.md` 公共查询、筛选与导出 |
| 严重度 | 建议 |
| 状态 | 待评审 |

当前运行合同与兼容行为见 [API 契约索引](../../api-contract.md)。此文件记录待回捞事实，不代替 Foundation 的正式修订或生产验收。
