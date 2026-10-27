# 月末账号资格证据 Schema（DYDATA-104 / 0066）

> 所属索引：[Schema](../foundation-schema-dy-data.md) · [术语](../foundation-glossary-dy-data.md) · [内部消费合同](../foundation-api-dy-data/settlement-authority.md)
> 依据：`apps/api/dy_api/models.py`、`alembic/versions/20261027_0066_account_qualification.py`、`apps/worker/account_qualification.py`；PostgreSQL 实码回捞，不是新增 DDL。以下三个表没有自增 id 或通用创建/修改三字段。

## 1 `account_qualification_snapshot`

| 字段 | PostgreSQL 类型 | 可空 | 约束/来源 |
|---|---|---|---|
| content_sha256 | varchar(64) | NO | PK；规范内容连同策略版本 SHA-256，重复内容复用 |
| records_json | jsonb | NO | 完整规范绑定记录数组，含原始字段、资格状态及逐行原因 |
| record_count | integer | NO | 规范记录数 |
| policy_version | varchar(64) | NO | 本次规范/资格策略版本 |

UPDATE、DELETE、TRUNCATE 拒绝；不建立可变“当前资格”指针。记录资格与业务原始账号表分别保存，不用累积 raw 行充当本次全集。

## 2 `account_qualification_observation`

| 字段 | PostgreSQL 类型 | 可空 | 约束/来源 |
|---|---|---|---|
| observation_id | varchar(128) | NO | PK；一次受控尝试 ID |
| source_run_id | text | NO | 来源运行 ID；普通索引 `ix_account_qualification_observation_source_run_id` |
| source_type | varchar(64) | NO | 来源类型 |
| started_at | timestamptz | NO | 实际采集开始时间 |
| ended_at | timestamptz | YES | 实际完成/失败时间，running 时 NULL |
| state | varchar(16) | NO | CHECK running/success/failed |
| complete | boolean | NO | 应用初值 false；成功必须 true |
| content_sha256 | varchar(64) | YES | FK → snapshot，ON DELETE RESTRICT；失败不得引用快照 |
| proof_json | jsonb | NO | 来源、范围、任务与完整性证明；应用初值 {} |
| error_code | varchar(128) | YES | 稳定失败码 |

索引 `ix_aqo_started(started_at, observation_id)`。唯一允许的 UPDATE 为同 observation/run/start 的 running 一次转终态，结束时间不得早于开始；成功必须 complete 且有快照，失败必须不完整且无快照。终态、删除和 truncate 禁止。成功终态与快照在同事务提交，失败不能更新完整成功标志。

## 3 `account_qualification_version`

| 字段 | PostgreSQL 类型 | 可空 | 约束/来源 |
|---|---|---|---|
| version_id | varchar(128) | NO | PK；月/观察/内容/策略导出的不可变标识 |
| business_month | varchar(7) | NO | `uq_aqv_month` 唯一，一个业务月一版 |
| cutoff_at | timestamptz | NO | 上海次月 1 日 00:00 截止 |
| observation_id | varchar(128) | NO | FK → observation，RESTRICT |
| content_sha256 | varchar(64) | NO | FK → snapshot，RESTRICT |
| policy_version | varchar(64) | NO | 被冻快照的策略版本 |
| frozen_at | timestamptz | NO | 实际冻结时间，不倒填为月末 |

UPDATE、DELETE、TRUNCATE 禁止；并发按月唯一且锁内重查，已有版本幂等返回，之后采集不能改写该版。

## 4 费用血缘与发布来源

- `settlement_fee_result.account_qualification_version_id varchar(128) NULL`，命名 FK `fk_fee_account_qualification_version` → version.version_id，RESTRICT；旧费用保留 NULL，不追写 8/9 月结果。
- 新 10 月及以后费用使用有效核销业务月的冻结版本；费用输入指纹、月结 preflight/watermark、重建元信息均固定该版及来源摘要，不能仅检查当前 raw 或成功 job receipt。
- `dashboard_publication_source_counters` 的精确来源名为 `account_qualification_version`。0066 初始化计数行，版本 INSERT 才推进 generation；snapshot/observation 不触发日常发布漂移。`sources._FINANCE_SHARED`、`finance.COMMON_SOURCE_TABLES` 纳入此来源，独立排名清单不变。
- 有证据或已有费用引用时 downgrade 拒绝删除；空表回退保留费用表既有触发器。无公开资格 CRUD/强制冻结接口，消费者是 worker 结算、月结和财务发布链。

## 5 资格、时间与容量约束

- 同一源记录账号类型精确为“子机构门店号”或“子机构区域号”，且绑定状态为“认证成功”才合格。认证信息自由文本不做白名单。正式中文列中的“绑定已拒绝”“未知状态”“子机构号”等逐行不合格并保留原因；明确不合格个人记录无账户 ID 可保留，不因此漏掉合格全集。缺列、数字码合同不明、损坏或身份冲突保守阻断，不猜数字类型映射。
- 月未结束拒绝冻结。候选必须在该月上海月末自然日的最后两小时内开始、在 cutoff 前完成；最新开始/完成尝试失败或不完整、任意 running、跨 cutoff、过旧均拒绝。两小时是运行完整性闸门，记录实际起止，不声称精确 0 点观察。
- 自动采集只在上述窗口持久化永久资格证据，复用约 30 分钟调度；每月最多 8 次 admission，额外一个失败预算标记阻断超预算，最多 8 份不同快照、每份规范内容上限 8 MiB（未计 JSONB/索引开销）。正常约 4 次，同 hash 去重；平日完整导出/upsert 及证明日志继续，但不持续新增这些永久表。显式受控 start/complete 函数不用于绕开自动预算。
- 全量证明绑定无筛选空 `{}` 的 `/life/gate/v3/collaborator/download_bc/start/` POST、同 download_id、download_type=120、完成 status=2、任务实际生成时间及下载 bytes/SHA-256；解析 workbook 必须 reset_dimensions 并校验正式列/身份/行完整性。不捡 mtime 最近文件，不以其他 scope 的 bind/list Total 强比导出总量。失败、不完整或无正式文本合同不得伪记资格完整。
- 区域账号资格不证明具体销售店；销售时有效关系、核销业务月、费率匹配日分开。官方短抖音号原来源匹配与错误分类见 [内部合同](../foundation-api-dy-data/settlement-authority.md)。迟到、退款和跨月重建使用原业务月冻结版，次月当前资料不能补历史。
