# PRD 9: 四类模板、差异、错误与版本

> **文档版本**: 1.0 | **最后更新**: 2026-08-20
> **关联文档**: [mainprd](../mainprd-dy-data.md) · [PRD 5](05-subprd-finance-promotion.md) · [PRD 6](06-subprd-finance-management.md) · [用户流程](../../../src/frontend/page-preview/explainer-flow-dy-data.md) · [交互语义](../../../src/frontend/page-preview/explainer-b-interaction-dy-data.md) · [术语表](../foundation/foundation-glossary-dy-data.md) · [Schema](../foundation/foundation-schema-dy-data.md) · [API](../foundation/foundation-api-dy-data.md)

## §1 文档范围

本文档覆盖**财务导入**（四类模板 + 五种结果场景 + 整批原子写入 + 更正版本）。

### 需求清单

| # | 需求 | 需求简述 | 对应章节 |
|---|---|---|---|
| R1 | 预校验 | 流式解析并收集全部错误 | §3 |
| R2 | 差异提交 | 无变化、差异和首次导入采用不同反馈 | §3 |
| R3 | 版本与更正 | 并发冲突拒绝，更正生成覆盖版本 | §3 |

## §2 页面整体布局

```
[模板类型][账期][上传] [首次成功/无变化/差异待确认/整批失败/版本冲突] [错误下载][历史]
```

## §3 四类模板导入

### 3.1 用户体验

**数据来源**：`GET/POST /api/v1/admin/finance-imports`、`GET /api/v1/admin/finance-imports/{batchId}`、`POST .../commits`、`POST .../corrections`、`GET .../error-file`。

**交互语义引用**：`dy19.import.result.1`、`dy19.routing.navigate.1`

**布局**：

```
[基础信息|推广服务费厂家结果|管理服务费厂家结果|SAP 确认]
[上传→预校验→差异确认→原子提交] [错误分页/下载] [版本冲突刷新]
```

**前端职责**：不自行匹配门店、不截断错误、不判定幂等；只渲染批次状态、差异和全部错误入口。

### 3.2 服务端处理逻辑

1. 流式解析文件，按模板验证必填、格式、门店 ID 和业务唯一键；不使用来源行 ID。
2. 以“业务唯一键 + 标准化内容 + 文件摘要”判定幂等；无变化不生成业务版本。
3. 任一错误时正式业务表零写入；错误行全部保存并分页/文件输出。
4. 有差异时等待确认；提交前校验读取版本，冲突返回当前版本和最近操作信息。
5. 四类模板统一使用新版本；撤销通过更正导入覆盖，不删除历史。
6. 管理服务费厂家结果在一行内同时登记发票和厂家全额扣款；不再拆成两个模板。四类业务键分别为门店 ID、发票号码、门店 ID + 账期、门店 ID。

### 3.3 数据链路

| UI 元素 | API 字段 | 计算规则 | 数据源（服务端读取） | 配置源（服务端读取） |
|---|---|---|---|---|
| 批次场景 | `batchStatus/contentChanged` | 映射五种用户反馈 | `finance_import_batch.batch_status/content_changed` | — |
| 读取/当前版本 | `readVersion/currentVersion` | 提交时必须相等 | `finance_import_batch.read_version/current_version` | — |
| 错误行 | `errors.list[]` | 返回本行全部错误 | `finance_import_row.row_number/business_key/validation_errors` | — |
| 成功目标 | `targetRecordId` | 仅提交成功后返回 | `finance_import_row.target_record_id` | — |

### 3.4 异常与兜底

**服务端兜底**：

| 场景 | 处理 |
|---|---|
| 任一行错误 | 整批失败，正式业务表零写入 |
| 版本冲突 | 409 返回读取/当前版本、最近操作人和时间 |
| 大文件错误很多 | 流式解析、数据库落行、分页查询，避免一次性占用大内存 |

**前端渲染兜底**：

| 场景 | 处理 |
|---|---|
| 整批失败 | 显示错误总数、分页摘要和“下载全部错误” |
| 版本冲突 | 显示版本与最近操作信息，只允许刷新重验 |
| 无变化 | 显示无变化并结束，不出现提交按钮 |

### 3.6 验收

| # | 类型 | 场景 | 触发条件 | 预期结果 |
|---|---|---|---|---|
| 1 | 业务规则 | 全部错误 | 多行多字段错误 | 所有错误行可分页查看和下载，不在首错终止 |
| 2 | 业务规则 | 原子性 | 任一错误行 | 正式业务表写入数为 0 |
| 3 | 业务规则 | 幂等无变化 | 相同标准化内容重传 | 返回无变化，不生成新版本 |
| 4 | 异常兜底 | 并发冲突 | 预览后他人已提交 | 409，展示版本与最近操作并要求刷新 |

## §4 接口契约

### 4.1 接口：财务导入 #37—#42

完整契约见 [账单发票 API §5](../foundation/foundation-api-dy-data/billing-invoice.md#5-四类财务导入)。禁止部分写入、自动截断、人工待匹配池和模糊匹配。
