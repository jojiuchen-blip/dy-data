# 十一月数据恢复发布记录

记录时间：2026-11-04，Asia/Shanghai。本文件依次记录PR74 / `1.6.0-rc.3`的数据恢复及PR75 / `1.6.0-rc.4`的固定快照发布；均未创建Git tag。

最新状态（20:18）：实际应用源码为 `1f02204bcbb0c68830ff8ac3a201ab864c6c8374`，20:14完成部署，20:15五模块与运行核验通过，磁盘61.43 GiB可用。下文PR74证据保留历史身份，最新PR75产物及验收在末节；商品SKU、退款口径和完整来源截止时间仍有缺口。

## PR74 源码、产物与范围

- 实际构建源码：`de230863cad8025455b71f4da0ec92379c120c1a`。
- [PR74](https://github.com/jojiuchen-blip/dy-data/pull/74) 合并到 main：`101772120447dd2ac67784b24d755db5918f47fa`。两者树完全一致：`f15686a2ddf195899bc4770393c9c374ed96f932`。
- 源码归档 SHA-256：`6192e6f70ae684fe2c3488bd84eed5ced84cef633b6fafcd833bb398cb06d303`。
- 上一运行回执源码：`9831027a151d7bc844edde2128906f148cadc1f5`；旧镜像的可复用标签未用于推断实际源码。
- 变更包含账号导出页面复用/回收、受维护影响的账号重试、重复压缩完整来源与共享读取兼容、维护审计键长度，以及相关测试。无数据库结构、依赖、Web 或业务金额口径变更。
- API、worker、publisher 协调更新；Web、proxy、browser、ops-agent、PostgreSQL 容器身份保持，Web 与 proxy 仅验证配置并重载 Nginx。

| 服务 | 实际新镜像 ID |
|---|---|
| API | `sha256:975e136f8aa68eb971fa9f36c5649a1bc88a92aa061c6c2de146dcdc42b273cc` |
| worker / publisher | `sha256:b384d3e5e4f041394a7a662535ef9576d0f3bd4b671b2fc3c03f5b51303c1b7b` |

构建使用候选 Dockerfile、锁定源码归档及既有镜像源配置；在生产主机独立候选目录顺序构建，未覆盖运行标签。实际镜像内七个修改的运行文件与候选源文件 SHA-256 一致；在无网络临时容器中完成 API 启动/鉴权冒烟并清除该临时容器。实际候选另以只读事务验证生产完整来源 114、直接来源 49 及原预算可容纳的 121,345 条分区。

## 验证

- [精确候选 CI/CD 41785324793](https://github.com/jojiuchen-blip/dy-data/actions/runs/41785324793)：completed / success。
- 全仓 pytest：5,438 passed、495 skipped，耗时 2,279.24 秒。真实 PostgreSQL 迁移、金融/维护、共享领取、重复压缩、静态发布等适用专项独立执行；新增重复压缩门禁拒绝跳过，不能用全仓跳过代替。
- CI Chromium 28 项、Nginx 导出 4 项、API 镜像 2 项、浏览器镜像 3 项通过；前端及 API/worker/browser/web 镜像构建通过。
- 最终组合本机真实 PostgreSQL 与月结专项 82 passed / 0 skipped。原外键故障先复现失败，后验证原固定任务第二次成功、旧 partial 不变、深层来源篡改拒绝及来源读取兼容。
- 旧 c112 完整本机回归的两项失败保留在开发日志；最终 Linux 全仓已验证修正候选，不改写旧结果。
- 合并后同树 main 的重复 [CI 41792089562](https://github.com/jojiuchen-blip/dy-data/actions/runs/41792089562) 于16:19报告1 failed / 5,437 passed / 495 skipped。失败为发票浏览器用例读取 `summaries[-1]` 后取空list首项；此前PG和28项Chromium专项均通过，后续镜像构建因此跳过。此运行不能标为全绿，也不覆盖部署前精确候选的成功记录；异步响应选取问题单独修复和验证。
- 后续测试专用修复 `7fe1d011` 将断言绑定到精确origin/path、GET、门店、账月、费用方向及分页参数；使用真实API空账月响应强制晚到，旧选择器确定复现IndexError，新选择器通过。最终该文件5 passed / 68.40秒，覆盖三视口、登记持久化与真实422/409/403失败保护。此测试提交不改变实际部署源码，不作为main原失败运行已通过的证据。

## 实际部署

部署运行标识：`november-de230863cad8-20261104t072539z-218551`。完成于 **2026-11-04 15:27:13+08:00**。

使用已审阅的限定应用切换脚本，持有环境发布锁；验证 CI、合并树、旧/新镜像、现有备份及容量后，等待旧 worker/publisher 正常退出。候选源码入正式目录，环境文件只更新两项镜像引用。五模块按正常预热与完整 head 检查通过后，依次切换 publisher、API 和 worker；两层代理配置验证与重载通过。

五模块预热报告 `PUBLICATION_SOURCE_BUSY`，仍有完整旧静态版本可读；未将这一结果描述成新数据生成成功。上线后八服务正常、三服务 reader 为直接深度 64 / 来源上限 1,024，真实 PG 磁盘 marker 与 scheduler 入口通过检查。公网首页 200、未登录 `/api/v1/auth/me` 401，生产 agent manifest 正确。

数据库部署前后均为 `20261027_0066`；无迁移、新整库备份、任务终态改写或业务回放。最新普通备份 `pre-migrate-20261028T095445Z.dump` 为 2,196,459,541 bytes，生产 `pg_restore --list` 通过，未进行完整恢复演练。部署后数据库文件系统总量 190,109,507,584 bytes，可用 67,091,705,856 bytes；固定余量 28,516,426,138 bytes，下一备份预留 3,294,689,312 bytes，容量门禁通过。

生产受控证据保存于部署日志目录相应运行标识内，包含实际逐服务镜像、读者散列、数据库和容量前后值。含环境备份的文件仅 root 可读，不进入仓库。

## 回退与数据恢复边界

- 旧 API `sha256:3efd17a8c19a60055f36582c21b367a0270f60573c7d30f4bb0081d86f78964f` 与旧 worker/publisher `sha256:c2489b9633678315aa09c79105f74ebb574460d9cfc6178bcb3306acd3c58ab5` 已用本次唯一标签保护。
- 原 active 与数据库形态未变时才允许退旧 reader；完整 114 来源结果发布后旧 reader 不兼容，必须保留新读取能力进行修复。不得拨回业务指针或把整库恢复描述为无损应用回退。
- 固定维护任务 `settlement-compaction-f1951620d84eae02a159da98f328cf1d` 沿原任务重试，旧 22,000 行未发布 partial 保留，原 3 次预算和默认 100,000 行上限不改；本次 CLI 显式上限为 130,000 行，写入 512 MiB、WAL 1 GiB，正常资源等待上限 900 秒。
- 账号和 11 月 2、3 日来源恢复、后续结算及五模块发布另行验收。下方按实际时间追加证据；退款单位/范围缺证继续隔离，7 月已取消的任务不重建。
- 五个模块的 `data_as_of` 仍未知，发布时间和来源计数只能证明版本与变化，不能代表业务数据已覆盖到某天。DYDATA-104 仍进行中。

后续真实数据验收在此追加，不能由本发布记录预先推定完成。

## 15:57 维护实证

原任务于15:46:07正常领取第二次尝试，于15:57:14发布成功，最终受控回执 `published_verified`。新 generation 为 `settlement-compact:5dad4bc5b4fb66fc6d8a9390443d6ee729be3a919f37d533cd0933967d19bba2`，manifest checksum 为 `ddfcc8c64c4c7c96ebb6195efae302387d5ffefd7ba81bd4165e631e36ff0ea4`；304批、121,345分区、114来源，active深度由48降为0。

CLI返回、原任务success / attempt 2/3、数据库发布事件、生成摘要及active身份一致。旧22,000分区 / 55批partial、原冻结预算均未变，五表保护摘要前后相同：

| 保护对象 | 行数 | 内容 MD5 |
|---|---:|---|
| settlement_statement | 2,164 | `acd925742396988b9628f30758c5057a` |
| settlement_statement_confirmation | 17 | `d5f6a862f1707fc1c9aba97078da669e` |
| promotion_invoice | 2 | `5e761b4047f902fe16e63ffdd3f7de89` |
| promotion_invoice_allocation | 2 | `43cb055a35f80de38d2b5781fe7adf3a` |
| invoice_record | 0 | `d41d8cd98f00b204e9800998ecf8427e` |

维护后PG文件系统可用67,087,552,512 bytes。此保护结论针对维护操作前后；后续正常日批可能依法生成新的未确认账单，需独立说明，不用该旧指纹要求所有未来业务数据静止。

15:57:19正常调度建立11月3日日批，维度采集成功并开始提交订单页。11月2日历史补采、旧账号重试及五模块新发布仍进行中。默认100,000分区门槛保持，本次130,000为已审阅的单次入口参数，不表示全局容量策略已扩容。

## 16:37 日批与账号恢复

11月3日日期任务 `date-sync-b0e711bf469c31a3c97db715187d5891` 完成全部71页：订单35、退款10、线索8、核销18。collect于16:03:35、materialize于16:29:27、settle于16:30:35分别成功提交；结算kernel明确完成，处理影响5,297条、结果明细2,266条。这些计数属于不同粒度，不作原始订单覆盖率换算。

所属范围 `range-sync-7da5b69490da9cd15b3a042ccc668afe` 的 finalize `finalize-ef52becac9d1668323613c2c69d35bad` 成功；16:32:14发布 `settlement-lineage:d6b7fb0801206519da6abb883d6e769beceaac30081bec8e6745606af168bc0f`，checksum `cc900aa13b6934a90eff0367634fdd8ce3f25807e4c311d40e2666c23f19d12c`。任务checkpoint与生成身份、持久发布事件均匹配，base为本轮新compact。

当天正常后台账号导出任务 `parent-sync-8cf4b9008749a5db22337c1a16caf27c` 于16:34:36成功，fetched=3,114，failed=0，rejected=0；upserted=7,655跨内部实体，不解释为7,655个独立账号。当天账号绑定、门店映射任务分别于16:33:29、16:34:01成功。

原账号失败任务 `parent-sync-8b81e68159e1a58fa34f0074ff94189d` 于16:37:03正常第二次尝试成功，collect_dimensions及settle均有成功提交。未重置次数、创建替代任务或手改终态。两条旧的attempt=0维度请求仍pending；当天对应维度已有成功刷新，但不能把当前数据新鲜度改写成旧请求已执行。

11月2日正常历史任务 `date-sync-e2ed380dba2e4e80592d9dd9c833433d` 于16:37:08建立；截至16:54，79页全部采集完成（订单38、退款12、线索9、核销20），正在incremental materialize，实际处理批次与心跳持续推进，无配额暂停。来源整理与结算完成前不推定历史日批已发布。

## 商品与退款的未完成边界

正常商品任务 `product-sync-scheduled-20261104163441` 于16:36:29失败，metadata错误码为 `INCOMPLETE_RESPONSE`（顶层error_code为空）。已扫描131页、观测6,470条、跳过931条；第一个10商品批次三次正常请求均有响应、返回10商品、外层结构合法，但约定字段中的SKU数量均为0。任务尚余967个商品查找，current/snapshot写入均为0，旧目录保持。

这只能证明响应未满足当前完整性合同，不能证明平台没有SKU或确定存在解析错误。代码已有从目录或原始订单精确Product→SKU映射补查的路径；缺少映射时不能猜ID、跳过该批或把诊断游标当作可恢复任务状态。未额外发起批量试探。

16:57追加只读精确核对：首批10个Product ID无重复，三次响应中的唯一身份集合均与请求完全一致；lookup_stats为product_id_requests=3、sku_requests=0、partial_responses=3。生产目录的product_id前导索引有效，10次限量等值查询均未发现精确SKU映射。该检查未扫描原始订单、未请求上游；当前目录不等于任务冻结输入，持久诊断也未保存其他响应字段结构，因此仍不能排除未解析字段，只能确认目前没有足够证据安全执行SKU补查。

退款采集页完成只证明采集进度，不代表金额单位和费用范围已获合同证明。此前11月1日1,039条退款仍受单位/范围质量门禁保护；未猜测金额单位、未直接回放业务事实，DYDATA-104继续进行中。

## 17:03 运行检查

八服务均running，具备healthcheck的六服务均healthy，全部restart=0、OOM=false。API/worker/publisher实际镜像仍与本次发布一致；公网首页200，未登录auth/me为401。现有五模块通过正常 `--check-ready`，PG文件系统可用66,043,236,352 bytes（约61.5 GiB）。新版本时效继续等待11月2日结算与发布后核对。

运维检查曾额外给该CLI设置 `default_transaction_read_only=on`，与其 `SELECT FOR SHARE` 保护性读取锁不兼容，产生SQLSTATE 25006；这不是看板缺失。复核后使用原正常CLI，并保持5秒语句及500毫秒锁超时，退出0。其他临时元数据查询均在显式READ ONLY事务内执行；未执行任何业务写入来通过可读性门禁。

## 17:16 历史缺日发布完成

11月2日的collect于16:44:30提交、materialize于17:09:35提交、settle于17:10:52提交；四个采集域均completed，79页全部保留，结算kernel明确完成，impact_count=5,885、detail_count=2,497。原范围任务为 `range-sync-224adbacaa98b280d39cb31b84751f89`，维度子任务也成功提交。

正常调度于17:15:12领取 `finalize-0e7116a117edd0aa36557c24bf017f53`；17:16:49发布 `settlement-lineage:8148043cf24985239fc903fc6e634c225c4c1d8b97d3d9f08890cd93eac57cb4`，checksum `3f47582de914f9ce87134b709ff19cc7d5afbe122f4be6af8fde967926bbd87d`。checkpoint与generation身份、持久事件均匹配，当前active指向它，base继承已发布的11月3日generation。11月3日不再是active符合后续发布顺序，不等于其结果丢失。

11月1日原成功日批保持，11月2、3日的采集—整理—结算—发布链路已核实完成；没有手工重建历史任务、修改配额或跳过门禁。上述结论仍不覆盖被隔离退款的金额口径完整性。11月4日当天尚未结束，不为追求日期最新而提前运行完整日批。

17:18看板复核时，结算和抖音榜单此前构建曾因来源变化返回 `PUBLICATION_SOURCE_CHANGED`，旧head保持；结算已自动开始新一轮构建。须继续读回成功新head，不将日批发布成功当作五模块已经刷新。

## 17:26–17:39 看板刷新与持续业务写入

结算head `69f60015123f49c096d48c29b5bd3b2b` 于17:26:24成功发布，明确引用本轮active `settlement-lineage:8148043cf24985239fc903fc6e634c225c4c1d8b97d3d9f08890cd93eac57cb4`。核销、线索、财务也已在缺日日批完成后分别发布；抖音榜单仍保留16:38成功head，后续多次构建返回 `PUBLICATION_SOURCE_CHANGED`，尚不能宣称五个模块都已接上补齐后的来源。

17:21:55至17:23:48的有界只读样本中，clue_assignment_rounds与clue_center_orders各实际更新5行，clue_follow_up_records新增5行，三个来源计数也各加5；排除纯零行语句触发的推测。按created_at索引仅取最新少量跟进记录并关联用户角色，动作来自active/store账号，包括unreachable及further_follow_up；未输出客户、门店、账号明文或跟进备注。普通到期处理不新增跟进记录，当前证据支持正常门店跟进持续改变来源。

发布层本已有REPEATABLE READ；真实PG旧测试也证明并发提交前后builder均可读到同一旧值，只是独立observer把后续变化判成构建失败。后续修复先在隔离环境验证固定快照模式：完整性/就绪/跟踪/事务保护保留，对声明关系预取ACCESS SHARE保护TRUNCATE/DDL；自身快照改变仍失败，合法外部后续提交只让完整版本立即标为stale并排下一轮。截止本节尚未部署该调整，不能把设计写成已生效。

五模块实际使用各自快照，现有data_as_of仍未知。固定数据库快照不等于所有业务事实按cutoff完整回放；预锁依赖也不自动补齐现有刷新计数依赖。后者属于独立已知边界，不以这次发布修复宣称全面解决。

## 17:59 发布修复验证进展

隔离 PostgreSQL 18 的看板宽回归226 passed / 1 skipped；唯一跳过是显式启用的20万券合成性能基准，不是功能或并发保护用例。此前核心62项零跳过；后续还新增了observer复用连接和外部修改head反例，以最终CI对应结果为准。两项独立只读审查未发现新增阻断项，覆盖声明锁的真实模型依赖、快照/事务/失败保留、显式内置builder选择以及公平调度。

17:59生产复核：八服务running，六个具有healthcheck的服务healthy，全部restart=0 / OOM=false；公网首页200、未登录auth/me 401，正常五模块check-ready退出0。实际API和worker镜像仍是本记录的de230版本；PG文件系统可用65,953,001,472 bytes，约61.4 GiB。新固定快照修复尚未部署。

另保留既有刷新跟踪边界：例如只更改settlement_statement_line的product_type且没有其他受跟踪表变化时，finance的来源指纹可能不改变。此次补齐关系锁不等于为这些旧依赖新增变化计数，未做跟踪迁移、计数重置或扩大金融口径；不得据此宣称所有历史刷新遗漏已解决。

## PR75 固定快照候选与完整验证

精确源码 `1f02204bcbb0c68830ff8ac3a201ab864c6c8374`，代码树 `9982a4b8911f86469dfd266c7fdb9a86c7a89fba`；[PR75](https://github.com/jojiuchen-blip/dy-data/pull/75) 于20:07合入main，合并提交 `ad9185ef3454134ecdff833ec5b9b5224ae05695` 与候选代码树一致。源码归档SHA-256为 `d785e39bc7a04706d78b2320c5a3beebffa54bbb0752bd345a40a96fed30b7d4`。

- 本机精确CI PostgreSQL功能集合125 passed / 0 skipped，包含15项新快照安全用例；3个既有独立规模/冻结schema诊断函数共4例明确deselect，同文件其他功能测试保留。两条工作流对JUnit非空、零跳过/失败以及9个关键函数集合做强制断言，并上传回执。
- 主线程集成生命周期36 passed；两位独立只读审查无新增阻断项。生产只读核对53个声明依赖关系均存在，无需迁移。
- [精确CI 41812438089](https://github.com/jojiuchen-blip/dy-data/actions/runs/41812438089) 于19:08 completed / success。全仓5,442 passed / 510 skipped，耗时2,216.99秒；适用PG门禁独立执行，包括静态发布125、金融/月末239、维护/共享领取155及重复压缩4项。Chromium28、Nginx4、API镜像2、浏览器镜像3项均通过，前端和四类镜像构建完成。Railway相关任务按配置跳过，不是本环境部署证据。
- 全局文件与套件门禁通过；当前T3.1三份计划一致，环境与PRD入口有效。索引仍报告43项既有链接问题，当前新增发布记录没有坏链；未宣称全仓文档链接全绿。

18:14已在独立候选目录完成实际生产目标镜像构建，沿既有Dockerfile和镜像源；API为 `sha256:ef5b9cc5883b4fdf3edbb9bd18eb4252c3d3368f115376689a79f448fd792e75`，worker/publisher为 `sha256:826c6c12cb2e4ff793a384f3244706262dfb06229dd9ca5db429b53edabd56b1`。三个发布运行文件与兼容reader的散列均与冻结源码相同；无网络临时容器的应用导入、默认启动、manifest和401鉴权检查通过，未访问生产数据库。

20:07复查生产仍为de230、八服务正常、PG磁盘可用65,889,533,952 bytes；20:08有界只读查询无running采集任务。20:09启动限定三服务切换，使用实际CI导出、main引用及原始Git commit对象校验候选与合并树，保留当前de230兼容镜像作为回退。20:10旧worker/publisher正常退出并开始预热；实际完成和新head证据另在下节登记，不以启动命令或候选构建成功代替部署成功。

## 20:14 PR75 实际部署与20:15独立读回

产品批次 `1.6.0-rc.4`，未创建tag。运行标识 `publication-1f02204bcbb0-20261104t120918z-635506`；20:14:28.252211完成限定三服务切换，实际源码和API/worker镜像与上节候选一致。其余五个服务的容器身份与镜像保持，Web及proxy只执行Nginx配置检查和重载。数据库前后均为 `20261027_0066`，未迁移、生成整库备份、重试维护、重跑采集或更改任务终态；既有源码staging按规则保留一份previous源码。

五模块正常预热均退出0。抖音榜单、结算、财务有独立的新head证据；核销和线索复用原完整版本，不能描述成五模块都新建了数据。20:15有界只读核对结果：

| 模块 | 完整head | 发布时间（+08:00） | 本次预热 |
|---|---|---|---|
| douyin-ranking | `74c35638e1b9464688e42e2df2423f66` | 20:11:58.563817 | 新版本 |
| sales | `c37b01b376794a3aa16d3a01b3065917` | 19:39:43.264491 | 来源未变，复用 |
| clue-overview | `aae0b57ba1a74b74b1f06d474dc5d0ea` | 20:07:18.102730 | 来源未变，复用 |
| settlement | `740740573abe4d16859eeb8c811ac757` | 20:12:58.626517 | 新版本 |
| finance | `dc1ed14bc01144a0a39ebfa0bb37ec19` | 20:13:11.755931 | 新版本 |

五个head及各模块最新尝试均为success，无最新错误；正常check-ready退出0。结算新head明确引用恢复后的active generation `settlement-lineage:8148043cf24985239fc903fc6e634c225c4c1d8b97d3d9f08890cd93eac57cb4`；应用部署未修改结算active身份。

本次生产预热的新版本均记录 `source_advanced_during_build=false`；固定快照遇并发提交后标为stale的行为由真实PG门禁证明，本次生产没有人为写业务记录制造并发。五模块data_as_of仍为空，发布时间不代表完整业务覆盖截止时间；未在这轮重新测量登录用户页面延迟。

20:15独立核对实际镜像、worker运行文件散列和服务状态：八服务running，六个有healthcheck的服务healthy，全部restart=0 / OOM=false；公网首页200，未登录auth/me 401。PG文件系统可用65,955,143,680 bytes（61.43 GiB），固定余量28,516,426,138 bytes及下一备份预留3,294,689,312 bytes均满足；现有普通备份仍是已验证的2026-10-28副本，未声称做过完整恢复演练。

原部署回执保持；同一受控运行目录追加 `post-deploy-verification.json`，last-deploy关联该证据并标为 `deployed_publication_verified_business_acceptance_pending`。这表示应用及静态发布核验通过，不代表商品SKU、退款经济口径或104全部业务验收通过。后续本节文档提交只补录事实，不替换实际应用源码SHA。
