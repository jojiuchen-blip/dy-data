# `clue_contact` - 线索联系方式

## 业务用途

集中保存线索明文手机号、脱敏展示值和解密状态。明文只从本表按服务端权限读取，避免在查询投影、日志、异常和普通导出链路中扩散。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `lead_key` | varchar(64) | NO | - | 主线索业务键 |
| `order_id` | varchar(64) | YES | NULL | 订单编号 |
| `phone_plain` | varchar(32) | YES | NULL | 后台明文手机号，列权限受限 |
| `phone_masked` | varchar(32) | NO | - | 中间四位脱敏号码 |
| `phone_hash` | char(64) | YES | NULL | 标准化号码摘要，仅用于一致性检查 |
| `phone_source` | smallint | NO | 1 | 1原始明文、2平台解密、3历史迁移 |
| `decrypt_status` | smallint | NO | 0 | 0待处理、1成功、2源无号码、3失败 |
| `source_record_key` | varchar(128) | YES | NULL | 最近联系方式来源原始行 |
| `decrypted_at` | timestamptz | YES | NULL | 最近成功解密时间 |
| `last_verified_at` | timestamptz | YES | NULL | 最近格式校验时间 |
| `decrypt_error_code` | varchar(64) | YES | NULL | 脱敏错误码，不保存密钥或 token |
| `data_version` | integer | NO | 1 | 联系方式更新版本 |
| `is_available` | smallint | NO | 0 | 1表示当前有可用明文 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 更新时间 |

## 索引

- `pk_clue_contact` (`id`)
- `uk_clue_contact_lead_key` (`lead_key`)
- `idx_clue_contact_order_id` (`order_id`)
- `idx_clue_contact_decrypt_status` (`decrypt_status`, `gmt_modified` DESC)

## 关系与安全约束

- 一个 `lead_key` 最多一条当前联系方式；号码变更通过 `data_version` 和操作审计追踪。
- 明文读取必须同时满足：当前活动轮次、责任门店命中、账户功能权限命中；管理数据范围本身不授予明文权。
- 失效、核销、退款、总部池或历史门店只返回 `phone_masked`。
- `phone_plain` 不得进入 `clue_center_order`、日志、异常文本、候选快照或普通 API 响应。
- 查看、复制和含明文导出均写入 `clue_operation_audit_log`。

## 页面字段映射

- 列表和详情默认读取 `phone_masked` 投影。
- 用户点击查看/复制时，服务端临时读取 `phone_plain`；前端状态失效后立即清除。

## 迁移说明

从 `clue_center_orders.phone_plain`、`phone_masked`、`phone_source` 迁入。迁移完成并核验后从查询投影删除明文字段。

## 使用接口

- `POST /api/v1/clues/orders/{order_id}/phone-access` — 按 reveal/copy 目的临时读取明文并审计。
- `POST /api/v1/clues/assignment-round-exports` — 逐行授权读取明文并记录导出摘要。
- `POST /api/v1/internal/clue-center/materializations` — 解密后集中写入明文、脱敏号和解密状态。
- `POST /api/v1/internal/clue-allocation/data-quality-checks` — 检查明文仅存在本表且脱敏投影一致。
- 列表/详情接口只读取 `clue_center_order.phone_masked`，不直接读取本表明文。
