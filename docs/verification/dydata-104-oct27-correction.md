# DYDATA-104：历史附件金额纠错服务与CLI

本项属于既有T3.1的104-O27-FUYANG限定实现，复用正式人工纠错调整、账单版本及财务审计模型。这里没有执行生产更正、票据登记或发布，也不代表页面金额已生效。测试及本文仅使用合成标识；真实清单和附件只保存在ignored私有证据目录。

## 执行合同

`apps/worker/historical_fee_correction.py`提供`preview_correction`与`apply_correction`；`scripts/historical_fee_correction.py`默认预演，提交必须携带所审阅预演的`preview_sha256`。使用现有`DY_DATABASE_URL/DATABASE_URL`配置；命令不打印连接配置或原附件。

本次例外仅接受完整8券16方向、2026-09业务月与同月入账。数量与历史月份是批准范围门禁，不包含真实门店/订单/券ID。实际非零差额数、新账单数和各方向分金额均从manifest及数据库计算，不内置生产金额或变更账单数量。

每张券两个方向必须共用同一真实来源行，8券不能复用同一来源行。源文件为保留原始`tables`数组的私有JSON；服务实际读取调用者提供的字节，校验文件SHA、源行SHA、订单号+券码、核销月及相应费用列。金额必须为整数分，ID必须是文本，不从商品名、昵称或现行费率重新推断历史金额。

### Manifest结构

顶层仅允许`schema_version=1`、`request_id`、`approved_by`、`approval_reference`、`rows`。`rows`必须16行，每行完整提供下表字段；未知字段、重复键身份、缺失字段或格式错误整批拒绝。

| 类别 | 字段 |
|---|---|
| 精确业务键 | `order_id/coupon_id/fee_direction/store_id/business_month/posting_month` |
| 已审阅版本 | `expected_fee_result_id/expected_statement_id/expected_statement_version/expected_entry_id` |
| 金额 | `old_fee_cent/target_fee_cent`，两者均为非负整数分；差额可正、负或零 |
| 原附件依据 | `source_sha256/source_table_index/source_row/source_coupon_code/source_row_sha256` |

`fee_direction`为整数1/2；`source_table_index`为0基表索引；`source_row`为**含表头的1基行号**。`source_row_sha256`使用服务公开函数`evidence_sha256`计算原数组行的规范JSON摘要；`source_sha256`为源文件原始字节SHA。`manifest_sha256`为同函数计算的完整manifest摘要，CLI另返回文件字节SHA，二者不要混用。

源推广费用列为`对应推广费金额`，管理费用列为`对应管理服务费金额`；原JSON中`订单编号`、`券码（已撤销核销加密）`、`核销时间`必须与所审阅行一致。此服务不新增来源下载、当前账号绑定或历史身份推测。

```powershell
python scripts/historical_fee_correction.py --manifest .tmp/private-correction.json --source .tmp/private-source.json
python scripts/historical_fee_correction.py --manifest .tmp/private-correction.json --source .tmp/private-source.json --apply --expected-preview-sha256 <reviewed-preview-sha256>
```

`--source`可重复，服务以实际字节SHA定位对应文件；只读预演不写审计或业务表。PostgreSQL CLI预演使用REPEATABLE READ、READ ONLY。apply使用READ COMMITTED，在取得锁后重新读取；拒绝可能沿用锁前旧快照的其他隔离级别。

## 事务、版本和保护

先按request取得事务级锁，再按排序后的`store_id+month`取得与settlement相同的slot锁，随后锁当前账单行。锁后重新核对当前fee指针、结果状态、订单/券/方向/责任门店/月/旧金额、账单当前版本、entry来源和费率/基数快照，当前账单还必须是该slot最新版本；整批状态摘要必须匹配预演。

同slot任一历史版本存在确认、锁账、发票登记/推广票据分配或异议事实，即明确拒绝。现有人工/退款调整、调整来源项或结转来源/应用也拒绝，避免不完整复制复杂财务血缘。不会选择别月、解除保护状态、创建异议、自动确认、登记发票或推进付款。

仅非零差额新增稳定ID的`SettlementFeeAdjustment`，`adjustment_type=4`、`refund_event_id=None`、基数调整为0，沿用原费用结果ID和规则版本。原fee、当前指针、原实收、费率和归属均不改。

每个有非零差额的当前账单创建Vn+1：完整复制原头/产品行/来源entry的业务快照，保留原版、设置`supersedes_statement_id`，追加精确manual adjustment entry。新entry的`adjustment_type_snapshot=4`、`refund_at_snapshot=None`，不得显示成人为退款。header/line/entry计数、基数和金额逐层核验后才切换当前指针；新版本保持待确认status2。仅零差额涉及的账单不增加版本。

复制仅使用旧账单持久化快照，不重新读可变raw/门店资料。预演返回旧来源项中的目标外entry指纹、完整fee依据和当前指针指纹；提交再次验证原目标外entry与fee/指针未变。新增克隆行按新身份保留同一业务快照。该指纹覆盖受影响slot及其历史来源，并非全库扫描证明；外部全库/发布指纹由主线程负责。

所有16方向均追加`FinanceOperationAudit`，包括零差额；`operation_type=HISTORICAL_ATTACHMENT_CORRECTION`、`target_type=SETTLEMENT_FEE_RESULT`、`target_id=原fee_result_id`。`before_snapshot`保留完整旧fee和原entry；`after_snapshot`保存manifest各行、新旧金额、差额、source SHA/行SHA、批准人/依据、adjustment ID、共同提交结果及完整证据SHA。审计只新增，不改写既有审计。

同request同manifest重试核验16条完整审计、证据SHA、调整及账单提交后状态，返回`already_applied=true`，不再产生差额或版本；同request异内容冲突。半成审计/缺调整/篡改状态失败关闭。若提交后又发生确认、开票、版本或来源变化，重试拒绝，不把它作为正常幂等入口再次修改财务事实。

服务使用savepoint保证整批失败回滚，调用者负责外层commit/rollback。CLI提交后在新事务严格回读；若commit已成功、回读期间出现后续状态冲突，仍明确输出提交结果，`durable_readback_verified=false`并以exit3提示核查，不伪称已回滚。预提交业务拒绝为exit2。

## 验证记录

合成样本为8券双方向、9个当前账单，外加同账单的无关来源项。差额数量、账单版本数量、完整快照、目标外费用/指针/来源、零方向审计及分方向合计均核对；测试同时覆盖负人工差额、全零批次、预演无写、CLI提交后回读和重复调用。

保护/失败用例覆盖旧fee/entry/账单版本、责任门店、错月/错方向、源文件/源行/券码/金额不符、非法整数/重复行、全部确认/发票/异议/锁账事实、复杂调整/结转、半成审计、缺调整、篡改审计、预演后目标外快照变化和中途异常整批回滚。

真实PostgreSQL使用测试专用环境变量`DYDATA_HISTORICAL_FEE_TEST_DATABASE_URL`；只允许loopback的`dydata_delivery_test`，每个测试创建独立随机schema并只清理该schema。实际测试同request并发只产生一次结果、不同request竞争同slot不重复入账、确认竞争获胜后整批拒绝、事务回滚/提交回读及拒绝旧隔离快照。不会清理共享public或使用生产数据。

2026-10-27最终执行（exit0，86.89秒）：

```text
python -m pytest tests/test_historical_fee_correction.py tests/test_historical_fee_correction_cli.py tests/test_historical_fee_correction_postgres.py tests/test_billing_statement_generation.py tests/test_historical_sale_attribution.py -q --tb=short
112 passed, 2 skipped, 4 warnings
```

本项5个真实PG用例全部执行通过。2个skip属于既有账单测试使用的另一专用环境变量未配置，不将其记为通过；4个warning来自既有Starlette/Alembic弃用提示。编译检查通过；suite lock有效，global-file检查0错误0警告、S4路由/Task环境及上下文门禁通过。私有运行日志为`.tmp/historical-correction-final-tests.log`。

源码实现、隔离PG验证、主线程聚合/发布、生产应用和业务验收分别记录；未运行本地全仓、Web构建或CI，这些由主线程在最终集成树执行。

## 主线程集成边界

本实现不修改settlement重算、聚合/发布、dashboard读取或模型/迁移。主线程必须根据16条exact fee audit保护原fee依据，并按真实退款/取消处理后续事件，再重建/发布使账单、财务、订单分佣及导出一致。单独运行本CLI不宣称整条发布链已验收。

原票号、日期、金额和分配证据缺失只阻止票据登记；本服务不制造票据。其他历史保护金额、后22券及其他门店月份不随本次例外入账。

本任务复用现有Schema和人工纠错枚举，无Schema/公开API foundation漂移；新增内部manifest与审计形状在本验证记录中明确。正式计划、Linear状态和后续集成验收由主线程统一回写。
