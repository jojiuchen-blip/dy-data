# 统一看板发布 Foundation 待改请求

| 字段 | 内容 |
|---|---|
| ID | S4-FCR-001 |
| 来源 Task | unified-dashboard-publications / T0.1 统一静态发布实现 |
| 分类 | GAP |
| 改动项 | 补充五模块不可变分析发布、版本固定/过期、统一筛选接口及真实时间字段 |
| 原因 | 分析读取已经从请求期来源计算改为后台发布；现有 API/Schema 文档没有此协议 |
| 指向代码块 | `apps/api/dy_api/routes/publications.py:15`；`apps/api/dy_api/dashboard_publications/schema.py:10`；`tests/test_api_dashboard_publications.py:76` |
| 目标 foundation 文件:章节 | `docs/prd/foundation/foundation-api-dy-data.md` 看板与筛选；`docs/prd/foundation/foundation-schema-dy-data.md` 分析发布侧表 |
| 严重度 | 建议 |
| 状态 | 待评审 |
