> 2026-10-26 最新：用户授权完成 D1–D7 核查、修复通用缺陷并统一交接 Linear。当前 S4 / T3.1 保持进行中；本轮基于 6ac6e440，集成负责人为当前 Codex。归属诊断、精确职人 UID 与历史区间兜底、月结阻断计数修复已实现，真实来源只读核查及回放成果见 [验证记录](../../verification/dydata-104-data-rootcause-oct26.md)。商品类型与上月默认另见 [PR63](https://github.com/jojiuchen-blip/dy-data/pull/63)。生产未部署、未补录暂停券组、未改确认账务；历史日期/编号桥及账单更正仍分别验收。下方旧状态按日期保留。

# T3.1 静态首版发布与生产业务验收

## 2026-10-26 当前执行：商品类型与默认账期

【用户确认】数据核查由协作者处理，本会话实施 DYDATA-104 已登记的三个功能。用户本轮明确同意开发，沿用 T3.1，不新增业务决策或恢复暂停的账务操作。基线为 `6ac6e44035d659d87343369dc89380417ec83dd7`；上游收集 2026-10-26，slug=dy-data、canProceed=true，大文件按相关章节读取。

| Requirement ID | 核心逻辑 / 完成标准 | Verification Method |
|---|---|---|
| 104-TYPE-01 | 后台、全国门店月榜、单店结算、订单明细、核销与线索按真实 product_type 配置和筛选；有效类型单独构成分类完整。列表、汇总、分页、下钻及导出一致，旧 scope 参数不产生隐藏过滤。 | 至少两个真实类型和全部；同类型跨 scope 不漏行、不重复；单条/批量/导入/导出及权限回归。 |
| 104-TYPE-02 | 原正式 scope 为精诚养车的全部 SKU（包括已有其他类型）转为精诚养车类型，输出精确变更前后清单；持续同步保持分类，内部 scope 不清空。 | 精确代码识别、预演/应用/回读/幂等/冲突与回滚；费率及受保护财务快照不变；未知类型准确报告。 |
| 104-MONTH-01 | 订单分佣各无显式账期入口默认 Asia/Shanghai 上一完整自然月，显式选择/深链和下钻返回保持；旧本月缓存不得覆盖菜单入口。 | 10→9、1→上年12、时区月界、切月/分页/导出；未发布/处理中/失败/无权限/真实零状态。 |

**保护边界**：独立抖音打榜 `DouyinRankingPage.tsx` / `DouyinRankingExportDialog.tsx` 保留全部/精诚养车/比亚迪本品的 scope 语义与商品集合。分类只改商品档案，不重写历史费用、账单行键、确认及发票，不改费率、实收或账期。GET/筛选/导出只读，分析更新走独立发布 worker，新增依赖同步失效跟踪。

**增量 PRD 双链·读**：本票 2026-10-26 最新正文及更正优先；`docs/prd/foundation/foundation-api-dy-data/sku-fee-admin.md`、`docs/prd/foundation/foundation-schema-dy-data/product-rule-source.md`、`docs/api/dashboard-publications.md`。旧文档 scope/type 配对和下架分类冲突记录 foundation 待改请求，不擅自改历史事实。

**增量核心文件**：`apps/web/src/pages/AdminProductTypeVisibilityPage.tsx`、`AdminSkuRulesPage.tsx`、`StoreRankingPage.tsx`、`StoreSettlementPage.tsx`、`OrderDetailsPage.tsx`、`SalesDashboardPage.tsx`、`ClueCenterPage.tsx`、`apps/api/dy_api/routes/fee_admin.py`、`routes/dashboard.py`、`routes/meta.py`、`dashboard_publications/`、`src/dy_data/` 商品分类服务及对应测试；实际写集由影响调查收窄。

**分工与当前非目标**：Codex 负责功能集成；独立工作树分别承接管理/同步、报表后端、前端。协作者继续数据核查；本轮不补录 22 券、不执行旧账务修复、不重跑历史月结、不登记发票。旧段落保留历史，不构成恢复授权。

**Evidence / Failure Handling**：验证写入 `docs/verification/dydata-104-product-types.md`；按提交区分实现、测试、CI、发布、实际分类转换和业务验收。未验证目标环境不宣称生产完成；转换预演出现范围/并发冲突则停止应用，历史事实异常不得靠重算消除。

**2026-10-26 集成进展**：三个功能已实现，实际PG覆盖59项通过/1项显式规模测试跳过；前端发布浏览器56项、导入归一预览3项及真实API月度9项通过，主整合构建通过。已补受限类型元数据和仅存历史账单行的类型选择；完整扫描/CI正在收口。当前目录与财务快照的时间语义见现行API合同，foundation差异记S4-FCR-004。未生产发布、预演或应用分类转换，不改变整体任务的进行中状态。

## 2026-10-23 已授权范围增量

用户阅读三组新增需求及实施顺序后明确同意开始。承接 DYDATA-104 正文 2026-10-23 增补，覆盖旧的“八月不处理”边界；确认、开票、锁账、权限及恢复预算保护继续有效。当前 Codex 为唯一集成负责人，基线为合入 PR61 的 `ca61eff`。上游收集于2026-10-23运行，slug=dy-data，canProceed=true；大文件按相关章节读取。

- 商品规则：读取指定附件全部相关行，产品线映射产品类型，生成新增/一致/冲突清单。复用商品分类和双费率入口；核对生效日、资格和受保护月份，不猜测或直接覆盖历史版本。
- 数据：核对8月31天、9月30天有效发布；修复原始pending-root在采集成功、finalize耗尽后的恢复资格。补采与重算分开，保留原root、次数、幂等和取消/暂停。九月2/2已用额度不绕过。按月对账总额、券/订单、退款和分币差异；八月未开票与累计应开票不作为九月当期基准。
- 页面与发票：月榜固定月度并移除统计方式、清理旧URL；开票页按确认账单展示默认6%含税拆分。去掉购买方、税率、不含税额、税额和价税合计人工输入，服务端派生金额；号码校验为20位ASCII数字。保留归属、状态、版本、重复登记、幂等及审计，不宣称税务验真，不实际登记生产发票。

**增量 PRD 双链·读**：`docs/prd/subprd/04-subprd-invoice-registration.md`、`docs/prd/foundation/foundation-api-dy-data/sku-fee-admin.md`、`docs/prd/foundation/foundation-api-dy-data/billing-invoice.md`。最新用户确认及Linear增补对明确冲突项优先；旧契约差异记录foundation待改请求。

**增量核心文件**：`apps/worker/day_recovery.py`、`apps/api/dy_api/routes/dashboard.py`、`apps/api/dy_api/routes/fee_admin.py`、`apps/web/src/pages/StoreRankingPage.tsx`、`apps/web/src/pages/StoreInvoicePage.tsx`、`apps/web/src/types/dashboard.ts`、相关pytest/浏览器测试、受控运维及对账脚本。

**分工**：主线程负责规则、对账、部署和计划；独立工作树分别负责恢复入口、发票后端、前端及各自测试。子任务不修改父范围或生产。

**增量完成标准**：23个附件SKU逐条映射，冲突可解释；两月发布、费用/账单/页面/导出与基准差异分别有证据；恢复保护回归通过；发票正常/非法号码/无权限/跨店/过期账单/重复提交/失败回滚及6%分币计算通过真实路由测试；真实页面、最终CI及PG验证通过，发布后回读。资源、来源或保护事实差异未解释时停止对应写入，不放宽门禁。

**Evidence**：`docs/verification/dydata-104-oct23.md` 脱敏记录；原始材料仅保存在忽略目录。状态仍为进行中，未宣称配置、重算或部署完成。

## 任务来源

- [主计划](main-delivery-plan-dydata-104-followthrough.md) / [任务看板](task-kanban-dydata-104-followthrough.md)
- [DYDATA-104](https://linear.app/keith-lim/issue/DYDATA-104)

### T3.1 静态首版发布与生产业务验收

**Requirement ID**：DYDATA-104 F / 全项

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` 全局规则
- `docs/prd/subprd/02-subprd-store-settlement.md` §3–4
- `docs/prd/subprd/03-subprd-order-fee-details.md` 筛选与导出
- `docs/prd/subprd/05-subprd-finance-promotion.md` §3
- `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md` 账单/财务契约
- `docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md` 费用、调整与冻结来源
- `docs/api/dashboard-publications.md` 不可变发布与读取

**核心逻辑**：代码合并与生产发布分别验收。最终提交完整 CI、真实 PG 门禁和前端构建通过后，核对实际生产版本及磁盘峰值预算，再走备份、迁移、五模块完整首版和 API 切换流程。首版失败保留旧版，不跳过来源与后处理门禁。保护原工作区未提交改动，不自动确认/开票/付款，不删除核销表现模块。

2026-10-20 用户调整优先级：历史恢复暂缓。构建时冻结财务/结算各月日水位完整性，读端只读取固定发布版本的状态；不完整月及包含该月的累计返回明确未就绪，避免正常零金额及不完整导出。状态变化纳入发布指纹，不能依赖业务表 DML 才恢复。已保护历史账单仍按原操作资格读取，生成新账单继续遵守原门禁。另修复线索读取原始平台售后 refund_type 时把发起来源误当全额退款的旁路。

2026-10-20 首次发布实测：抖音榜单构建约809秒，期间正常线索跟进变更导致来源指纹检查拒绝发布。T3.1包含这一发布阻断的最小性能修复：核销聚合先限定本批订单券，再按订单/POI汇总并使用已加载的唯一门店映射；重复同店、歧义POI、同店多POI、撤销与cutoff口径保持。不得修改来源指纹或完整性门禁，不新增索引/迁移；通过专项、真实PG、最终CI和重新预热证明结果，不能以EXPLAIN估计代替耗时验证。

2026-10-20 后续用户明确不再等待7/24补采：允许通过现有取消语义结束该闲置历史任务的重试，必须保留部分已写事实、检查点、错误与操作审计，不能伪造成功或完整性。发布当前已知数据时保留未知来源时间及未完成正式账期保护；不修改来源门禁。若优化后仍遇来源变化，只重试失败模块，最多三次；必要时安排短暂业务写入静默窗口，保持失败回滚和五模块首版检查。

2026-10-20 18:22 再次预热在240秒上限停止，实际生产EXPLAIN确认轮次查询的SKU归属表达式在每500条页面重复创建三个全来源哈希子计划；此前合成规模测试没有覆盖真实原始线索体量。T3.1继续以最小批次归属查询替换该重复扫描，限定本批order_ids并保留三来源并集、SKU规则、first_at与原计分口径。无新迁移、不放宽超时或来源保护；专项等价性、真实PG执行计划和最终CI通过后复用本轮有效发布检查点继续部署。

2026-10-20 19:53 五模块首版成功，随后API默认启动因镜像未包含`apps.ops_agent`失败，旧服务和采集已恢复。T3.1补齐API运行依赖，并将真实构建镜像的导入、默认CMD启动及HTTP响应纳入CI；仅构建成功不作为运行验收。再次切换前保留原镜像、有效备份及加法迁移检查点，失败只恢复运行服务和镜像配置，不能用旧dump覆盖期间新增业务事实。

2026-10-20 20:46 PR57服务健康通过后，真实页面发现榜单Decimal序列化成字符串并触发前端白屏。已恢复原API/web，新后台服务及静态版本保留。PR58只将榜单计数归一为整数后沿用比例算法，补真实PG→HTTP→现有前端格式化验证及五模块类型检查。schema、builder与来源规则不变时，核对当前五head/readiness及已发布数据的数值契约后只替换API/web；不重复迁移、物化或停止采集。回退必须验证实际镜像、环境pin、代理HTTP及其余后台服务身份，服务健康不替代真实浏览器验收。

**核心文件**：
- `apps/api/dy_api/dashboard_publications/finance.py`
- `apps/api/dy_api/dashboard_publications/period_readiness.py`
- `apps/web/src/pages/StoreRankingPage.tsx`
- `apps/web/src/pages/StoreSettlementPage.tsx`
- `deploy/tencent/deploy.sh`
- `apps/api/Dockerfile`
- `.github/workflows/ci-cd.yml`
- `apps/api/dy_api/dashboard_publications/ranking_build.py`
- `apps/api/dy_api/dashboard_publications/ranking_read.py`
- `docs/api/dashboard-publications.md`
- `docs/rules/storage-management.md`
- `docs/devlog/20261020_dydata-104-followthrough.md`
- `tests/`

**完成标准**：五模块同版本筛选和导出、真实更新时间、冷/热耗时及内存有可复核记录；九月金额逐层一致、8/9/10 月切换及下载内容正确；实际部署源码/镜像、服务健康、磁盘余量及新错误均核对。未满足生产业务验收不得关闭 104 或把源问题写成合法零。

**Verification Method**：完整 CI、真实 PG、真实浏览器下载/权限与筛选测试、生产有界只读 smoke 和备份/磁盘容量记录。

**Evidence**：`docs/devlog/20261020_dydata-104-followthrough.md`，对应最终 CI 与脱敏运行记录。

**Failure Handling**：证据不符、资源/配额不足或保护指纹变化时停止相关写入；保留真实状态并记录具体阻碍，不绕过门禁。未满足验收不标记完成。

**完成收尾：状态同步**：核对验证与 foundation 漂移；新增契约缺口只追加待改请求。由 ai-project-manager 调度 delivery-planner 同步主计划、看板、子计划与执行驾驶舱，重跑一致性和 route-check；生产结果没有实证时不能写完成。

**Owner**：Codex 执行与独立复核 → 用户业务验收

**前置**：T0.1、T0.2、T1.1 代码验证；未完成账期展示保护。T2.1 后续验收不阻碍本次受保护部署。

**部署验收（2026-10-20 21:38）**：5da13df1已于21:26部署，冻结提交完整CI成功，真实页面白屏修复。榜单刷新1.897秒、层级筛选0.727秒，核销月份0.607秒、线索状态0.335秒；三个榜单Excel工作表各1596条且版本一致。生产API峰值197.1MiB/768MiB、无OOM，磁盘23.25GiB/19.701%。结算8/9/10月及财务九月明确未完成，金额和导出保护有效；没有宣称核销全年稳定秒内或历史金额对账完成。详见开发日志21:38节及生产验收收据。

**状态**：进行中

**九月页面修复验收（2026-10-21 12:49）**：PR59已合并，生产 `f66cdd5d` 于12:47仅切换API/web；完整CI4098通过/284跳过，真实PG静态发布61通过/4跳过，新增HTTP数字/null及5项真实浏览器回归通过。生产九月月榜452店、推广费10,032.68元；单店推广/管理费、正式待确认账单正常显示，累计明确暂不可用，八月继续拒绝，切回九月恢复，控制台错误为空。全部服务健康，五个后台容器身份保持，API峰值179.6MiB/768MiB，0重启/0 OOM，磁盘18.745%/22.12GiB。`/opt/dy-dashboard/logs/dydata104-monthly-browser-acceptance-20261021.json`与last-deploy记录通过；本页面缺陷已修复，整体用户业务验收仍保持进行中。

2026-10-21 用户截图验收发现九月月榜仍被八月阻断，并明确要求修复。已交叉验证九月 30/30、452 张账单、月费金额一致；缺陷是混合月/累计读端无条件检查历史前缀。当前 T3.1 增量验收：MONTHLY + PROMOTION_FEE_MONTH 和单店九月当月读取成功；累计字段及对应兼容别名为 null，并附 `period_availability`（HTTP 为 `periodAvailability`），包含 `monthly_ready`、`cumulative_ready`、`incomplete_months`。同版本累计请求/累计排序及含累计导出继续拒绝；八月和缺失元数据继续保护，完整前缀及合法零值保持原行为。前端明确显示累计未完整，不能用 0 回填；真实 PG→HTTP 数字/null、权限隔离与生产两页面验证后才记修复完成。

部署与技术验收已完成；2026-10-21 T2.1 已完成九月恢复和金额交叉核验，转待验收。当前承接整体用户业务验收，包含八月的累计查询继续受保护，不关闭104。详见[九月恢复核验记录](../../ops/dydata-104-september-recovery-20261021.md)。

