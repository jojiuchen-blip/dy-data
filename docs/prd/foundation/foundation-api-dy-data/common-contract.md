# 公共 API 契约

> 所属索引: [foundation-api-dy-data.md](../foundation-api-dy-data.md)
> 适用范围: 本轮全部 22 个接口

## 1 路径与方法

- 统一前缀：`/api/v1`；管理端资源统一位于 `/api/v1/admin`。
- 路径全小写，多词使用连字符，集合资源使用复数。
- GET 只查询；POST 用于创建不可变版本或触发任务；PUT 只用于允许整体替换的可编辑人工字段。
- 内部自增 `id` 不出现在 URL。路径参数使用 `skuId`、`ruleVersion`、`batchId`、`syncRunId` 等业务标识。
- 本轮不使用 PATCH；不可变财务结果、调整、锁账账单均不提供 DELETE。

## 2 成功响应包络

宿主项目的当前包络优先于通用套件示例：

```json
{
  "data": {},
  "definitions": [],
  "meta": {
    "generatedAt": "2026-07-20T11:20:00+08:00",
    "source": "postgres",
    "requestId": "req_xxx"
  }
}
```

| 字段 | 类型 | 必返 | 说明 |
|------|------|:---:|------|
| `data` | object/array/null | 是 | 业务数据；删除或无实体结果时可为 `null` |
| `definitions` | array | 否 | 页面指标解释；只有确有定义消费的接口返回 |
| `meta.generatedAt` | datetime | 是 | 本次响应生成时间，不代表数据同步成功时间 |
| `meta.source` | string | 是 | `postgres`、`cache` 等受控来源，不返回连接信息 |
| `meta.requestId` | string | 是 | 用于错误排查和审计串联 |

`code/msg` 不属于宿主成功响应；前端以 HTTP 状态判断请求结果。

## 3 字段、金额与时间

| 类别 | 契约 |
|------|------|
| JSON 字段 | `camelCase`；数据库 `snake_case` 由后端映射 |
| 枚举 | `UPPER_SNAKE_CASE`，未知外部枚举统一映射为 `UNKNOWN` |
| 金额 | JSON integer，单位分，字段以 `Cent` 结尾；允许调整字段为负数 |
| 费率 | JSON string，六位小数，如 `"0.080000"`，范围 `0`～`1` |
| 月份 | `YYYY-MM`，如 `2026-08` |
| 日期 | `YYYY-MM-DD`，按 `Asia/Shanghai` 业务日解释 |
| 时间 | ISO 8601 且带时区；前端不得把无时区字符串当本地时间猜测 |
| 业务 ID | string；保留平台原值，不转 number，不丢失前导零 |
| 空列表 | `[]` |
| 暂无对象值 | 字段保留并返回 `null` |

## 4 分页

请求参数：

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|:---:|:---:|------|
| `page` | integer | 否 | 1 | 从 1 开始 |
| `pageSize` | integer | 否 | 20 | 通常 1～50；接口另有上限时在接口详情说明 |

响应 `data`：

```json
{
  "list": [],
  "total": 0,
  "page": 1,
  "pageSize": 20
}
```

旧运行接口的 `{ rows, pagination: { page_size } }` 不作为新接口模板；实施时前后端同步切换。

## 5 错误、权限与幂等

### 5.1 结构化错误

```json
{
  "detail": {
    "code": "SKU_FEE_RULE_DATE_CONFLICT",
    "message": "该 SKU 在所选生效日已存在规则",
    "errors": [
      {
        "rowNumber": 8,
        "field": "effectiveDate",
        "reason": "SKU 123 在 2026-08-15 已存在规则"
      }
    ],
    "requestId": "req_xxx"
  }
}
```

| HTTP | 稳定错误码示例 | 场景 |
|:---:|---------------|------|
| 400 | `INVALID_REQUEST` | 请求结构无法解析 |
| 401 | `AUTH_REQUIRED` | 未登录或会话失效 |
| 403 | `DATA_SCOPE_FORBIDDEN` | 角色或门店范围不允许 |
| 404 | `RESOURCE_NOT_FOUND` | 业务 ID 不存在 |
| 409 | `SKU_FEE_RULE_DATE_CONFLICT` | 同 SKU + 生效日冲突 |
| 409 | `IMPORT_BATCH_STATE_CONFLICT` | 导入批次状态不允许提交 |
| 409 | `STATEMENT_LOCKED` | 试图改变已锁账结果 |
| 422 | `VALIDATION_FAILED` | 字段、枚举、日期或批量行校验失败 |
| 429 | `SYNC_RATE_LIMITED` | 同步任务触发过于频繁 |
| 500 | `INTERNAL_ERROR` | 未分类服务异常；响应不得泄露凭据或 SQL |
| 502 | `DOUYIN_UPSTREAM_FAILED` | 抖音上游不可用或响应非法 |

### 5.2 权限

- `/admin/*` 使用管理员依赖；发布结算范围、提交费率导入等高风险动作应使用项目最终权限矩阵中的更严格角色。
- 门店月度分账和订单费用明细必须在服务端校验请求门店与当前用户数据范围。
- 全国门店榜单前 20 名是明确 Web 业务例外；它不授权查看该门店的月度账单或订单明细。
- 导出沿用与查询完全相同的鉴权和筛选，不得先查全量再由前端过滤。
- CLI / Agent 后续即使复用 GET 契约，也必须经过独立只读通道白名单；本轮不为其开放 POST/PUT。

### 5.3 幂等

- POST 触发任务、单条费率发布、导入提交和范围规则发布必须支持 `Idempotency-Key` 请求头，长度 16～128；单纯上传预校验可按文件摘要去重，不强制该请求头。
- 同一用户、同一路径、同一 `Idempotency-Key` 和同一请求摘要重复提交时返回首次结果。
- 相同键但请求摘要不同返回 409 `IDEMPOTENCY_KEY_REUSED`。
- 导入批次完成后再次提交同一批次，返回已完成结果，不重复创建规则版本。
- 服务端只保存幂等键的 SHA-256 摘要，不保存原始请求头；请求体使用稳定规范化后的 SHA-256 摘要比较。

| 动作 | 幂等状态来源 |
|------|-------------|
| 单条费率发布 | `sku_fee_rule.idempotency_key_hash/request_payload_sha256` |
| 导入批次提交 | `sku_fee_rule_import_batch.commit_idempotency_key_hash/commit_payload_sha256` |
| 结算范围发布 | `settlement_scope_rule.idempotency_key_hash/request_payload_sha256` |
| 商品同步触发 | 既有 `job_runs.job_id/metadata_json` 中的幂等键与请求摘要 |

## 6 `GET /api/v1/meta/filters` — 结算筛选元数据

> 消费页面: 全国门店榜单、单店分账、订单费用明细
> 数据源表: `dim_sku_product_rules`、`agg_store_monthly_settlement`、`agg_store_ranking`，以及本轮外既有 `dim_stores` 和用户门店授权关系
> 变更: 保留路径，目标响应改为 camelCase 并补齐账期、方向与正式账期边界

**请求参数**：无业务参数。返回门店列表已经按当前用户范围过滤；全国榜单例外不扩展此门店列表。

**响应 `data`**：

| 字段 | 类型 | 必返/可空 | 说明 | 来源表.列/规则 |
|------|------|-----------|------|---------------|
| `stores` | array | 必返 | 当前用户可选择的门店 | 用户门店授权关系过滤 `dim_stores` |
| `stores[].storeId` | string | 必返 | 门店业务 ID | `dim_stores.store_id` |
| `stores[].storeName` | string | 必返 | 门店名称 | `dim_stores.store_name` |
| `productScopes` | string[] | 必返 | 产品范围，包含 `all` | `dim_sku_product_rules.product_scope` |
| `productScopeTypeMap` | object | 必返 | 产品范围到商品类型的合法映射 | `dim_sku_product_rules.product_scope/product_type` |
| `productTypes` | string[] | 必返 | 当前可用商品类型，包含 `all` | `dim_sku_product_rules.product_type` |
| `saleMonths` | string[] | 必返 | 可用销售月份 | `agg_store_ranking.period_key`、`raw_douyin_orders.sale_time` |
| `verifyMonths` | string[] | 必返 | 可用核销月份 | `raw_douyin_verify_records.verify_time` |
| `statementMonths` | string[] | 必返 | 可用结算账期 | `agg_store_monthly_settlement.month` |
| `periodTypes` | string[] | 必返 | `MONTHLY`、`CUMULATIVE` | 业务枚举；对应 `agg_store_ranking.period_type` |
| `feeDirections` | string[] | 必返 | `PROMOTION`、`MANAGEMENT` | 业务枚举；对应费用表 `fee_direction` |
| `formalPeriodStartMonth` | string | 必返 | 固定 `2026-08` | 已确认正式账期规则 |
| `timezone` | string | 必返 | 固定 `Asia/Shanghai` | 已确认业务时区 |

**约束**：

- 商品类型必须按当前产品范围收敛；无匹配值返回 `[]`，不得保留上一次选择。
- 月份按降序返回；`2026-07` 可作为测试数据筛选值存在，但不得进入正式累计或开票准备范围。
- 管理端对商品分类的更新和商品同步成功后，应使元数据缓存失效。
