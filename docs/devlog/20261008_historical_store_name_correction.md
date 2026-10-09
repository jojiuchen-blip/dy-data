# 历史门店名称纠正与上线核对

## 范围与依据

用户确认组织源表中两家服务店名称互换，源 XLSX 已另行纠正。本次追加
Alembic `20261008_0061`，前序为 `20260916_0060`，通过既有部署迁移流程执行。
仅修改 `ranking_store_org_history.store_name`，覆盖符合条件的全部历史版本。

| store_id | 必须匹配的服务店编码 | 原错误名称 | 正确名称 |
| --- | --- | --- | --- |
| 7380305331350308915 | BYDEFJ008W | 福建龙长鸿汽车销售服务有限公司 | 福建龙迪鑫汽车销售服务有限公司 |
| 7402151814281398298 | BYDFJ062W | 福建龙迪鑫汽车销售服务有限公司 | 福建龙长鸿汽车销售服务有限公司 |

ID、编码、原错误名称三个条件必须同时满足。不满足、已经正确、或后来改成其他
名称的记录均不修改。POI 不存在于该历史表，本次不写入或推断 POI 映射。
组织归属、业务日期、版本号、线索首分配绑定、资格名单、指标分子分母和快照均保持原值。
既有快照动态关联组织历史名称，因此不需要重算才能显示更正后的名称。

## 来源与审计

`source_hash` 保留原导入配置的身份，不重新计算或伪装为纠正后的源文件摘要。
迁移专属表 `ranking_store_name_correction_0061` 保存实际被修改记录的版本、门店 ID、
服务店编码、原名称、新名称、原来源摘要、生效时间和纠正时间。
审计表与当前历史行一起提供这次显式更名的追溯链；原始导入名称可以从审计表还原。
该表由此一次性迁移管理，不修改已冻结的 V1 排行榜 schema 定义。

PostgreSQL 执行时先获取既有配置/快照发布事务锁，再短暂获取组织历史表的
`SHARE ROW EXCLUSIVE` 锁，避免采集更名前记录和更新之间发生并发写入。
普通查询可以继续；配置发布和该表写入需等待迁移事务结束。
重复运行 `alembic upgrade head` 不重复更名或产生重复审计记录。

## 上线与核对

沿用部署脚本的数据库备份及 `migrate` 服务，不额外执行全表交换 SQL。
正式环境实际影响行数取决于已导入的历史版本数，不能将本地测试的 4 行当作生产行数。

迁移前后可运行以下最小范围查询并保存结果，逐版本检查编码和名称。

```sql
SELECT mapping_version, store_id, service_store_code, store_name, source_hash,
       effective_from
FROM ranking_store_org_history
WHERE store_id IN ('7380305331350308915', '7402151814281398298')
ORDER BY mapping_version, store_id;
```

迁移后确认版本为 `20261008_0061`，记录审计计数，并对照页面和导出结果。
审计计数为零可能表示原名称已经正确，也可能表示 ID/编码不匹配；应根据上面的
查询区分原因，不扩大更新范围。名称以外的字段应与迁移前结果一致。

```sql
SELECT version_num FROM alembic_version;
SELECT mapping_version, store_id, service_store_code, old_store_name,
       new_store_name, source_hash, corrected_at
FROM ranking_store_name_correction_0061
ORDER BY mapping_version, store_id;
SELECT count(*) AS corrected_rows FROM ranking_store_name_correction_0061;
```

## 回滚

需要撤回名称纠正时，先导出上面的审计查询，再通过既有迁移容器执行
`alembic downgrade 20260916_0060`。仅对审计中确实改过、且当前服务店编码、
名称、来源摘要和生效时间仍与纠正记录一致的行恢复原名称。
后续改名、修改编码或替换来源的记录不会被覆盖；已经正确而未进入审计表的
记录也不会被逆向改错。回滚保留当前其余所有字段，随后删除迁移专属审计表。
如果更晚的迁移已经上线，须先评估那些迁移的回滚影响，不直接跨版本回滚。

本修复不修改现有 API、指标口径及 V1 schema 契约；新增表仅承载迁移审计。

## 本地验证

- `tests/test_store_name_correction_migration.py`：7 项通过。覆盖两家门店多版本
  更名、编码不符及同名其他门店不修改、已正确名称不修改、审计原值、既有快照
  关联名称、全部其他排行榜字段不变、重复升级、回滚后再升级和空库。
- 同一专项测试覆盖后续改名、改编码、改来源摘要、改生效时间时的回滚保护。
- `tests/test_deploy_compose_config.py`：26 项通过，三个 PostgreSQL 发布验证脚本
  的目标 head 同步为 `20261008_0061`。
- `tests/test_alembic_migrations.py`：61 项通过，包含单一可部署 head、历史分支
  升级及既有迁移回滚回归；`git diff --check` 对本任务文件通过。
- PostgreSQL 部分验证了离线 SQL 生成与锁语句，未在此任务连接真实 PostgreSQL
  或生产数据库；正式环境的影响行数和部署结果需按上线核对步骤确认。
