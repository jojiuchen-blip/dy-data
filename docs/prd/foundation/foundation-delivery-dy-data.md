# Foundation 交付清单 - dy-data（抖音经营引擎）

> 生成时间: 2026-08-20
> Skill: foundation-builder
> 模式: 增量更新
> 范围: DYDATA-19 月度账单确认、异议、发票登记、财务导入、查询与审计；最新规则覆盖旧的只读开票假设

## 上游依赖

| 上游 Skill | 产物文件 |
|---|---|
| brd-writer | docs/brd/BRD-dy-data-20260716-1255.md |
| page-designer | src/frontend/page-preview/page-delivery-dy-data.md |
| page-explainer | src/frontend/page-preview/explainer-flow-dy-data.md<br>src/frontend/page-preview/explainer-b-interaction-dy-data.md<br>src/frontend/page-preview/explainer-delivery-dy-data.md |
| 冻结规格 | docs/superpowers/specs/2026-08-20-dydata-19-settlement-finance-design.md |

## 交付产物

| 产物 | 文件路径 | 行数 | 拆分子文件 |
|---|---|---:|---|
| 术语表 | docs/prd/foundation/foundation-glossary-dy-data.md | 167 | — |
| 数据库 Schema | docs/prd/foundation/foundation-schema-dy-data.md | 136 | docs/prd/foundation/foundation-schema-dy-data/billing-invoice.md<br>docs/prd/foundation/foundation-schema-dy-data/existing-read-dependencies.md<br>docs/prd/foundation/foundation-schema-dy-data/product-rule-source.md<br>docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md |
| API 接口设计 | docs/prd/foundation/foundation-api-dy-data.md | 256 | docs/prd/foundation/foundation-api-dy-data/billing-invoice.md<br>docs/prd/foundation/foundation-api-dy-data/common-contract.md<br>docs/prd/foundation/foundation-api-dy-data/product-sync.md<br>docs/prd/foundation/foundation-api-dy-data/settlement-reporting.md<br>docs/prd/foundation/foundation-api-dy-data/sku-fee-admin.md |

## 产物摘要

| 指标 | 数值 |
|---|---|
| 数据表总数 | 25 张目标设计表 + 5 张结构不变既有依赖表 |
| API 接口数 | 42 |
| DYDATA-19 新增接口 | 20 |
| DYDATA-19 新增表 | 8（并变更 `settlement_statement` 版本模型） |
| DYDATA-19 冻结交互语义 | 4 |
| 正式累计起点 | `2026-08` |

## 一致性自查结果

- 检查时间: 2026-08-20
- DYDATA-19 页面可写操作覆盖率: 5/5 (100%)
- 新增 API ↔ Schema 覆盖率: 20/20 (100%)
- 新增表消费覆盖率: 8/8 (100%)
- 交互语义 → API/Schema 覆盖率: 4/4 (100%)
- 术语一致性: 全部通过
- 孤立项: 无
- 文件拆分约束: 主文件及全部子文件均少于 400 行

## 已确认的 DYDATA-19 关键边界

- 开票与厂端审核在系统外完成；系统不创建开票申请单、不执行开票、不创建审核任务。
- 门店账号按费用方向确认账单、提交异议和登记推广费发票；财务人员使用管理员角色导入结果，管理员与最高管理员在本模块权限一致。
- 推广费状态固定为“待开票 / 提交成功，待厂端审核 / 审核通过，已结算 / 审核不通过，请重新上传”；管理服务费不套用此审核状态链。
- 账单、发票和四类导入均采用不可变版本；更正覆盖当前指针，不删除历史。四类导入任一错误行时正式业务表整批零写入。
- 门店只按 `store_id` 精确匹配；禁止 SAP 编码、名称、金额或月份模糊匹配。一个门店、一个账期仅一张当前有效发票，不跨账期、不拆票。
- 单月与正式累计同时可查；正式累计从 `2026-08` 开始，确认金额只显示单月。历史审计可归档低成本存储，但必须可查询。

## 外部依赖与非阻断项

| 项目 | 当前处理 | 影响 |
|---|---|---|
| 企业微信发送 | 本期未开发，不设计接口 | 不阻断发票登记与状态导入 |
| 外部真实开票/厂端审核 | 系统外业务，系统仅登记和导入结果 | 不纳入系统验收 |
| DYDATA-22 身份治理 FCR | 与 DYDATA-19 无关，保持待评审且未消费 | 不影响本次财务底座设计 |
| DYDATA-32 页面权限登记 | 页面设计缺口保持 out_of_scope | 正式开放新生产路由前需独立完成 |

## 下游可消费信息

| 下游 Skill | 应读取 | 用途 |
|---|---|---|
| planner / prd-writer | 本清单、glossary、schema、api、冻结规格和全部拆分子文件 | 生成实施计划、验收映射、迁移顺序和接口任务 |

## 下游进入条件

- 任务拆分必须以本清单声明的相对路径为准，不从历史评论重新拼接需求。
- API 和 Schema 是目标契约，不表示运行代码、迁移或生产适配已经实现。
- 开发顺序必须先完成迁移与领域服务，再接 API 和页面；所有写操作必须包含权限、幂等、版本冲突和审计测试。
