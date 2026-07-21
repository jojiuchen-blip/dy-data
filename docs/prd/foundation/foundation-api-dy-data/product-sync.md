# 商品同步 API

> 所属索引: [foundation-api-dy-data.md](../foundation-api-dy-data.md)
> 消费页面: 商品同步后台、SKU 规则后台的同步状态与历史区
> 边界: 内部管理接口契约可先确认；抖音外部接口待脱敏响应样例后补齐

## 0 共享响应对象

### 0.1 `ProductSyncRunItem`

| 字段 | 类型 | 说明 | 来源表.列/系统来源 |
|------|------|------|-------------------|
| `syncRunId` | string | 同步运行 ID | `job_runs.job_id`，同时关联 `sku_product_sync_history.sync_run_id` |
| `mode` | string | `INCREMENTAL/FULL` | `job_runs.metadata_json.mode` |
| `status` | string | `QUEUED/RUNNING/SUCCESS/FAILED/PARTIAL` | `job_runs.status` |
| `startedAt` | datetime/null | 启动时间 | `job_runs.started_at` |
| `finishedAt` | datetime/null | 结束时间 | `job_runs.finished_at` |
| `observedCount` | integer | 上游观察到的 SKU 数 | `job_runs.metadata_json.observed_count` |
| `insertedCount` | integer | 新增当前快照数 | `job_runs.metadata_json.inserted_count` |
| `updatedCount` | integer | 更新当前快照数 | `job_runs.metadata_json.updated_count` |
| `unchangedCount` | integer | 无变化数 | `job_runs.metadata_json.unchanged_count` |
| `failedCount` | integer | 校验/写入失败数 | `job_runs.failed_count` |
| `latestSuccessfulSyncedAt` | datetime/null | 本次完整成功的最近同步时间 | `dim_sku_product_rules.last_synced_at` 聚合 |
| `nextCursorMasked` | string/null | 脱敏后的下一游标摘要 | `job_runs.metadata_json.next_cursor_masked` |
| `errorCode` | string/null | 稳定错误码 | `job_runs.metadata_json.error_code` |
| `errorMessage` | string/null | 脱敏可操作错误 | `job_runs.error_message` |

### 0.2 `SkuSyncHistoryItem`

| 字段 | 类型 | 说明 | 来源表.列 |
|------|------|------|----------|
| `snapshotId` | string | 快照业务 ID | `sku_product_sync_history.snapshot_id` |
| `syncRunId` | string | 同步运行 ID | `.sync_run_id` |
| `skuId` | string | SKU ID | `.sku_id` |
| `productId` | string/null | 商品 ID | `.product_id` |
| `spuId` | string/null | SPU ID | `.spu_id` |
| `skuName` | string/null | SKU 名称快照 | `.sku_name` |
| `productName` | string/null | 商品名称快照 | `.product_name` |
| `creatorAccountId` | string/null | 创建者账号 ID | `.creator_account_id` |
| `creatorAccountName` | string/null | 创建者名称 | `.creator_account_name` |
| `ownerAccountId` | string/null | 归属账号 ID | `.owner_account_id` |
| `ownerAccountName` | string/null | 归属账号名称 | `.owner_account_name` |
| `productStatusRaw` | string/null | 平台原始状态 | `.product_status_raw` |
| `productStatus` | string/null | `ACTIVE/INACTIVE/DELETED/UNKNOWN` | `.product_status_normalized` |
| `payloadSha256` | string | 脱敏规范化载荷摘要 | `.payload_sha256` |
| `observedAt` | datetime | 平台观测时间 | `.observed_at` |

## 1 `GET /api/v1/admin/product-sync-runs` — 商品同步运行列表

> 数据源表: `sku_product_sync_history`、既有任务表

**请求参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `page` / `pageSize` | integer | 否 | 标准分页 |
| `status` | string | 否 | 运行状态 |
| `mode` | string | 否 | `INCREMENTAL/FULL` |
| `startedFrom` / `startedTo` | datetime | 否 | 启动时间范围 |

**响应 `data`**：分页对象，`list` 项为 `ProductSyncRunItem`。

**约束**：普通管理员只看到脱敏错误摘要，不返回外部请求头、Cookie、凭据、完整响应或原始游标。

## 2 `POST /api/v1/admin/product-sync-runs` — 触发商品同步

> 数据源表: 成功后写 `sku_product_sync_history` 并更新 `dim_sku_product_rules` 平台字段
> 请求头: 必须提供 `Idempotency-Key`

**请求 JSON**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `mode` | string | 是 | `INCREMENTAL` 或 `FULL` |
| `reason` | string | 是 | 1～512 字符的触发原因 |

**响应 `data`**：`{ syncRunId, mode, status: "QUEUED" }`。

**状态与并发**：

- 同一商品同步目标同时只允许一个 `RUNNING` 任务；重复触发返回 409 或复用同一幂等结果。幂等键摘要与请求摘要写入 `job_runs.metadata_json`，不得记录原始请求头。
- `INCREMENTAL` 从最近一次完整成功游标继续；游标仅在对应页面数据与历史快照事务提交后推进。
- `FULL` 重新遍历商品范围，但不得删除未在单次响应中出现的当前 SKU；删除/下架必须来自稳定平台状态或完整对账结论。
- 触发成功只代表入队，不代表数据已成功同步；页面轮询 #3。

**写入边界**：

- 只更新 `dim_sku_product_rules` 的平台同步字段、`syncRunId` 和 `lastSyncedAt`。
- 严禁覆盖 `productScope`、`productType`、`isServiceProduct`、费率及其人工审计字段。
- 单条非法响应进入数据质量问题；若批次不能保证完整一致，任务为 `FAILED/PARTIAL`，不得用启动时间更新最近成功同步时间。

## 3 `GET /api/v1/admin/product-sync-runs/{syncRunId}` — 商品同步运行详情

> 数据源表: `sku_product_sync_history`、既有任务表

**响应 `data`**：

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `run` | `ProductSyncRunItem` | 运行摘要 | 共享对象 |
| `phaseCounts` | object | 拉取、校验、写快照、更新当前值各阶段计数 | `job_runs.metadata_json.phase_counts` |
| `affectedSkuSample` | string[] | 最多 20 个脱敏/授权内 SKU ID | `sku_product_sync_history.sku_id` |
| `dataQualityIssueCount` | integer | 本次产生的数据质量问题数 | `data_quality_issues.source_run_id` 聚合 |
| `retryable` | boolean | 是否允许安全重试 | `job_runs.metadata_json.retryable` |

不存在返回 404。运行中轮询建议不短于 3 秒；响应不得返回完整外部载荷。

## 4 `GET /api/v1/admin/sku-products/{skuId}/sync-history` — SKU 同步历史

> 数据源表: `sku_product_sync_history`

**请求参数**：`page`、`pageSize`、`observedFrom`、`observedTo`。

**响应 `data`**：分页对象，`list` 项为 `SkuSyncHistoryItem`，按 `observedAt` 降序。

**约束**：`raw_payload` 不直接作为 API 字段返回；如排查必须展示差异，应由服务端生成白名单字段差异，禁止透传未知外部内容。

## 5 抖音商品在线 API — 外部引用（待样例）

- **对接方**：抖音来客商品在线 API。
- **文档地址**：当前未提供；不得写入猜测链接。
- **调用场景**：#2 触发的 worker 按页或按游标同步商品、SKU、SPU、账号归属和状态。
- **是否需改动**：未知；本项目仅通过适配器消费，不要求外部系统为本项目修改。
- **待确认请求信息**：正式 URL、鉴权方式、分页/增量游标、限流和重试语义。
- **待映射响应字段**：商品 ID、商品名称、SKU ID、SKU 名称、SPU ID、创建者账号 ID/名称、归属账号 ID/名称、商品状态、平台更新时间、下一游标。
- **冻结前证据**：至少一份脱敏成功响应、一份空页/末页响应、一份错误响应，以及直播/短视频相关渠道枚举说明。

外部映射未冻结时，内部 API 仍可确认，但 #2 的真实生产验收必须保持“依赖未关闭”，不能把模拟响应当作完成证据。
