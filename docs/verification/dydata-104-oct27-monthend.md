# DYDATA-104：10月起月末账号资格实现与验证

本记录仅对应104-O27-ACCOUNT / T3.1。基线为本地集成 `d206a65`；本实现未推送、未部署、未采集或写入生产，也未回填任何历史月底资格。2026-10-27的当前资料不构成2026-10月末事实。

## 已实现合同

- 账期自2026-10起按Asia/Shanghai月底最后完整成功采集冻结。候选采集必须在月末自然日开始、截止前完成，开始及完成均在截止前两小时内；最新尝试失败、不完整、跨截止或仍运行均阻断。冻结只能在该月结束后产生，保留真实采集开始/完成时间；不是声称精确0点的源状态。
- 同一原始记录必须明确为“子机构门店号”或“子机构区域号”，并且“抖音号绑定状态=认证成功”。认证信息文本不限制。个人号/总部垂直号排除；未知类型、未知状态、数字码无正式映射时失败关闭，不能跨行拼字段。
- `account_qualification_snapshot`按规范源记录内容SHA256去重；`account_qualification_observation`每次记录run/start/end/完整性/错误。采集启动用短独立事务提交running，成功snapshot及terminal observation随原采集主事务原子提交。抓取失败独立记录failed；被杀或主事务回滚保留running，不能用成功任务回执替代来源。
- `account_qualification_version`每账期唯一，引用实际observation、内容hash及policy。PostgreSQL和SQLite迁移保护snapshot/version不可变，observation仅允许running到terminal的一次转换。来源及费用provenance非空时拒绝downgrade；仅完全空的新结构可回退，保存旧费用来源触发器。
- 复用原30分钟维度采集路径，未另建生产调度。月结预检、watermark、任务metadata、月份重算和fee input_fingerprint引用冻结资格版本。冻结不依赖fee数量，避免资格/费用循环。全月结果存在但仍有未pin资格的当前结果时，预检不得放行。
- 销售归属与月底资格分开：新资格不使用昵称，不把短抖音号当UID，不用月底POI改写销售店。首次/迟到结果仍需原销售时归属证据。已有合格结果同次核销重算复用已建立的销售店依据，后来当前绑定状态不得改变旧资格。独立历史归属裁决保留优先级。
- 仅在已独立验证精确UID、完整销售覆盖区间和唯一门店时，排除不同账号的明确个人号昵称别名；未知类型、同ID反证及真实多店冲突继续阻断。8/9账期和独立打榜规则不变；核销月及费率匹配日仍由原有效核销决定。
- 版本表INSERT才触发分析source counter；snapshot/observation的半小时写入不引发分析重发。分析模块依赖清单由主集成线程同步，不改独立排名资格表。

## 完整性证据及真实来源边界

单独解析一个XLSX仅能证明文件读取完整、字段合同存在及无重复身份，不能证明后台导出未被筛选或截断。因此自动导出后必须以可比、未带筛选的后台完整列表总数、所有分页、无重复及账号/短抖音号身份多重集交叉核验。proof保留文件hash、实际行数、佐证total/page_count、身份集合hash及是否匹配；后台数字类型/状态只可参与完整性身份核对，不被翻译成资格。

若列表是另一来源scope、只有子机构子集、带筛选、缺页/重复、总数变化或与导出身份集合不一致，不标qualification complete。缺独立佐证的手工workbook同样不能自动冻结资格。旧raw采集可保留，但qualification observation为failed，月底月结暂停。这里没有硬编码3095/3096/1163等实时行数，也不拿累计raw行数当一次采集全集。

**尚未验证生产可用性**：主线程当前只读取回的字段分布说明历史workbook确有中文类型/状态，不能证明新proof采集路径已运行。后台API若只覆盖另一scope，当前全量身份校验会安全阻断；需要实际导出任务响应的正式total/scope合同或可比全列表证据后运行验收，不能为了通过而猜数字映射、忽略缺失身份或将API子集冒充全集。完整性proof实际生产回收、10月底真实冻结及生产月结仍是独立验收项。

## 验证证据

全部为合成数据或明确localhost、数据库名含test的隔离PostgreSQL schema。测试连接串仅从本地忽略文件读取，不写入本记录。

| 命令/检查 | 结果 |
|---|---|
| suite lock / validate-global-files / route-check | 2.0.1锁有效；0错误/警告；S4可进入 |
| 主集成计划verify-task-context T3.1及env-check | canExecute=true，envReady=true；主线程已确认s4_pre_coding_plan_consistency_check通过 |
| `python -m pytest tests/test_data_settlement.py -q` | 192 passed；保留旧金额、退款、撤核、锁账、发票与PR65销售区间断言；仅3处10月重核销场景显式补合成冻结资格 |
| 新资格、真实PG、后台导出/解析/登录恢复、月结集成定向组 | 最终合并复跑63 passed；其后追加unknown/真实多店别名反证两项，资格专项再跑32 passed |
| 新资格+月结规划/告警+维度复用定向组 | 54 passed |
| 历史归属、月结集成、调度、维度、职人采集扩展组 | 初次95 passed/1个旧迁移回退期望失败；空表精确downgrade修复后专项通过，扩展复跑121 passed |
| `tests/test_account_qualification_postgres.py`（localhost真实PG） | 1 passed：base→0066完整迁移、4线程同月冻结同一version、版本counter仅+1、UPDATE/DELETE/TRUNCATE保护、失败采集持久审计、主事务回滚不留下成功证据、已用证据downgrade拒绝 |
| `git diff --check`、相关模块compileall | 通过 |

新测试覆盖同记录/认证信息自由文本、未知数字、个人冲突、ID命名空间、hash去重、月底两小时/跨截止/10月27日/提前冻结、失败/运行中/次月补证拒绝、重复页/过滤子集、独立身份总数佐证、跨月核销、迟到当前变更不改旧资格、旧月份结果保护、精确UID个人别名与禁止月底POI猜销售店、watermark全量pin以及资格冻结不依赖费用。

## 迁移、容量及foundation待改请求

0066只新增空的三张证据表及费用结果可空外键，不回填8/9或已确认账务。snapshot只按内容变化存储完整规范源，重复采集仅增一条小observation；冻结来源长期保留，未提供自动删除审计证据的任务。运行失败/无变化同样保留观察记录；生产部署仍须按仓库磁盘/备份门禁检查实际空间。

| ID | 来源 | 分类/严重度 | 待改内容 | 目标及证据 | 状态 |
|---|---|---|---|---|---|
| S4-FCR-ACCOUNT-MONTHEND | T3.1 / 104-O27-ACCOUNT | GAP / 阻断业务合同同步 | 账号观察、内容去重、冻结版本、费用资格外键；上海月末最后完整采集/失败暂停及2h运行门禁；原销售归属和核销费率日期分离 | `docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md` §1及新增资格schema；`apps/worker/account_qualification.py`、`models.py`、0066迁移、`settlement.py`、`month_close.py` | 待主线程汇总/上游修订 |

本子任务未编辑foundation、全局计划或生产配置。完整仓库pytest、Web build、最终目标提交CI、部署、实际浏览器来源proof及真实月末业务验收由主集成线程收口；本记录不能作为这些项目已通过的声明。
