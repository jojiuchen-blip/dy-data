# 商品范围与组织筛选契约增量

| 字段 | 内容 |
|---|---|
| ID | S4-FCR-001 |
| 来源 Task | clue-product-scope T0.1 |
| 分类 | GAP |
| 改动项 | 指标API及导出新增productScope；线索读/导出新增org_level和org_key；新增授权组织搜索接口 |
| 事实证据 | routes/dashboard.py、routes/clues.py及docs/api-contract.md |
| 影响 | Foundation API需回捞；无schema迁移 |
| 建议处理 | foundation-builder按API合同追加契约，不修改历史计算定义 |
| 状态 | 待回捞 |
