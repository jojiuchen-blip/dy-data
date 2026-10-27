# DYDATA-104：10月起月末账号资格实现与验证

本记录仅对应104-O27-ACCOUNT / T3.1。基线为本地集成 `d206a65`；本实现未推送、未部署、未采集或写入生产，也未回填任何历史月底资格。2026-10-27的当前资料不构成2026-10月末事实。

## 已实现合同

- 账期自2026-10起按Asia/Shanghai月底最后完整成功采集冻结。候选采集必须在月末自然日开始、截止前完成，开始及完成均在截止前两小时内；最新尝试失败、不完整、跨截止或仍运行均阻断。冻结只能在该月结束后产生，保留真实采集开始/完成时间；不是声称精确0点的源状态。
- 同一原始记录必须明确为“子机构门店号”或“子机构区域号”，并且“抖音号绑定状态=认证成功”。认证信息文本不限制。正式中文列中其他明确文本逐行不合格并保留原因，不拖垮完整合格集合；数字码无正式映射、缺字段或真实身份冲突时整批失败关闭，不能跨行拼字段。
- `account_qualification_snapshot`按规范源记录内容SHA256去重；自动永久资格采集仅在月末最后2小时启动，observation记录run/start/end/完整性/错误。窗口内启动用短独立事务提交running，成功snapshot及terminal observation随原采集主事务原子提交。抓取失败独立记录failed；被杀或主事务回滚保留running，不能用成功任务回执替代来源。平时仍正常导出校验/upsert，小型proof/hash走普通运行日志，不增无用途永久资格快照。
- `account_qualification_version`每账期唯一，引用实际observation、内容hash及policy。PostgreSQL和SQLite迁移保护snapshot/version不可变，observation仅允许running到terminal的一次转换。来源及费用provenance非空时拒绝downgrade；仅完全空的新结构可回退，保存旧费用来源触发器。
- 复用原30分钟维度采集路径，未另建生产调度。月结预检、watermark、任务metadata、月份重算和fee input_fingerprint引用冻结资格版本。冻结不依赖fee数量，避免资格/费用循环。全月结果存在但仍有未pin资格的当前结果时，预检不得放行。
- 销售归属与月底资格分开：新资格不使用昵称，不把短抖音号当UID，不用月底POI改写销售店。首次/迟到结果仍需原销售时归属证据。已有合格结果同次核销重算复用已建立的销售店依据，后来当前绑定状态不得改变旧资格。独立历史归属裁决保留优先级。
- 仅在已独立验证精确UID、完整销售覆盖区间和唯一门店时，排除不同账号的明确个人号昵称别名；未知类型、同ID反证及真实多店冲突继续阻断。8/9账期和独立打榜规则不变；核销月及费率匹配日仍由原有效核销决定。
- 版本表INSERT才触发分析source counter；snapshot/observation的半小时写入不引发分析重发。分析模块依赖清单由主集成线程同步，不改独立排名资格表。

## 完整性证据及真实来源边界

单独解析一个XLSX仅能证明文件读取完整、字段合同存在及无重复身份，不能证明后台导出未被筛选或截断。主线程已实际捕获正式协议：精确POST `/life/gate/v3/collaborator/download_bc/start/`、空JSON对象、仅商户上下文`root_life_account_id` query；start成功生成download_id；mget同ID、download_type=120、status=2且带生成开始/完成时间及file_url。新代码以本次启动任务及匹配的完成元数据下载文件，保存任务证明、真实本地观察区间、文件名/字节数/hash和全部解析行数；签名URL仅在内存使用，不写proof或日志。

额外筛选query/非空body、不同任务ID、重复或矛盾任务元数据、错误导出类型、时间/文件名不符、字节hash不符、截断或缺字段不能标qualification complete。源工作簿在本次私有临时目录读取后清理，完整规范源行及proof保留于DB；不再按mtime从下载目录捡旧文件。parser无条件reset_dimensions并读至XML末尾，防官方A1:J1类错误dimension把全部数据截成一行。后台bind/list只覆盖另一视图scope，不能拿它的Total强比workbook，也不用于资格类型映射；原数字API fallback缺中文合同仍不能产生资格快照。手工workbook无精确任务证明也不自动冻结。

主线程实际probe已获得237175字节、3096行、1151条合格源记录（1146门店+5区域）的任务/文件闭环；这是当前源协议证据，不是本分支新代码已生产运行，更不是10月末事实。没有硬编码实时行数。新代码实际采集proof、10月底冻结及生产月结仍分别验收。

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

0066只新增空的三张证据表及费用结果可空外键，不回填8/9或已确认账务。自动入口仅在上海月末22:00（含）至次月0点（不含）启动永久资格采集，最多8次/月（4个半小时正常槽、4次合计补尝试），另最多1条确定ID的预算耗尽失败marker。advisory事务锁串行化计数；预算耗尽先提交该marker再停止本月自动导出，后续重试不增marker/快照，月结安全暂停。每份规范snapshot最大8MiB，超限仅留失败证明，不截断、不存大内容。相同hash跨观察/跨月份复用；新内容最多8份/月，正常采集48次/年，自动规范内容上限8×8MiB×12=768MiB/年（不含索引、WAL和备份开销）。平时正常采集只走原始数据upsert与普通日志，小proof/hash由已有日志保留规则管理。显式start/complete函数保留给受控操作和合成测试，不作为自动常驻旁路。既冻来源不删除；生产部署仍按磁盘/备份门禁检查实际空间。

| ID | 来源 | 分类/严重度 | 待改内容 | 目标及证据 | 状态 |
|---|---|---|---|---|---|
| S4-FCR-ACCOUNT-MONTHEND | T3.1 / 104-O27-ACCOUNT | GAP / 阻断业务合同同步 | 账号观察、内容去重、冻结版本、费用资格外键；上海月末最后完整采集/失败暂停及2h运行门禁；原销售归属和核销费率日期分离 | `docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md` §1及新增资格schema；`apps/worker/account_qualification.py`、`models.py`、0066迁移、`settlement.py`、`month_close.py` | 待主线程汇总/上游修订 |

本子任务未编辑foundation、全局计划或生产配置。完整仓库pytest、Web build、最终目标提交CI、部署、实际浏览器来源proof及真实月末业务验收由主集成线程收口；本记录不能作为这些项目已通过的声明。

## 2026-10-27审查修正：负例标签与身份桥证据

主线程生产只读反馈出现“绑定已拒绝”“未知状态”“子机构号”等明确中文值。它们不是正向允许条件，不应被误当成整个中文来源合同不存在。规范化policy升级为`settlement-monthend-cn-v2`：每行保留`qualification_status`和`reason_codes`，非两类型写`account_type_not_eligible`，非认证成功写`certification_not_successful`。明确不合格行无账号ID再记`nonqualifying_record_without_account_id`，可保留多个无法识别但明确不合格的源行；可能合格行无ID、字段矛盾、可识别身份重复/冲突仍阻断。parser保留每一非空源行，不因个人行无ID而先丢行、误报文件不完整。

数字API、缺列/缺值仍不能按文本负例放宽。历史v1证据继续按其原内容与policy校验，冻结引用实际snapshot的policy，不能把v1来源重新标为v2或改写既冻月份。

跨UID身份桥尚未实施、不得宣称10月多数订单已解决。代码证据是`apps/worker/collectors/orders.py`将`owner_account_id`取自`owner_account_id`或`sale_info.transfer_uid`等，而职人采集`apps/worker/collectors/aweme_bindings.py`同一来源行含`craftsman_uid`和`aweme_short_id`；其规范化`douyin_id`可取该短号。后台workbook的“抖音id”与所属账户id是另一组命名空间。潜在跨UID桥必须是：精确职人UID → 同条正式OpenAPI记录的短抖音号 → 冻结workbook同短号的唯一合格所属账户ID。不能用昵称、认证信息、数字类型码、POI或纯粹相等的不同命名空间数值代替。新代码识别collector优先选择的`transfer_uid`来源，不把其文本恰等后台account_id视为跨namespace证明；无候选关联记`qualification_identity_unresolved`，多个账户冲突记`qualification_identity_ambiguous`，源所选字段与normalized值矛盾记`qualification_identity_source_conflict`，只有可证身份匹配到不合格源行才记`account_not_qualified_in_frozen_month`。

已按主线程核实的[官方订单查询字段定义](https://partner.open-douyin.com/docs/resource/zh-CN/local-life/develop/OpenAPI/general-capabilities/order.query/query)实现**有来源的短抖音号直接匹配**：`transfer_douyin_uid`定义为订单归属人的抖音号，`transfer_uid`则为加密且非抖音UID的归属人uid。只有raw的`sale_info.transfer_douyin_uid`或`order_sale_info.transfer_douyin_uid`确实按collector优先级被选择、且与normalized列一致时，才查冻结workbook的`douyin_id`。通用顶层`owner_douyin_uid`不因此整体重解释为短号，低优先级字段不能偷偷补匹配。一个明确合格关系不会被个人负例污染；多个合格账户、明确backend账号与短号指向不同账户、来源值不一致仍阻断。这是已定义命名空间内匹配，未启用上文缺证跨UID桥，实际覆盖须独立回收。

本地忽略查询脚本`.tmp/inspect_account_identity_bridge.py`供主线程在API现有环境执行；当前协议`account-identity-bridge-readonly-v2`。它强制PostgreSQL REPEATABLE READ / READ ONLY、45秒语句和2秒锁超时，仅输出来源run、字段键/类型和聚合覆盖/冲突计数，不输出账号/UID/昵称值或连接串。可显式选workbook/OpenAPI source_run，统计最新保留源行中一对一/一对多的UID→短号→合格账户、10月有任意核销来源的订单直接等值与潜在额外覆盖、后台`integration_content.user_info`实际字段及等值候选。v2用materialized期内券/订单及去重JOIN消除循环相关EXISTS，保留聚合stage、safe SQLSTATE和超时分类，不加长45秒上限。它不采集、不建任务、不更新来源，不把保留raw行称为完整快照，也不把字段相等本身称为正式UID定义。合成隔离PG查询验证1 passed；主线程生产v2查询也已成功，源数据保留在忽略目录，未commit。

生产只读聚合在当前保留source_run中看到3096条workbook、1151个合格所属账户、1926条OpenAPI/1921对不同UID-短号；只有13条一对一候选桥。9695个10月有任意核销来源的订单中，3754有owner_account_id、217有owner_douyin_uid，文本直对后台ID为0，潜在职人桥只额外覆盖4个，9691未覆盖。后台user_info的user_id对订单两列均0；aweme_id对owner_douyin_uid有少量相等只能提示需查原始来源，不能把短号认成UID。这些数字是当前候选覆盖审查，不是计费范围、冻结版本或新规则可验收覆盖；尚缺正式身份关联的订单必须保持独立阻断。

若后续采用桥，资格snapshot应把双方原始记录hash、各自namespace/value、来源run/真实观察区间、完整分页证明和唯一性裁决一并纳入不可变内容hash；只存当前raw引用不够。来源必须新鲜且完整，短号对应多UID/多合格账户、缺值、字段角色不明或时间不可核验均单列阻断。`collect_aweme_bindings`当前的cursor循环退出和PhaseStats不能独立证明全批完整，桥采集须验证终止标志、重复页/身份及页链，不能复用旧成功回执冒充新桥证据。桥只决定账号资格身份，销售门店仍走独立销售时证据。

登录误报修复：新版真实业务页包含“登录人”且没有旧“抖音号明细”，不再用“登录”子串判断失效。实际login/passport路由、明确登录失效/扫码提示或真实密码登录form才可认定；优先读rendered body text，隐藏模板/JS及redirect query里的login不作为凭证。保留真正登录跳转优先于下载/API失败的处理。

本次补审验证：负例/正式export task proof/新版登录/来源短号与优先级/窗口和容量边界等相关110项通过；真实PG及月结相邻27项通过，含4线程发起12个请求仅8个自动admission、1个预算marker，原完整迁移/冻结/不可变/原子性回归保留。ignored v2只读查询合成PG再次1 passed，生产由主线程执行且成功。新自动采集代码、10月末实际冻结和多数订单身份覆盖未据此宣称生产验收完成。
