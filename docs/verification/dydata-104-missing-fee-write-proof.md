# DYDATA-104：精确漏费修复的事务写入证明

基线 `344ba4cc7ae279996d6ed65e9a8f4f4c6c385fb5`。本次只修改精确漏费修复保护及专项测试，不改费用算法、预算、审核清单、费率、历史月份范围或发布流程；没有生产执行。主线程负责集成、重新 CI、预演审核和唯一生产操作。

## 问题与边界

主线程生产失败日志显示，50 券事务在写入前对 `dashboard_ranking_orders` 执行全量 `to_jsonb`、逐行 SHA256 和排序聚合时触发5秒 SQL 超时。独立回读373券 audit/current/history 全0，发布 worker 已由主线程恢复。后续目录估算还发现大型 `settlement_ranking_overlay`、`settlement_order_details`、partition manifest 和 monthly overlay；只删 dashboard 表扫描不能解决同类瓶颈。

`_financial_table_names` 的发现范围、所有原配置/来源/财务锁继续保留，并显式加入 DQ。未知 sidecar 也必须接受统一保护。新增 materialized view、foreign table、分区、继承或非 heap 关系不会被 `pg_tables` 隐藏，而是在写入前失败关闭。

## 保护证明

1. 在原共享 claim 锁和排序 `SHARE ROW EXCLUSIVE` 关系锁下，以 schema-qualified 名称取得关系身份；锁前后身份及本事务计数必须一致。所有保护关系绑定 schema/OID、解析后的OID、heap文件身份、tablespace、列/默认值、约束、规则、触发器及函数定义、索引定义及文件身份。身份或保护集合变化拒绝整批。
2. `pg_stat_xact_all_tables` 比较同一事务内基线与最终 insert/update/delete 计数。未知及已知非目标关系必须零增量，覆盖数据库内部触发器、FK效果和写后恢复原值。使用事务计数，不使用存在延迟的全局累计计数。`track_counts` 关闭、统计缺行或关系类型不支持均拒绝。
3. 真正账务事实仍逐行 SHA256：费用/current（排除精确目标券）、调整、结转、账单/行/entry/确认、争议、票据/分配/生命周期、审计、导入、SAP、财务档案及冻结账务来源。固定表集合见代码及新预演合同。大型派生关系和未知 sidecar 不扫业务行，但并未退出锁或零写入保护。
4. 允许范围有额外证明。费用/current 只能各插入 `2*N` 行，不能更新或删除，业务字段、版本、计算运行和指针逐项回读匹配 quote。审计只插入本次精确1行，既有审计仍逐行摘要。DQ只能删除原已存在的目标 issue ID；剩余目标行逐字段不变，实际删除计数须恰等于目标集合消失数量，因此不能用目标删除额度删除别的券。
5. 正式0063来源触发器更新精确三个来源行：费用 `4*N`、current `2*N`、审计 `1`。费用每方向先发出零行旧结果 UPDATE，再 INSERT；语句级触发器两次都会执行，不能按插入元组误算 `2*N`。三个来源行都必须原已存在；函数原本在缺行时抛错，不补造计数。逐行身份/其他字段不变、generation精确增量、changed_at处于实际写入时间窗；计数表无插入删除，总更新计数也必须相等。其他来源行的集合和全部字段保持原摘要。
6. 审计先 flush，再 `SET CONSTRAINTS ALL IMMEDIATE` 运行待执行约束触发器。随后检查无 pending ORM 写入，`expire_all` 后重新 SELECT 全目标输出，refresh审计并逐列核对，再完成最终账务摘要和关系计数/身份检查。最后封住直到 driver commit 的任何后续SQL或自动flush；正常 driver commit 不经过 SQL 执行监听，已用真实PG正例确认。监听只封闭最后间隙/拒绝意外直接DDL，不承担数据库内部效果的完整保护。

审计来源 `finance_operation_audit` 的精确+1是旧成功操作本来就产生的正式失效更新；旧代码在最后摘要之后才插审计，所以未比较到此行。本次在主线程审阅真实0063函数并批准后，将这个既有行为纳入最终证明，不压制、回退或补写来源计数，也不扩大业务操作。

## 审核与兼容

`WRITE_PROOF_CONTRACT`（含核心账务表集合、三来源精确增量和DQ规则）进入新 preview hash，必须重新预演审核。请求文档、预算和原 request digest 计算保持兼容：旧成功 audit仍按原request/exclusions/hash与实际输出回读，不能写回、升级或篡改旧审计。没有新增队列、重试、分批器、全月回退或迁移。

预算仍是单SQL5秒、锁1秒、整事务30秒；任何拒绝或超时都回滚整批。没有因数据量或机器速度调大预算。真正账务事实行摘要本身若超预算，仍应拒绝，不能动态退化为少量抽样。

## 已取得的本地证据

所有 PostgreSQL 写测试仅在主线程指定的 loopback 专用测试库中使用唯一schema；未显示连接串或密码。使用共享venv，未升级依赖。

- 首组正常提交、幂等、完整迁移及事务特征：3项真实PG通过，原preview严格只读也有通过证据。
- 首组数据库内部/DML/DDL/例外范围/并发反例：35项真实PG通过，225.03秒；后续增加索引/触发函数DDL、真实关闭统计、缺统计故障注入及旧审计兼容案例，最终JUnit单独归档。
- 50券/100方向性能：5张派生sidecar共500,000行、`pg_total_relation_size`合计587,243,520字节；实际成功提交100费用、100current、1审计，调整和任务0。preview3.703秒、apply11.094秒。核心账务摘要前0.094/后0.047秒，原普通精确writer6.562秒，最终关系证明0.110秒；共观察6868条SQL。无大派生业务行扫描。收据位于本地 `.tmp/write-proof-evidence/perf-temp/`，JUnit为 `large-50-real-pg.xml`。
- 兼容性探针离线校验另附。独立脚本不import或执行新修复，默认无DB；显式执行只有5条metadata/config/locks SELECT，RR只读、SQL3秒/锁500ms/20秒wall，最终rollback，无业务行扫描。
- 主线程已实际执行首版及完整索引/触发函数元数据v2兼容性探针：PG180004、74关系、track_counts on、无不兼容或冲突关系锁。本worker只读核对v2本地证据文件，SHA256为`366eb23feaca64bf3c9e0ad336409d5ad5fc0ec9a84f4bba19865e69d60fb40f`，未执行生产。最终v3仅更新readback加固后的源码绑定，选择/元数据/配置/锁SQL与v2逐项相等；离线另验此等价性。此证据只证明当时结构先决条件，不等于生产apply成功或之后仍有静默窗口。

最终回归结果、补充用例及patch摘要以交接的JUnit和本地证据索引为准。旧失败JUnit保留，不能覆盖或说成已通过。

### 最终验证与源码对应

- 写入证明完整实现、最后identity-map回读加固前的源码SHA256：`1d3c5bb557963a697439889c4972e51c904c2ce367481101c33e60e0f044c628`。`final-specialist-suite.xml`：125通过（47 SQLite、78真实PG），0失败/跳过，757.27秒；仅单独已有成功证据的500k派生50券性能case被显式deselect。旧PG文件38项全部运行，包含10/20/50/373预算样例，未把预算拒绝当生产成功。
- 最终源码SHA256：`7643847ebda7b069defecd6213c1115850f05cf4d38c38e1400d8b9eb8364b78`。除最终回读强制`populate_existing`、拒绝pending写入及注释外，保护SQL/合同/预算与上一项相同。在该源码上重跑24项相关真实PG：22通过，新增2个缓存反例因测试把业务audit_id当作bigint主键查询而在断言前失败，记录保留于`final-readback-subset.xml`；只修正测试查询后，`final-stale-cache-corrected.xml`中fee/audit两项均通过，16.31秒。即最终24个验收case由这两份原始证据覆盖，不伪造一份全绿重跑记录。
- 最终源码的24项覆盖正常提交/完整迁移/幂等、异常writer、10种audit/deferred/内部DDL效果、目标DQ、旧成功审计兼容、未过期fee及audit缓存篡改、提交seal、事务计数跨idle即时性及50券大派生表。最终50券复测preview1.812秒/apply5.906秒、关系证明0.062秒，100fee/100current/1audit实际提交；500,000派生行/587,243,520字节及6868 SQL同前。此性能收据位于`final-readback-temp/`。
- 最终源码绑定的独立compatibility v3：SHA256 `d16ce8b5a938756529e441368be782fe63cab3198d35514be2c2aea59ebfcf20`；13项离线通过，包含v2/v3除源码绑定外全部payload/SQL相等。没有因此再次执行生产查询。

全部本地PG测试已结束并释放。没有commit、push、部署或生产修复；集成负责人仍需在冻结树完成正式CI/发布门禁。

## 限制

本证明针对可信 PostgreSQL、已审阅应用路径及普通heap，不是恶意超级用户、扩展、外部FDW或绕过PostgreSQL物理写入的安全沙箱。直接DDL/opaque语句被拒绝；数据库内部对受保护关系的写入/结构变化由独立计数和catalog证明处理。部署期间仍须维持既有DDL/发布/源任务协调；元数据预检不替代正式事务锁。

没有声明373券单事务可完成、旧未运行测试已通过或生产修复已成功。本任务无foundation schema/API合同漂移，不写计划状态或生产资料。
