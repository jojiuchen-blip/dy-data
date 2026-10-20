# DYDATA-104 接手、稳定性与业务闭环

日期：2026-10-20。用户授权先处理远端/本地代码、按 #50 → #51 合并，再在统一 main 上继续 104；不新建 Linear。旧交接票的“原会话停止修复”仅描述交接者，不撤销本轮用户授权。原 dy-data 工作区的十项未提交/未跟踪改动保持原状。

## 接手与合并

- Linear DYDATA-104 原为 Todo / High / 未分配，无其他活跃协作者证据；10:33 经已登录浏览器改为 In Progress。连接器仍 UNAUTHORIZED，未索取凭据。截图与脱敏本地证据保存在忽略目录，不提交真实业务明细。
- PR50 新发现并修复回执错误：A、B 两次恢复后重复 A 不能返回最新 B。ce9183b1 针对原请求校验根、窗口、配置、ledger/metadata 请求键与 ordinal；冲突 409，不重新分配。定向 72 passed，主线程独立 13 项新回归通过。
- PR50 最终 CI [39358414983](https://github.com/jojiuchen-blip/dy-data/actions/runs/39358414983)：3655 passed / 189 skipped；PG 门禁、Web build、镜像构建成功，部署 skipped。10:49 合并为 aaa329f98e6d3b3a5d0e0538f24abda8cad10869；树 1985653d4dccbf9a6139cee6f18ff280d95acbbb，保留 main 的 PR52/53。
- PR51 已切 base 到 main；预计合并树与已测试 head 13d9d476 的树一致（0b5c1bd9d5f9fab9725ca047b41d6e0f021c6e4e），最终 CI 尚待记录。自动部署 TENCENT_DEPLOY_ON_PUSH=false / RAILWAY_DEPLOY_ENABLED=false。

## 当前生产证据（只读）

10:13–10:15 的查询使用 REPEATABLE READ + READ ONLY、statement_timeout=8s、lock_timeout=1s，完成后 rollback。通过 generation-aware _priority_rows_for_day/_day_state 核对九月仍 29/30，仅 9/14 failed。原根 range-sync-10562f3369ac7d31e9801d42d8db1d60 failed；ordinal1 parent pending，finalize-4de6b6930faa42691dda3d16343d86f9 failed 3/3。三次真实 traceback 均为 sparse base lineage depth 超限；未重置状态或恢复预算。

当前 active settlement lineage 为 settlement-lineage:480d281734c07ccf37461c3aff31b61799a40261d9c3f84237b16c8e660a87e7，published / depth23。另有 date-sync-e0b16c490d8ecc5a135ad6db15d8882a 运行 settle，不能将系统视为空闲。磁盘可用 21,396,967,424 B / 126,695,563,264 B（约 19.93 GiB / 16.89%）；健康检查正常，当前容器 restart0，点时 OOMKilled=false 不抹去旧事故。

API 当前镜像 823e554a8f9d、10/19 15:43 创建，768 MiB；worker 镜像 202938b5e1fb、3 GiB；browser 镜像 89e6b34cb4bc、2 GiB。API 当前 ranking_snapshots.py / ranking_lifecycle.py 哈希与 main PR53 一致（38d17e1d… / 999aba3e…），routes/dashboard.py / main.py 与 fe02e2a 一致（1c84af83… / d398a7aa…）。worker settlement_rebuild.py / settlement_compaction.py 与当前集成树一致。生产是选择性更新，不能仅用 last-deploy 或 git HEAD 推断全部源码。

## OOM 证据边界

旧诊断 artifact 39208185034 的内核日志确认 10/19 14:05:20、14:06:13、14:07:04 的 API uvicorn cgroup OOM；anon-rss 是 767424/776184/760888 **kB**，不将 kB 误写成 MiB。旧 API 容器已替换，当前 API 容器查询该窗口无日志。

补查主机 nginx access.log.1 与 proxy 容器该 6 分钟窗口，共同覆盖 173 条请求。在服务器端使用源码提取的 163 个路由模板匹配，只输出模板/方法/状态/时间及安全分页日期参数，不输出 IP、账号、订单、查询令牌、正文。

- 抖音打榜 GET 5 次 422、5 次 499、3 次 502。错误请求使用 pageSize200、9/1–10/19，按 group/service_center/district/area/store 切换；不能根据状态码反推 422 的响应详情。
- 14:05:12 / 14:06:03 / 14:06:54 打榜请求中断，随后约 8–10 秒发生已知 OOM；14:05:23 / 14:06:14 出现打榜 upstream connect failed。
- 14:07:04 来源核验 GET upstream prematurely closed connection，与第三次 OOM 同秒。该接口当前按 page_size+1（上限501行）读取；不能仅因它被中断就认定它是大内存根因。
- 关联证据支持优先测榜单读取，但无每请求 RSS 或开始事件，尚不能独立归因；PR53 内存补丁在事故后已进入当前 API，PR51 静态读取尚未部署。

## 新路径规模基线（本地，非生产 HTTP）

使用实际 API Dockerfile 构建镜像 dydata104-api-baseline:13d9d476，在本地专用 PostgreSQL 18 容器执行现有真实来源规模测试。测试容器 768 MiB、memory-swap 同为 768 MiB、2 CPU；数据库另限 1 GiB/2 CPU，无公网端口。均为合成数据。

510467 订单 / 84944 责任轮次 / 85674 线索中心订单 / 1531 门店：真实构建 77.08s，构建子进程 peak RSS 98,369,536 B；投影总量 105,668,608 B，另持久绑定 4,382,720 B。读取只访问投影，全年 report 0.772–0.836s，含筛选项 0.881–0.993s；九月 0.272–0.283s，默认赛期 0.311–0.316s。1 passed / 105.64s，容器 exit0/OOMKilled=false。未放宽秒内断言。

测试内置字段写着 unrestricted local process，但本次外层 Docker 的 2 CPU 限额有 inspect 实证，不能照抄该字段为无 CPU 限制。以上是函数/SQL 路径及构建子进程测量；没有完成 HTTP 并发、导出和 API 进程峰值验收，不能将构建 RSS 冒充 API 峰值。

## 104 已定位的代码缺口

- StoreSettlementPage 默认取版本月份首项，真实10月存在时会默认10月；需复用上海上月助手，保留显式10月可选。五个 SKU 模板/结果下载入口丢弃 Promise 错误且缺忙碌保护。
- 月结范围规则当前只匹配 exact effective_month，没有未来延续合同；不能因九月已授权就无版本地永久复制八月。需明确可审计生效/停用语义，保护历史规则和费率。
- priority 三种调度入口不一致，普通队列返回值丢弃，一轮可串行执行多个重任务；rebuild 未占 heavy_sync、使用独立锁，自动维护启用前需真正统一跨进程保护。
- compaction closure 为当前直接 base 链（到 terminal compact/legacy root），manifest 计数需去重 artifact/partition 含 tombstone；legacy_root 键可能不写新 manifest。现 summary 分页内存有界但总扫描不限，不适合每轮无条件全扫。
- 退款金额单位、经济口径、券/次数覆盖与已有财务事件覆盖仍未取得充分证据，重放和静态首版门禁继续保留。

本轮未执行生产补采、迁移、恢复代分配、范围写入、账单确认、部署或 quota/attempt 重置。正式计划基线与后续实现另追加；没有更新用户记忆文件。

## 10:57 合并基线完成

- PR #51 最终 CI 39358437442：3,855 passed / 248 skipped，真实 PostgreSQL 门禁、前端与全部镜像构建通过；部署步骤跳过。
- #50 合并 `aaa329f98e6d3b3a5d0e0538f24abda8cad10869`，#51 合并 `05a7e2455d3883d0587b3dcf8bd8f014cd7b579f`；最终树 `0b5c1bd9d5f9fab9725ca047b41d6e0f021c6e4e` 与已验证候选树一致。
- 自动部署变量均为 false。本轮合并未触发生产切换。
- 104 从合并后的 main 新建独立工作树；原工作区未提交改动保留。以下开发开始以本节为当前基线，前文“待合并”均为历史记录。

## 11:32 当前集成与复核

- 已集成共享 heavy 槽、API 请求资源观察、默认上月与五处 SKU 下载反馈、自动维护核心和可复跑 HTTP 容量脚本。仅本地代码，尚未推送或部署本轮 104 修复。
- 用户确认未来账号、渠道范围从生效月持续适用直到明确修改/停用，已追加 S4-FCR-015 与接口说明。按账号、渠道独立选择最新版本，不跳过停用、不复制每月规则，原账单保护保持。当前实现与保护回归正在隔离树收口。
- 主线程发现并修复 legacy 周期规划被积压饿死、DRAIN 放行直接重任务、直接任务定时器未推进三项调度问题。startup/run-once/poll 共用单轮预算，日期 drain 上限一条，财务检测上限一条；轻量日期规划不被重任务积压阻挡。
- 主线程独立回归：调度/采集/子进程/财务检测/月结 104 passed / 8 skipped；新增流式指纹兼容、探针与调度 43 passed；观察器+探针 33 passed；UI 真实 Chromium+FastAPI 与探针 28 passed；部署相关 49 passed。Web build 通过，现有大 bundle 提示仍在。skip 是显式 PostgreSQL 环境门禁，不能当作 PG 已通过。
- 自动维护执行器组合 365 passed / 6 skipped；独立容器 Linux + 两项真实 PG 37 passed，覆盖 49 层发布和 100100 条 manifest 截止预算。但独立代码审查复现旧 head 快照误终止新 base queued job，已要求修复并追加确定性 PG 回归，当前不能将原 17b1bfd1 判为最终可发布。
- 通用容量探针与部署接线已实现：真实 PG data_directory → 持久挂载 → 只读 marker，当前仅本地路径/配置与脚本测试，未在生产创建或挂载 marker。自动预算为保守策略值，不是生产实测容量。

### 真实 HTTP 容量证据

隔离合成数据库规模保持 510467 订单、84944 轮次、85674 中心订单和 1531 门店；setup、API、client 分容器，API 768 MiB / 2 CPU / 禁 swap，正常 cookie 鉴权，仅替换测试 session。脚本 `scripts/benchmark_dashboard_http.py` 最终报告与文件 SHA 一致，自有 schema 已清理。

- API cgroup 基线 145.33 MiB，峰值 184.66 MiB，RSS 峰值 207.03 MiB；不同指标不混用。OOMKilled=false、oom_kill=0。
- 全年列表 0.891/0.866/0.932s；全年列表加筛选项稳定轮次 1.078/1.135s；并发全年读 1.079s、九月读 0.283s、全层导出 6.763s。单独全层 XLSX 导出 7.071s，152943 B，3 sheet 各 1681 组织行，各层订单合计 510467。
- 334 条 SQL 观察中，源表读取、写入、builder 调用均为 0。401、422、410 与实际门店权限范围通过；A03 对所有初始化角色开放，不能伪造 403 场景。
- 单个全年请求 0.889s，其中 SQL 0.828s、鉴权 9ms、序列化与 JSON 编码合计不足 1ms；最慢 selected_orders 查询 0.749s。导出 SQL 4.829s，其余 Python/框架 2.241s。
- 内存与数据校验通过。这里的组合耗时是脚本串行读取筛选项和榜单的合计，不是当前页面首屏实测；当前页面只请求榜单。冷启动筛选 1.190s 的非 SQL 初始化来源未完整拆分。未复现旧 OOM，不宣称事故根因已证实；也不能将本榜单规模结果替代所有财务模块的规模验收。

### 生产只读复核 11:31–11:32

READ ONLY / REPEATABLE READ、statement_timeout 8s、lock_timeout 1s，完成后 rollback。首次查询误用了投影代次表复数名称而失败，事务回滚；按模型单数表名修正后成功，无生产写入。

- 退款日期任务真实 success；九月旧 finalize 仍 failed 3/3、原根 failed、ordinal1 pending，没有虚改任务终态。
- active 已自然推进至 published / depth24，另一个日期任务正在 settle，当前不是空闲窗口。
- 仍是 Alembic 0062，静态发布表未建立；退款金额单位不明确 1375 条、券匹配歧义 27 条仍在。本轮不绕过完整基线或执行未知金额重放。
- API、worker、ops-agent、browser、PostgreSQL healthy。根文件系统可用 21,229,232,128 B（约 19.77 GiB / 16.76%），df 使用率 83%。未执行额外清理或部署。

本轮没有修改用户记忆文件。其余源码实现未发现新 foundation 漂移；范围语义变更以 FCR-015 留待 Foundation 正文同步。

### 最终集成专项补验

- 范围规则已合入 `496b5191`；主线程独立 scope/API/billing 92 passed / 2 PG skipped。新增24项范围用例包含真实重算前后已确认账单全字段与来源指针不变；显式停用撤销未保护当前指针但保留历史金额。
- 自动维护并发修复已合入 `55c87d23`：JobRun 锁后在同事务 NOWAIT 重读 active，冲突回滚并延后。主线程对冻结树在独立 Docker/PG 执行19项真实数据库专项全部通过（42.87s），覆盖共享领取15项与维护4项，包括旧head/新job竞态和锁冲突后继续领取。
- 全仓第一次尝试在收集阶段失败：宿主机 site-packages 中第三方 `tests` 包遮蔽仓库命名空间，8个导入错误，业务测试未开始。已新建忽略的独立 `.venv`，按既有 requirements 安装后重跑，不修改测试断言或业务代码规避环境问题。

### 冻结候选 HTTP 复测与并发复核

- 候选 `55c87d23` 与实测合并节点 `7007256e` 的内容树均为 `120c22cbeedc63d0c1a67115900fdddefed33db8`。本节是包含请求观察器后的复测，前文较低峰值保留为历史结果。
- 同规模独立 HTTP 测试退出0，API限额768 MiB / 2 CPU / 禁swap，cgroup基线185.39 MiB、峰225.39 MiB，RSS峰207.74 MiB。无OOM，334条SQL中源读取、写入及builder调用均为0；内容、权限、版本校验通过，自有测试schema清理后剩余0。
- 全年列表1.140/0.884/0.858s；全年加筛选项1.464/1.185/1.081s；单独导出6.805s；并发全年/九月/导出0.977/0.213/6.773s。组合数值是脚本串行接口耗时，不能当作当前页面首屏实测；列表冷读超过1秒，仍未证明稳定秒内，不将容量通过写成性能目标全部通过。
- 报告SHA256为`854418b6670ab69f879f23c862eff01b4b5219cad5f1e054d758f403363e2be9`。44组观察器start/end配对且末尾并发计数为0；但21个业务请求模板均为unknown，已定位到依赖允许的FastAPI0.150新式`_IncludedRouter`未被识别。该观察兼容问题另作修复和真实路由回归，不能用测试专用直接注册端点替代业务include_router验证。
- 自动维护P1独立复核关闭：JobRun后锁active、NOWAIT冲突回滚、当前base queued任务保留本tick，符合发布锁顺序。复核者另跑3项竞态/receipt/stale用例通过；真实PG仍采用主线程19项实跑证据，不重复计数。

### 收尾审查修正

- `73192c22` 修复新式FastAPI路由树的观察器识别。仅读取注册元数据、缓存最多512个模板，不触发handler或改变scope。独立容器FastAPI0.150与0.136.3各40项通过，主集成环境另40项通过，覆盖真实业务include_router、嵌套prefix/mount、404/405、取消/流式/日志失败与隐私边界。全规模容量报告仍对应前一冻结候选，未将其冒充后续补丁的重测。
- 部署审查实际复现自定义bind路径中`&`被既有sed替换器展开。`2e1bb5e5`在创建marker前拒绝环境写入和解析不安全字符，并写入通用规则。主线程Windows18项通过、1项Linux专属跳过；独立Linux容器19项全部通过，无网络和生产操作。
- 独立审查另复现真实daily supervisor返回BUSY/0后，legacy入口仍运行未共享准入的商品同步。正在补齐正常商品runner的事务级heavy锁和资源/冷却检查，并让被延后的queued任务复用原身份恢复；不能仅凭BUSY全停而造成商品同步永久饥饿，也不能用一次未加锁的查询充当跨进程互斥。

### 商品同步准入修复闭环

- 已合入`9d40fc04`：正常API后台及scheduler共用的商品runner在现有单事务内取得PG共享try-lock，检查ALLOW、冷却和running writer SQL fence后才扫描来源/初始化adapter。正常领取设置heavy_sync，拒绝保留queued、attempt、metadata和cursor，后续调度复用原身份。事务中间没有commit，提交/回滚后释放锁；终态重复调用不再次采集。
- 独立复核按原BUSY场景重放，确认adapter初始化为0、queued/attempt0不变，释放占位后同job成功；原P2关闭。旧interval测试的mock此前一直留下queued，已改为模拟真实成功提交，继续验证完成后的间隔限制；没有放松断言来允许重复成功执行。
- Owner组合80 passed / 24 PG skipped，商品API13 passed，采集调度47 passed（旧interval mock由主线程另验）。主线程主集成商品+调度+修正interval组合37 passed / 5 PG skipped；CI已把新商品PG专项加入既有真实数据库步骤。实际PG结果另行记录，不把skip计成通过。
- 主线程在合入后的源码上用隔离Linux容器独立执行新商品专项：21 passed / 0 skipped（13.32s），其中5项真实PG覆盖共享锁拒绝与恢复、running compaction、legacy NULL rebuild、商品事务反向阻止压缩领取直至提交，以及异常回滚恢复queued并释放锁。独立schema清理由fixture完成，未连接生产。

### 草稿提交与完整验证安排

- 最终业务代码冻结于`6481c2aa`。本地独立环境全仓回归从`55c87d23`开始，审查期间新增的观察器、路径和商品准入修复已分别在主线程专项复核；该长测试运行不能代替冻结提交的完整验证，最终以草稿PR上的精确提交CI为准。
- 草稿PR仅用于代码审阅和并行CI，不合并、不部署，不将尚在运行的完整回归写成通过。上一轮CI完整pytest耗时约27分钟，因此不串行等待两轮长测试；本地结果与精确提交CI结果均在PR验证记录更新。
- 远端main再次核对仍为`05a7e2455d3883d0587b3dcf8bd8f014cd7b579f`，无新冲突；原工作区的8项修改、2项未跟踪文件保持。项目suite锁、全局文档、S4路由、正式计划13/13结构、一致性和T1.1上下文验证通过。
- 生产最后一次本轮只读证据见11:31–11:32节，后续未进行生产写入、迁移、重放、清理或部署。业务和生产验收尚未闭合，DYDATA-104继续In Progress。

### 完整回归发现的固定月份测试修正

- 本地长回归在84%处发现旧 `test_settlement_mock_filter_and_statement_use_the_same_store` 失败，单独重跑可复现。该用例只提供八月账单，却使用默认入口；新的上一完整月默认在当前日期选择九月，现有月份保护正确隐藏八月账单的确认按钮。
- 用例现显式选择 `month=2026-08` 并断言账期显示，继续验证门店与账单一致；不改业务行为或放宽月份保护。与默认上月、真实切月、筛选刷新旧账单保护及版本冲突组合复验31项全部通过（46.14s）。旧长运行仍保留原失败证据，最终完整结论以新提交CI为准。
- 复核脚本与页面后更正前文性能口径：filters+report合计是串行接口测量；当前抖音榜单页面只调用report。当前页面首屏没有实测，不能用组合接口耗时代替。已有SQL证据支持优先评估follow/self分支提前聚合以减少中间行数，但尚未实现或验证加速幅度。

### CI通过与默认账期显示边界

- `dc5c138282423300456ba0938a4e06b82c3e26ef` 的 [CI 39369996707](https://github.com/jojiuchen-blip/dy-data/actions/runs/39369996707) 于13:07北京时间成功：全量4048 passed / 272 skipped，显式PostgreSQL门禁、前端和API/Worker/Browser/Web四镜像全部通过；生产release gate与deploy均skipped。该结果仅对应上述提交。
- 收尾检查复现另一个跨月显示边界：默认请求九月，已发布月份选项仅含八月时，账期按钮显示“请选择”。页面现在以实际查询月作为缺失选项时的显示值，不改变查询、发布版本或确认资格。新增浏览器回归先在原代码失败，补丁后与切月、旧账单保护、版本冲突和下载组合32项通过（41.01s），Web build通过。
- 上述显示补丁在全量CI通过后加入；其最终远端CI结果由PR记录，不把前一提交通过结果冒充最新head完整验证。本轮仍未部署，原工作区改动保持，DYDATA-104业务验收继续进行。

### 发布优先级调整及当前生产证据

- 用户要求尽快部署，并明确“实在恢复不了不要纠结”。正式计划转入 T3.1，T2.1 历史恢复暂缓；失败记录、恢复预算、原始事实及未完成业务验收保留。此次调整不是批准猜测退款金额、重置次数或绕过来源并发保护。
- 13:20–13:41 的有界只读核验确认：退款日期任务 a48 对应 **2026-07-31**，1,375 条金额单位不明确的原始退款也全部发生在该日，不能直接视为九月费用缺口。当前正式日水位为八月 30/31、九月 29/30（9/14 未完成）、十月 16/31。任务成功不等于退款经济口径核准。
- 使用与目标源码相同的新账期状态采集函数在生产 worker 内只读执行，设置 repeatable read/read only、3s statement、500ms lock、15s idle timeout 及 25s 总上限；退出0，命令总耗时5.27s。它仅读既有日任务，未生成账单、未采集上游、未修改状态。
- 13:31 来源门禁仍有两条 collect_dimensions/retry_wait 历史 parent 和一条正常 date_sync/settle。两条旧导出请求的唯一 attempt 已结束、没有有效 lease、没有 settle 或日期/finalize 子任务；生产原子阶段写入与目标源码一致，失败维度写入回滚。今天另一个同 target 导出已在12:27完成维度及 settle。旧请求可在排空 worker 后按审计取消流程放弃，不能标成 success；本节记录时尚未取消。
- 正常日期任务 866192 的心跳及 lease 持续更新，13:41 worker CPU约80%、内存192.6MiB，当前不是失联任务。没有强杀、重试或手动恢复该任务。
- 实际生产关键源码哈希匹配 fe02；工作目录 Git HEAD 为 ba397 且存在归档部署留下的大量修改与未跟踪文件，不能用 HEAD 代替运行版本。已在 repo 外以600权限保存完整工作树归档（排除 `.git`），文件名 `pre-release-worktree-20261020T053847Z.tar.gz`，10,471,716 B，gzip及tar目录验证通过，SHA256 `43cf4ddcf82d5a62d2ca0d759d5169800468185b9659b82e245bcea4dc947d63`。没有覆盖源目录。
- 磁盘可用约21.12GB（19.67GiB、16.67%），距离15%仅约1.97GiB；普通6份备份仍符合保留策略，未发现失败 partial 或可明显释放的新缓存。专项镜像的共享大小不能累加成可回收量。实际构建、备份、首版及WAL峰值仍须经过既有容量门禁，不降低阈值。

### 未完成账期保护与退款终态旁路修正

- `297eeb35` 将财务/结算日水位状态冻结到已有 dimensions sidecar，并纳入后台来源指纹；当前月、缺失或不完整状态返回503 `PUBLICATION_PERIOD_NOT_READY`。单月财务检查所选月，累计及包含累计卡片的结算响应检查正式起点前缀。完整零金额仍合法，GET与导出不读取实时任务、不重算、不生成账单。无需结构迁移。
- 主线程独立复核后，集成树的账期保护、财务读取与HTTP回归 **68 passed / 41.57s**；实现者另跑78项及小范围真实PG5项通过，未把这些计为主线程全仓验证。新PG测试文件符合现有CI glob，会进入显式PostgreSQL门禁。
- `08269d8c` 修正线索原始退款证据把平台 `refund_type=2` 当作全额退款的旁路，复用与采集器相同的结构识别函数。只有独立订单/券投影证明全量退款时才可采用平台退款时间；原内部全额枚举继续兼容。主线程线索/终态 **76 passed / 4.93s**，退款采集/受控重放 **72 passed / 133.81s**。
- 这些改动未恢复历史金额、未改业务终态，线上版本尚未切换。需要前端同时保留授权筛选项、清除不完整账期旧金额并显示中文说明；最终提交的完整CI和真实页面另行记录。

### 账期保护独立 PostgreSQL 复核

- 主线程在集成树使用已有隔离 PostgreSQL、独立 schema 执行账期保护与财务 PG 套件：**22 passed / 62.88s**，包括冻结读、缺日恢复指纹、完整零值、两方向金额一致性、跨月、回滚/级联以及200门店12个月构建预算。未连接生产写库。
- 前端集成 `11aef4c6`：仅明确账期未完成503可以提交同版本授权筛选和无金额视图；普通503/410/401/403仍沿用既有策略。实现者46项浏览器场景、38项界面契约和构建通过；主线程独立浏览器复核正在运行。历史账单操作仍走实时接口。
- 已再次 fetch origin，main保持 `05a7e245`，PR54仍可合并。最终提交重新进入完整CI，新增保护不冒用前一提交的通过结论。

### 14:30 发布排空、清理与完整回归修正

- 主线程独立浏览器回归完成：1 个入口、46 场景，122.87s 通过。旧 worker 收到正常退出信号后等待当前任务完成，14:20 核对 exited/0、非 OOM；正式 API 继续 healthy。没有强杀正在执行的结算任务。
- 排空后运行精确 allowlist 的一次性维护，先 dry-run，再在共享领取锁和行锁内取消两个已放弃的历史维度 parent 及各自 range 计划，共4条；保留 attempts、错误、失败阶段和原始事实。操作以 system / SSH 维护身份写审计，不伪装浏览器用户。独立测试31项通过（包含真实PG），生产二次执行 changed_jobs=0，验证幂等。
- 已保护当前7服务真实镜像、完整源码和环境配置，并保留10月16日回滚组。清理20个9月镜像的25个精确旧标签仅回收约87MB，普通 builder 缓存清理后合计约1GiB；不能把 Engine 的共享/独占估算当作 df 回收值。继续移除无容器/部署引用的10月14日 browser、ops-agent 共6标签后，实际从15,970,689,024B增至18,484,731,904B。未删除 volume、业务表或整库备份。清理报告保存在生产日志目录。
- `2e7b09d5` 的 CI 39376604326 所有显式 PostgreSQL门禁通过，但全仓 pytest 为4067 passed / 273 skipped / 2 failed（1670.65s）。两项失败来自 dashboard 合同用例的自定义 builder 没有冻结新账期完整性 sidecar，生产读端正确返回503；不是允许绕过未完成月份。
- `c2d38140` 只补该测试 builder 的合成完整性证据和准确行计数，业务代码及金额/合法空数据断言保持。主线程独立 dashboard 全文件与账期保护组合27 passed / 12.94s，继续覆盖缺日拒绝和完整零值合法两种分支。新精确提交仍须全量CI，不采用前一失败运行作为发布依据。
- 本节记录时仍未合并或切换正式版本。为后续新dump和首版留足空间，正在准备把两份旧普通备份加密复制到用户本机，只有实际密文完整解密、SHA比对和pg_restore完整读取通过后，才评估服务器副本轮换；不是永久缩短全局备份保留策略。本任务无新增foundation漂移。

### 15:40 合并、发布门禁与运行恢复

- 精确提交 `ee4b04fa` 的 CI 39380873085 全部成功：全仓 **4069 passed / 273 skipped**（1651.35s），显式 PostgreSQL 门禁、前端和四镜像构建通过。PR54 于15:07合并为 `89425aa0389fd164d4ec4b22db117e92857d8028`，合并树与已测试树相同。
- 生产旧工作目录先完整归档，再逐项移入独立保存目录；安装器检查原HEAD、真实git目录、空暂存区、完整七服务回滚镜像及目标树后安装已合并源码。运行版本仍以容器真实镜像判断，不能把新工作目录HEAD当作已完成切换。
- 14:30节记录的10月16日历史镜像组后来经过独立引用审查，已退休并精确清理，实际释放3,398,582,272 B；当前七服务的真实运行镜像、源码和配置回滚点全部保留。没有删除容器卷或业务事实。
- 仅9月24日普通备份完成本机加密转存；9月29日复制未启动。前者使用AES-256-GCM、当前Windows用户DPAPI保护密钥，经过密文认证、解密SHA256一致和`pg_restore --file=/dev/null`完整读取。此证据不是实际数据库恢复演练，恢复仍依赖保存原Windows用户配置和密钥文件。
- 首次正式构建完成后，容量门禁在备份前因12%余量正常阻止发布。核对并删除五个已被新构建替代、无任何容器引用的候选镜像，实际释放2,833,240,064 B；没有清本次重试所需的构建缓存。
- 按当前日期预演默认3份最新、7日、4周及最早基线规则，仅9月24日备份过期。重新核对其SHA与已验证加密副本一致后，用既有保留脚本删除服务器副本，保留报告`dydata104-retention-current-date-applied.json`。未缩短保留参数，9月29日和其他恢复点保留。
- 第二次发布容量检查通过，可用20,311,392,256 B。新备份`pre-migrate-20261020T071845Z.dump`为2,038,734,240 B，非空和归档目录校验通过；普通轮换未再删除文件。0062→0063迁移成功，账单快照异常门禁通过。
- 首个`douyin-ranking`静态版本从15:24构建到15:37，最终被`PUBLICATION_SOURCE_CHANGED`拒绝；没有发布head，也没有替换API、Web或采集worker。构建期间存在正常线索跟进更新，相关来源计数器推进；不能将失败版本或不完整财务账期当作可用版本。
- 只读诊断发现每500订单的核销聚合计划先从全POI取核销、逐条查券，最后才过滤本批订单。线上现有订单券与核销索引齐全；无ANALYZE的计划对比支持先按订单收窄后再映射POI的最小优化，尚未以计划估计冒充生产加速结果。
- 为避免继续中断采集，15:40恢复原配置并显式固定五个原运行镜像，恢复原worker的`unless-stopped`策略并启动。API和worker均running/healthy、无OOM，网页返回200。新源码和加法迁移保留，完整业务切换仍未完成。曾临时设置的900秒后台预算随配置恢复撤回，不能宣称新publisher已经运行。
- 恢复时根盘可用18,099,789,824 B，仍低于15%目标；后续只处理已核验的未使用构建缓存，不通过删除业务数据或降低容量阈值放行。DYDATA-104保持In Progress，历史退款和九月完整账期验收仍未完成。

### 首版核销查询修复验证

- 集成核销批次查询优化：SQL先按本批订单连接券与核销，按订单/POI聚合，再使用已加载的无歧义POI映射按门店取最大时间。未改变来源门禁、截止时间、撤销、核销成功状态和业务结果，无新增迁移。
- 实现者SQLite榜单专项40 passed / 1 PG skipped，真实PostgreSQL7 passed；主线程独立容器PG复验7 passed / 19.37s。新测试与旧SQL独立oracle比较，涵盖重复同店映射、歧义排除、多POI同店、撤销及cutoff边界；测试文件使用`_postgres.py`后缀，纳入既有显式PG CI glob。
- 合成510467订单、84944轮次的真实builder完成81.810s、峰值RSS93.8MiB、3426条SQL；该结果不能代替生产首版耗时。规模测试整项仍因既有全年筛选+列表合计1.003–1.044s未满足严格1s预算而失败，单次列表0.816–0.879s、常见月份合计0.304–0.352s。未放宽阈值或扩大到读取查询改造。
- 本补丁归属当前T3.1发布阻断修复，主/子计划、看板和执行入口已同步；consistency、T3.1 envReady/canExecute均通过。最终CI、重新预热和生产切换仍待本提交验证，不把前一版本CI或本地规模结果冒充线上完成。

### 构建后缓存清理与发布重试准备

- PR55承接首版核销慢查询修复。生产worker已恢复且持续healthy，未把主机源码或已执行0063迁移标为新版本上线。
- 发布脚本新增默认关闭的`DEPLOY_PRUNE_BUILD_CACHE_AFTER_BUILD`：显式true时只在所有镜像构建成功后执行`docker builder prune --force`，失败走现有错误处理；PostgreSQL、容量、备份、迁移、五模块首版及切换门禁保持原顺序。仅清理dangling构建缓存，实际释放量由df确认，不把unused估算作为可用空间。
- 主线程`bash -n`与`git diff --check`通过；部署脚本、镜像回滚、publication预热、Compose和备份轮换组合68 passed / 1 skipped（16.33s），覆盖清理开关、失败退出及顺序。默认容量不足仍阻断，不降低15%和10GiB阈值。本增量无foundation漂移。
- 独立审阅确认构建/清理失败传播和保留门禁有效；发现并修正显式空串与默认初始化的测试差异，harness现执行真实初始化。最终组合复验69 passed / 1 skipped（18.84s），bash语法和diff检查通过。

### 16:12 新历史补采阻断与缓存清理

- 15:40恢复旧worker后，正常调度启动业务日2026-07-24的`date-sync-07348cb62442bab8bf74eddbd0ca2de7`。16:04的READ ONLY有界诊断确认其为collect/retry_wait、douyin_rate_limited、attempt1/3、无lease；下一次本地重试2026-10-21 00:03:02+08。此时间不是上游配额恢复证据，历史请求还必须遵守02:00窗口。
- checkpoint已提交53页：orders27、clues7、verify17完成，refunds2页未完成；无法从已有证据推算退款剩余页数。attempt峰值约98.4MiB，当前证据不支持OOM。
- 经EXPLAIN确认source_run索引后查询：该run当前归属orders2250、coupons2158、verify327、clues662、refunds200，impacts3626（包含大量已有事实更新）。materialize/settle stage尚不存在。采集按页原子提交，collect committed_at空不表示未写；不能通过删除来源行回滚，更不能取消任务后把全局忙碌门禁解除当作完整性证据。
- 维持真实重试与旧版服务，不取消该新任务、不发起额外上游试探、不绕过首版门禁。普通失败/取消任务的部分提交需保留独立完整性验收，任务终态本身不代表完整来源。DYDATA-104继续In Progress。
- 16:11仅清理dangling构建缓存，命令为`docker builder prune --force`；执行前后核对7个真实运行回滚镜像、5个候选镜像和35个现有容器的镜像引用。没有修改镜像标签、容器、卷、备份或业务事实。
- 引擎报告回收2.999GB，但文件系统实际由17,702,838,272B升至19,936,260,096B，实际释放2,233,421,824B（约2.08GiB）；随后复核可用19,936,178,176B（约18.57GiB/15.74%）。必须使用df实测，不能把引擎共享空间估算当作实际回收。报告`dydata104-dangling-cache-cleanup-20261020T081105820747Z.json`保留在生产日志目录。
- 清理后API、worker、browser、ops-agent、PostgreSQL健康，正式入口HTTP200。生产源码89425aa0与0063加法迁移保留，但实际运行镜像仍是发布前原版；5个publication head仍为空。当前没有启动新备份、构建、迁移或切换。


### 16:41 修复合并与最终只读核对

- PR55已合并为`39a8a2364e51dfba8d605e377e6849df6c44d887`，合并内容树与精确测试提交`8985f5007dbfea15fd45cb8d883a6e224d675321`完全一致（`dc9990ef3384c0f81a7b98925caf8a812f832241`）。[CI 39390355995](https://github.com/jojiuchen-blip/dy-data/actions/runs/39390355995)全部成功：全仓4079 passed / 274 skipped（1732.50s），显式PG、前端、API/Worker/Browser/Web四镜像全部通过；静态发布PG专项53 passed / 4 skipped。PR55链接：https://github.com/jojiuchen-blip/dy-data/pull/55。
- 原工作区仍为8项已跟踪修改和2项未跟踪文件，未覆盖。集成分支已经快进到已合并main，本节只记录结果，不包含新的业务代码。
- 16:41生产只读核对：073日期任务仍为collect/retry_wait，无lease，attempt1/3；没有heavy任务正在执行。0063仍在，五个publication head仍为空；唯一首版失败原因保持SOURCE_CHANGED。
- API/worker仍为原运行镜像，均healthy、OOM=false；browser、ops-agent、PostgreSQL也健康，正式入口200。根盘可用20,098,523,136B（约18.72GiB/15.86%），df使用率84%。本轮缓存清理没有错误，实际可用空间已回到15%以上；后续备份前仍必须重新测量，不据此预先放行未来写入。
- 代码已合并，生产静态页面仍未切换。下一步须先确认在途日期任务退款采集与materialize/settle/finalize真实完成，再安排正常排空、备份、五模块预热和切换。正常请求限流和历史02:00窗口保持，不取消部分提交任务、不伪造success。没有创建新的周期任务或恢复已暂停的一次性自动化；现有正常采集调度继续运行。
