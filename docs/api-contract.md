# dy-data API 契约索引

> 当前运行契约以 `apps/api/dy_api/routes/`、Pydantic schema、依赖和测试为准。双费率、商品同步和双费用结算契约见 [Foundation API 设计](prd/foundation/foundation-api-dy-data.md)；T3.1 已实现结算筛选、榜单、单店分账、订单费用明细与同口径导出，生产迁移和端到端发布验收仍以 T4.1 结果为准。

## 1. 基础约定

- API 前缀：`/api/v1`。
- 会话：Web 请求携带会话 Cookie；业务接口默认需要登录。
- 授权：普通业务接口校验当前用户和门店范围；`/admin/*` 使用管理员或最高管理员依赖。
- 响应：业务成功响应沿用 `{ data, definitions?, meta }`，具体字段由对应 schema 定义。
- 错误：使用 HTTP 状态和结构化详情表达认证、授权、输入和服务错误；前端不得只判断一个自定义成功码。
- 时间、金额、ID 和状态口径以 schema、模型和数据库字段为准，变更时必须同步测试和前端类型。

## 2. 认证

前缀：`/api/v1/auth`

- `POST /login`
- `GET /me`
- `POST /logout`
- `POST /change-password`
- `POST /activation-status`
- `POST /initialize`
- `POST /reset-password`

账号激活和忘记密码统一使用 `external_account_id`（账户所属 ID）与 `poi_id`（所属账户关联 POI ID）进行同记录核验。`POST /activation-status` 返回受控状态 `invalid`、`ready` 或 `activated`；只有认证成功的子机构账号记录及其门店 POI 映射同时匹配时，才允许进入后续激活或重置流程。

`POST /initialize` 在双 ID 复核成功后设置账号名和密码；`POST /reset-password` 只允许已激活、状态正常的门店账号修改密码，并保留原账号名和门店范围。生产环境不得启用测试认证模式。

## 3. 经营与结算

前缀：`/api/v1`

- `GET /meta/filters`
- `GET /dashboard/store-ranking`
- `GET /commission-rules/summary`
- `GET /stores/{store_id}/monthly-settlement`
- `GET /order-fee-details`
- `GET /order-fee-details/export`
- `GET /dashboard/sales`
- `GET /order-details`
- `GET /order-details/export`

前三个结算页面入口使用 camelCase 业务字段、标准 `{ list, total, page, pageSize }` 分页和带 `requestId` 的响应元数据。榜单摘要基于完整过滤集合且名次不按页重置；单店和订单明细在服务端重验门店或账单范围；锁账查询只读冻结来源，预览只读当前指针。`/order-fee-details/export` 忽略分页、重新授权、返回带 UTF-8 BOM 的 CSV，空结果返回 409 `EXPORT_EMPTY`。

旧 `/order-details*` 继续提供通用订单查询和导出，不混入双费用、账单冻结或调整记录语义。所有筛选、汇总与明细必须使用一致的时间、门店、产品维度和权限范围；导出不是公开端点，同样需要认证与范围控制。

## 4. 线索运营

前缀：`/api/v1`

- `GET /clues/filters`
- `GET /clues/overview`
- `GET /clues/assignment-rounds`
- `GET /clues/assignment-rounds/export`
- `GET /clues/orders/{order_id}`
- `POST /clues/orders/{order_id}/follow-up`
- `DELETE /clues/follow-up-records/{follow_up_record_id}`
- `GET /clues/orders/{order_id}/phone`

详情、电话和跟进操作必须校验用户角色、订单归属和门店范围。

## 5. 反馈与任务

- `POST /api/v1/feedback`
- `GET /api/v1/jobs/recent`

任务状态用于运行观察，不向未授权用户暴露敏感错误和配置内容。

## 6. 后台管理

前缀：`/api/v1/admin`

- 账号：`/accounts*`、未激活门店、账号创建/更新和密码重置。
- 反馈：`/feedback*`。
- 商品与归属规则：`/sku-rules*`、`/non-commission-owner-accounts*`、`/product-type-visibility*`。
- 线索分配：`/clue-allocation/master-leads`、`decisions`、`eligible-leads`、`headquarters-pool`、`cycles*`、`audit-logs`、`store-scores*`、`rules*`、`rule-versions*`、`store-groups*`。
- 同步：`/sync`、`/sync/config`、`/sync/run`、`/sync/clue-center/rebuild`。

完整 method、参数和 schema 以 `admin.py` 及自动生成的 OpenAPI 为准；新增管理端点必须显式选择管理员依赖。

## 7. 变更规则

1. 先修改 schema、实现和测试，再同步本文分组索引与前端类型。
2. 破坏性字段或语义变化必须写入 Linear 验收标准并提供迁移方案。
3. 新接口至少覆盖正常、非法输入、无认证、无权限和门店越权场景。
4. 详细目标字段契约由 Foundation API 文档维护；本文保留当前运行入口与兼容约定。目标契约进入实现后，必须同步更新 route、Pydantic schema、前端类型、测试和本索引。
