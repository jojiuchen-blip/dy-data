# `clue_allocation_rule` - 分配规则

## 业务用途

定义规则身份和作用范围。命中优先级固定为锚点门店、门店组、城市、全局；规则参数全部由不可变版本承载。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `rule_id` | varchar(64) | NO | - | 规则业务 ID |
| `rule_name` | varchar(255) | NO | - | 规则名称 |
| `scope_type` | smallint | NO | - | 1全局、2城市、3门店组、4锚点门店 |
| `scope_key` | varchar(128) | NO | - | 规范化唯一范围键 |
| `scope_city_code` | varchar(32) | YES | NULL | 城市范围代码 |
| `scope_store_group_id` | varchar(64) | YES | NULL | 门店组范围业务 ID |
| `scope_anchor_store_id` | varchar(64) | YES | NULL | 锚点门店范围 ID |
| `is_enabled` | smallint | NO | 1 | 是否允许新线索命中 |
| `current_published_version_id` | varchar(64) | YES | NULL | 当前发布版本业务 ID |
| `description` | varchar(1000) | YES | NULL | 规则用途说明 |
| `created_by` | varchar(64) | YES | NULL | 创建人 ID |
| `state_version` | integer | NO | 1 | 编辑乐观锁版本 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 更新时间 |

## 索引

- `pk_clue_allocation_rule` (`id`)
- `uk_clue_allocation_rule_rule_id` (`rule_id`)
- `uk_clue_allocation_rule_scope` (`scope_type`, `scope_key`)
- `idx_clue_allocation_rule_enabled_scope` (`is_enabled`, `scope_type`)
- `idx_clue_allocation_rule_published_version` (`current_published_version_id`)

## 关系与约束

- 作用范围只能填写与 `scope_type` 对应的一组字段，其他范围字段必须为空。
- 全局范围 `scope_key` 固定为 `global`；同一范围只有一个规则身份。
- 停用规则只影响尚未绑定版本的新线索，不能切换已绑定线索。

## 页面字段映射

- 分配规则：名称、范围、启用状态、当前发布版本。
- 普通管理员只读；最高管理员可创建和维护。

## 迁移说明

由 `clue_allocation_rules` 迁移为单数表，删除数据库外键，保留唯一范围键。

## 使用接口

- `GET /api/v1/admin/clue-allocation/rules` — 分页读取规则及当前发布版本摘要。
- `POST /api/v1/admin/clue-allocation/rules` — 最高管理员创建唯一范围规则。
- `GET /api/v1/admin/clue-allocation/rules/{rule_id}` — 读取规则、版本和绑定数量。
- `PUT /api/v1/admin/clue-allocation/rules/{rule_id}` — 更新名称、说明和启用状态，范围不可变。
- `POST /api/v1/admin/clue-allocation/rule-versions/{rule_version_id}/publish` — 原子更新当前发布版本指针。
- `POST /api/v1/admin/clue-allocation/rule-versions/{rule_version_id}/retire` — 退役后影响新线索范围回退。
- `POST /api/v1/internal/clue-allocation/formal-cycles` — 按范围优先级解析新线索规则。
