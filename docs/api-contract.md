# dy-data API 契约索引

> 当前运行契约以 `apps/api/dy_api/routes/`、Pydantic schema、依赖和测试为准。双费率、商品同步和双费用结算契约见 [Foundation API 设计](prd/foundation/foundation-api-dy-data.md)；T3.1 已实现结算筛选、榜单、单店分账、订单费用明细与同口径导出，生产迁移和端到端发布验收仍以 T4.1 结果为准。

## 1. 基础约定

### 打榜源证据归属字段（2026-09-11）

`GET /api/v1/admin/ranking-source-evidence` 的观察契约升级为
`ranking-source-observation-v2`，仍仅最高管理员可用，保留最长 7 日、最多
500 行、游标绑定查询上下文和只读约束。旧版本游标不可跨版本复用。

- `orders.owner_name_key`：原始订单归属账号名称的 SHA-256 匹配键，可空。
- `accounts.account_name_key`、`bindings.account_name_key`：账号昵称的同算法匹配键，可空。
- `bindings.source_account_name_key`：绑定表另一个账号名称 `account_name` 的同算法匹配键，可空；用于核验现有归属解析器的第二个精确名称，不改变归属规则。未包含此字段的旧导出不能视为完整名称归属核验。
- 名称按原文精确比较，不转换大小写、不模糊匹配；空值、空字符串和全空白返回 null。
  匹配键不是匿名化保证，也不证明门店归属；相同昵称跨门店、有失效绑定或冲突时不得自动归属。
- `bindings.source_bind_start_time`、`source_bind_end_time`：原始绑定起止值，未提供返回 null，
  保留 0；不擅自推断单位、开放区间或历史有效状态。
- 名称原文、完整 raw_payload、手机号和跟进正文不返回。接口不修改订单、绑定或结算逻辑。


### 财务已计算账单展示增量（DYDATA-87，2026-09-08 用户确认）

- `/admin/finance/invoices` 及导出以当前已生成账单为基础，推广与管理方向均保留尚未确认、尚未提交发票的行；不存在的发票字段返回空值，不创建确认或发票事实。
- 尚无 current 正式账单的门店账期，读取当前已发布月度投影补充展示；请求固定活动代次，遵守继承分区、删除标记与商品可见性，不回退到过时汇总。该行 `statementId`、发票字段为空，不自动锁账；有 current 正式账单时优先正式账单，避免重复统计。
- 没有活动发布代次时不展示裸旧汇总表中的未出账金额；已有正式账单仍正常展示，历史正式事实不受影响。
- 新增只读 `processingStatus`：`PENDING_STATEMENT`（待生成账单）、`PENDING_CONFIRMATION`（待确认）、`PENDING_SUBMISSION`（已确认待提交）、`SUBMITTED`（存在当前有效发票事实）。`status` 仍为原发票状态，不冒充办理状态。列表先展示待生成账单，再展示正式账单；两部分共用分页总数。
- `/admin/finance/summary` 与列表、导出保持相同账期、搜索和门店权限范围；未确认金额计入总额，不计入已确认、待开票或已开票金额。管理费“待开票”筛选仍要求真实确认。
- 发票历史、作废/替代、金额、确认、开票和厂家导入流程不变；自动展示并不自动执行业务动作。

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

DYDATA-88 修复后的运行约定：

- `overview` 以筛选范围内的唯一订单为分母；跟进、有效跟进和本店核销以该订单在范围内轮次的布尔汇总计数，不因多次分配重复累计。当前有效线索仍要求当前有效轮次。分配明细和门店轮次报表仍按轮次呈现。
- `store_scope_mode=all` 只授权管理员全店访问；`specified` 只授权列出的门店；`none`、空集合、未知或缺失范围拒绝操作。电话、跟进和 `can_operate_current_round` 使用同一范围判断，并复核当前正式轮次及主线索状态。
- 电话只接受完整中国手机号或合法格式化号码。密文先解密，掩码不作为明文。缓存必须匹配当前原始联系方式的来源指纹；没有来源、来源变化或解密失败时不返回旧明文。旧的无指纹缓存由当前源重新验证，不能直接视为可信。
- 列表电话按订单批量查询和解析；GET 不提交业务写事务。进程内解密缓存按数据库与来源隔离，上限 1024 项，成功 300 秒、失败 30 秒，不缓存授权结果。完整电话仍仅由授权电话端点或当前可操作轮次的导出提供。
- 同主线索的跟进、关闭和撤销在事务内锁后重新读取；关闭后的旧请求返回现有冲突响应，不重新打开历史轮次。真实模式的前端详情错误直接显示，不使用演示数据替代。

## 5. 反馈与任务

- `POST /api/v1/feedback`
- `GET /api/v1/jobs/recent`

任务状态用于运行观察，不向未授权用户暴露敏感错误和配置内容。

## 6. 后台管理

前缀：`/api/v1/admin`

- 账号：`/accounts*`、未激活门店、账号创建/更新和密码重置。
- 反馈：`/feedback*`。
- 商品与归属规则：`/sku-rules*`、`/non-commission-owner-accounts*`、`/product-type-visibility*`。
- 线索分配：`/clue-allocation/master-leads`、`decisions*`、`eligible-leads`、`headquarters-pool`、`cycles*`、`cycle-previews`、`trial-cycles`、`rebuild-cycles`、`audit-logs`、`store-scores*`、`rules*`、`rule-versions*`、`store-groups*`。
  - `POST /clue-allocation/cycle-previews` 生成 10 分钟有效的短时预览，并绑定线索状态版本、规则版本和目标范围。
  - `POST /clue-allocation/trial-cycles` 与 `POST /clue-allocation/rebuild-cycles` 仅供最高管理员显式确认后执行，必须携带 `Idempotency-Key`；同键同请求重放原结果，同键不同请求返回冲突。
  - `GET /clue-allocation/cycles/{cycle_id}` 返回批次摘要和分页逐线索执行项；`GET /clue-allocation/decisions/{decision_id}` 返回结构化候选与评分证据。
  - 候选、批次、决策、审计、规则、评分列表接受 `page/page_size`，返回 `rows` 与 `pagination`；前端保留服务端总数，选择只在当前页生效，忽略过期分页响应。
  - 页面权限按 `D05` 规则配置、`D06` 试运行、`D07` 分配记录、`D08` 总部池拆分；批次列表和详情允许 `D06` 或 `D07`。
  - 试运行证据与正式轮次隔离，不改变线索池位置、门店责任和经营指标；旧同步页不再提供直接线索物化入口。
- 同步：`/sync`、`/sync/config`、`/sync/run`。线索正式重建不再通过同步页的直接物化入口触发。

完整 method、参数和 schema 以 `admin.py` 及自动生成的 OpenAPI 为准；新增管理端点必须显式选择管理员依赖。

## 7. 变更规则

1. 先修改 schema、实现和测试，再同步本文分组索引与前端类型。
2. 破坏性字段或语义变化必须写入 Linear 验收标准并提供迁移方案。
3. 新接口至少覆盖正常、非法输入、无认证、无权限和门店越权场景。
4. 详细目标字段契约由 Foundation API 文档维护；本文保留当前运行入口与兼容约定。目标契约进入实现后，必须同步更新 route、Pydantic schema、前端类型、测试和本索引。

## 昨日优先调度状态（DYDATA-90）

`GET /api/v1/admin/sync` 在部署配置 `WORKER_SCHEDULER_MODE=priority_daily` 时，`worker_status.mode` 返回 `priority_daily`；`schedule.auto_sync_enabled` 和 `worker_status.auto_sync_enabled` 表示新模式已启用。`config.auto_sync_enabled` 仍保留旧滚动调度设置，不用于控制新模式。管理页将相关旧控件禁用并解释区别。

`next_scheduled_sync_at` 是下次上海02:00日历触发点，不是当前任务预计完成时间。`latest_successful_sync_at` 和日窗完成覆盖以 `priority-daily-v1`、`target=all` 的已成功发布range任务为准，分域collect成功不计作已发布。状态栏纳入parent/date/finalize任务。历史范围仍由已有配置管理，新模式固定按完整日推进。
