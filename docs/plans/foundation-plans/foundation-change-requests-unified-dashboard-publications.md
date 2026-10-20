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

## S4-FCR-002：操作表单的实时管理费记录

- 来源 Task：unified-dashboard-publications / T0.1；分类：GAP。
- 新增 GET `/api/v1/admin/finance/management-invoices/{store_id}/{statement_month}/current`，沿用更正成功响应形状及 FIN02/管理员/当前门店权限。
- 原因：静态分析行不能作为更正表单的当前版本；打开表单和冲突恢复需要实时记录，提交继续保持现有并发控制。
- 目标：财务 API foundation 的管理费更正章节；严重度：建议；状态：待评审。
- 证据：`get_current_management_invoice`、`tests/test_api_management_invoice_current.py`。

## S4-FCR-003：静态发布与账期完整性分离

- 来源 Task：DYDATA-104 / T3.1；分类：GAP。
- 用户 2026-10-20 要求优先发布，难以恢复的历史任务不继续纠结；据此暂缓历史恢复，保留未完成业务验收。
- 在静态发布 stats 中冻结各月日水位状态，并纳入财务/结算来源指纹。财务 MONTH 检查所选月，累计及包含累计卡片的结算响应检查正式起点 2026-08 至选中月的前缀；缺失状态失败关闭。返回 503 `PUBLICATION_PERIOD_NOT_READY`，不得伪造零值或触发版本失效重试。
- 查询和导出只读发布侧表；筛选项保留，允许切换账期。新账单生成门禁及历史确认/开票保护保持。
- 目标：财务/结算 API foundation 异常与发布状态章节；状态：用户方向已确认，S4 实现验证中，Foundation 正文待同步。
- 此变更不核准退款单位、九月金额或历史覆盖关系，不改变五模块首版及来源并发保护。
