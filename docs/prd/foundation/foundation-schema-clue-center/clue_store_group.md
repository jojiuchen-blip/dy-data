# `clue_store_group` - 线索门店组

## 业务用途

定义一组共享同一分配规则作用范围的门店。V1 不实现 A/B 测试，但保留门店组作为城市与单店之间的稳定配置层。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `store_group_id` | varchar(64) | NO | - | 门店组业务 ID |
| `group_name` | varchar(255) | NO | - | 唯一名称 |
| `description` | varchar(1000) | YES | NULL | 用途说明 |
| `is_enabled` | smallint | NO | 1 | 是否可用于规则匹配 |
| `sort_order` | integer | NO | 0 | 后台展示排序 |
| `created_by` | varchar(64) | YES | NULL | 创建人 ID |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 更新时间 |

## 索引

- `pk_clue_store_group` (`id`)
- `uk_clue_store_group_group_id` (`store_group_id`)
- `uk_clue_store_group_group_name` (`group_name`)

## 关系与约束

- 已被发布规则版本引用的门店组不得物理删除，只能停用。
- 停用不改变已锁定规则版本和历史决策证据。

## 页面字段映射

- 分配规则后台：门店组范围选择和只读详情。

## 迁移说明

由 `clue_store_groups` 迁移为单数表，文本主键改为业务唯一键。

## 使用接口

Phase 4 回填。
