# 账单确认、异议、发票与财务导入 Schema

> 增量来源: DYDATA-19 冻结规格（2026-08-20）
> 数据库: PostgreSQL；金额为整数分，时间为 `timestamptz`

### 1 `settlement_statement_confirmation` — 账单方向确认

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|---|---|---|---|---|---|
| id | bigint | NO | PK | identity | 主键 |
| confirmation_id | varchar(128) | NO | UK | — | 业务 ID |
| statement_id | varchar(128) | NO | UK* | — | 不可变账单版本 |
| fee_direction | smallint | NO | UK* | — | 1推广费，2管理费 |
| confirmation_status | smallint | NO | IDX | 1 | 1有效，2被新版本替代 |
| confirmed_amount_cent | bigint | NO | | 0 | 确认金额 |
| confirmed_by | varchar(128) | NO | IDX | — | 门店账号 |
| confirmed_at | timestamptz | NO | IDX | now() | 服务器确认时间 |
| gmt_create | timestamptz | NO | | now() | 创建时间 |
| gmt_modified | timestamptz | NO | | now() | 更新时间 |

唯一索引：`statement_id + fee_direction`。双方向互不阻断。

### 2 `settlement_dispute` — 账单异议

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|---|---|---|---|---|---|
| id | bigint | NO | PK | identity | 主键 |
| dispute_id | varchar(128) | NO | UK | — | 业务 ID |
| statement_id | varchar(128) | NO | IDX | — | 提交时账单版本 |
| store_id | varchar(128) | NO | IDX | — | 门店 ID |
| statement_month | char(7) | NO | IDX | — | 账期 |
| fee_direction | smallint | NO | IDX | — | 费用方向 |
| dispute_type | smallint | NO | IDX | — | 费率/遗漏/金额/其他 |
| status | smallint | NO | IDX | 1 | 待处理/审核中/待审批/成立/不成立/撤回 |
| disputed_amount_cent | bigint | NO | | 0 | 争议金额 |
| description | text | NO | | — | 说明 |
| contact_name | varchar(128) | NO | | — | 联系人 |
| contact_phone_ciphertext | text | NO | | — | 加密手机号 |
| evidence_json | jsonb | NO | | [] | 证明资料对象键和摘要 |
| resolution_note | text | YES | | NULL | 管理员处理说明 |
| result_statement_id | varchar(128) | YES | IDX | NULL | 新账单版本 |
| submitted_by | varchar(128) | NO | IDX | — | 提交人 |
| processed_by | varchar(128) | YES | IDX | NULL | 管理员 |
| submitted_at | timestamptz | NO | IDX | now() | 提交时间 |
| processed_at | timestamptz | YES | | NULL | 处理时间 |
| gmt_create | timestamptz | NO | | now() | 创建时间 |
| gmt_modified | timestamptz | NO | | now() | 更新时间 |

### 3 `settlement_dispute_order` — 异议订单范围

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|---|---|---|---|---|---|
| id | bigint | NO | PK | identity | 主键 |
| dispute_id | varchar(128) | NO | UK* | — | 异议 ID |
| order_id | varchar(128) | NO | UK* | — | 订单 ID |
| coupon_id | varchar(128) | YES | UK* | NULL | 券 ID |
| disputed_amount_cent | bigint | NO | | 0 | 本订单争议金额 |
| gmt_create | timestamptz | NO | | now() | 创建时间 |
| gmt_modified | timestamptz | NO | | now() | 更新时间 |

### 4 `invoice_record` — 发票登记版本

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|---|---|---|---|---|---|
| id | bigint | NO | PK | identity | 主键 |
| invoice_id | varchar(128) | NO | UK | — | 业务 ID |
| store_id | varchar(128) | NO | UK* | — | 门店 ID |
| statement_month | char(7) | NO | UK* | — | 单一账期 |
| statement_id | varchar(128) | NO | IDX | — | 确认账单版本 |
| fee_direction | smallint | NO | UK* | — | 1推广费，2管理费 |
| version_no | integer | NO | UK* | 1 | 版本号 |
| is_current | boolean | NO | IDX | true | 当前有效版本 |
| invoice_number | varchar(20) | NO | IDX | — | 发票号码 |
| invoice_date | date | NO | IDX | — | 开票日期 |
| invoice_amount_cent | bigint | NO | | — | 发票/扣款金额 |
| invoice_status | smallint | NO | IDX | 1 | 推广费四态；管理费固定已结算 |
| source_type | smallint | NO | IDX | — | 门店登记/管理员导入/更正 |
| import_batch_id | varchar(128) | YES | IDX | NULL | 导入批次 |
| registered_by | varchar(128) | NO | IDX | — | 操作者 |
| registered_at | timestamptz | NO | IDX | now() | 登记/导入时间 |
| gmt_create | timestamptz | NO | | now() | 创建时间 |
| gmt_modified | timestamptz | NO | | now() | 更新时间 |

部分唯一索引：`store_id + statement_month + fee_direction WHERE is_current`。更正新增版本，不删除历史。

### 5 `invoice_status_event` — 发票状态事件

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|---|---|---|---|---|---|
| id | bigint | NO | PK | identity | 主键 |
| event_id | varchar(128) | NO | UK | — | 事件 ID |
| invoice_id | varchar(128) | NO | IDX | — | 发票版本 |
| event_type | smallint | NO | IDX | — | 登记/状态导入/替换/更正 |
| from_status | smallint | YES | | NULL | 原状态 |
| to_status | smallint | NO | | — | 新状态 |
| operator_id | varchar(128) | NO | IDX | — | 操作者 |
| import_batch_id | varchar(128) | YES | IDX | NULL | 来源批次 |
| occurred_at | timestamptz | NO | IDX | now() | 事件时间 |
| gmt_create | timestamptz | NO | | now() | 创建时间 |
| gmt_modified | timestamptz | NO | | now() | 更新时间 |

### 6 `finance_import_batch` — 财务导入批次

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|---|---|---|---|---|---|
| id | bigint | NO | PK | identity | 主键 |
| batch_id | varchar(128) | NO | UK | — | 批次 ID |
| import_type | smallint | NO | IDX | — | 四类模板 |
| statement_month | char(7) | NO | IDX | — | 账期 |
| file_name | varchar(255) | NO | | — | 脱敏文件名 |
| file_sha256 | char(64) | NO | IDX | — | 文件摘要 |
| normalized_sha256 | char(64) | NO | IDX | — | 标准化摘要 |
| read_version | bigint | NO | | — | 读取版本 |
| current_version | bigint | NO | | — | 当前版本 |
| batch_status | smallint | NO | IDX | 1 | 校验/无变化/待确认/可提交/成功/失败/冲突/更正 |
| total_rows | integer | NO | | 0 | 总行数 |
| success_rows | integer | NO | | 0 | 成功行数 |
| error_rows | integer | NO | | 0 | 错误行数 |
| content_changed | boolean | NO | | false | 是否有差异 |
| submitted_by | varchar(128) | NO | IDX | — | 管理员 |
| committed_by | varchar(128) | YES | IDX | NULL | 提交人 |
| submitted_at | timestamptz | NO | IDX | now() | 上传时间 |
| committed_at | timestamptz | YES | | NULL | 提交时间 |
| gmt_create | timestamptz | NO | | now() | 创建时间 |
| gmt_modified | timestamptz | NO | | now() | 更新时间 |

### 7 `finance_import_row` — 财务导入逐行结果

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|---|---|---|---|---|---|
| id | bigint | NO | PK | identity | 主键 |
| batch_id | varchar(128) | NO | UK* | — | 批次 ID |
| row_number | integer | NO | UK* | — | 原文件行号 |
| business_key | varchar(512) | NO | IDX | — | 标准化业务键 |
| normalized_payload | jsonb | NO | | {} | 标准化字段 |
| row_status | smallint | NO | IDX | 1 | 通过/无变化/差异/错误/已写入 |
| validation_errors | jsonb | NO | | [] | 本行全部错误 |
| target_record_id | varchar(128) | YES | IDX | NULL | 成功目标 ID |
| gmt_create | timestamptz | NO | | now() | 创建时间 |
| gmt_modified | timestamptz | NO | | now() | 更新时间 |

### 8 `finance_operation_audit` — 财务操作审计

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|---|---|---|---|---|---|
| id | bigint | NO | PK | identity | 主键 |
| audit_id | varchar(128) | NO | UK | — | 审计 ID |
| operation_type | varchar(64) | NO | IDX | — | 操作类型 |
| target_type | varchar(64) | NO | IDX | — | 对象类型 |
| target_id | varchar(128) | NO | IDX | — | 对象 ID |
| operator_id | varchar(128) | NO | IDX | — | 操作者 |
| operator_role | smallint | NO | | — | 门店/管理员/最高管理员 |
| before_snapshot | jsonb | YES | | NULL | 变更前脱敏快照 |
| after_snapshot | jsonb | YES | | NULL | 变更后脱敏快照 |
| result_status | smallint | NO | IDX | — | 成功/失败/冲突 |
| request_id | varchar(128) | NO | IDX | — | 请求 ID |
| occurred_at | timestamptz | NO | IDX | now() | 操作时间 |
| gmt_create | timestamptz | NO | | now() | 创建时间 |
| gmt_modified | timestamptz | NO | | now() | 更新时间 |

审计不可修改或删除；可归档低成本存储但必须可查。导入流式解析全部错误，任一错误时正式业务表整批零写入；四类更正均新增版本。
