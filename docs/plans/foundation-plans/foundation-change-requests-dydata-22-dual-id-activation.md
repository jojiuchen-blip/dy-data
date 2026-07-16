# DYDATA-22 Foundation Change Requests

| ID | 来源 Task | 分类 | 改动项 | 原因 | 指向代码块 | 目标 foundation 文件:章节 | 严重度 | 状态 |
|---|---|---|---|---|---|---|---|---|
| S4-FCR-001 | T1.2 双 ID 同记录后端核验 | GAP | 补充账号激活状态、最终激活和忘记密码的双 ID API 契约 | 当前仓库没有 `docs/prd/foundation/` 接口文档，但实现已新增 `/auth/activation-status` 并修改初始化、重置请求模型 | `apps/api/dy_api/routes/auth.py:171`、`apps/api/dy_api/schemas.py:42` | `docs/prd/foundation/foundation-api-dy-data.md` §账号认证（待创建） | 建议 | 待评审 |
