# `clue_store_group_member` - 门店组成员

## 业务用途

保存门店加入和退出门店组的有效期历史。V1 同一门店同一时刻最多属于一个活动线索门店组，避免规则范围优先级歧义。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `member_id` | varchar(64) | NO | - | 成员关系业务 ID |
| `store_group_id` | varchar(64) | NO | - | 门店组业务 ID |
| `store_id` | varchar(64) | NO | - | 内部门店 ID |
| `store_name_snapshot` | varchar(255) | YES | NULL | 加入时门店名称 |
| `is_active` | smallint | NO | 1 | 当前是否生效 |
| `active_from` | timestamptz | NO | CURRENT_TIMESTAMP | 生效时间 |
| `active_to` | timestamptz | YES | NULL | 失效时间 |
| `created_by` | varchar(64) | YES | NULL | 操作人 ID |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 更新时间 |

## 索引

- `pk_clue_store_group_member` (`id`)
- `uk_clue_store_group_member_member_id` (`member_id`)
- `uk_clue_store_group_member_active_store` (`store_id`) WHERE `is_active=1`
- `idx_clue_store_group_member_group_active` (`store_group_id`, `is_active`)

## 关系与约束

- 新增活动关系前，应用层必须关闭该门店其他活动关系。
- 历史关系不参与新规则匹配，但用于解释历史规则作用范围。

## 页面字段映射

- 分配规则后台：门店组成员列表和编辑。

## 迁移说明

由 `clue_store_group_members` 迁移并补充关系业务 ID、有效期和历史保留。删除数据库级级联。

## 使用接口

Phase 4 回填。
