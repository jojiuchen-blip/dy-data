# DYDATA-90 昨日优先调度

用户授权：启用新调度并启动上海时区2026-09-09整日采集。执行范围为T0.2，Linear DYDATA-90；旧采集修复发布记录不替代本次新模式验收。

## 设计与边界

- 每日02:00优先昨日完整窗口；订单同时查询创建窗口和修改窗口，退款按完成时间查询。
- 昨日采集、业务处理与最终发布闭环成功后，历史任务才使用剩余预算。历史按近到远逐日推进。
- 同一接口、应用、账户、上海业务日共用原子计数。历史默认保留10次本地重试余量；退款90次本地保护仍受历史核验的100次平台上限约束，不视作所有接口通用限制。
- 只有QPS限制的接口继续按速率节流，不虚构每日额度。历史跨零点暂停；预算暂停不计入三次真实失败上限。
- 新模式明确绕过旧无界队列领取；任务仍复用租约、fencing、阶段断点和单重任务槽。
- 门店/职人每两小时刷新，商品独立每日刷新。浏览器导出与开放接口是独立来源，运行结果分别留证。

## 当前生产启动证据

基线版本8a753e9f、迁移0052；新模式未部署时先按用户指定日期启动四个持久分域任务。

- 订单：date-sync-bf0d2255916ef05ed0c1070657c27279
- 退款：date-sync-500bf4972babcc64cb9a1e3a8e1a07ad
- 线索：date-sync-aa54b9378417324182aefad40dfeb8af
- 核销：date-sync-18b6d5a77d5c613ee780a74512564a10

00:43上海时间订单collect成功；本次写入/刷新2253条订单、2121条券。包含旧订单修改，不等于9月9日新增数。00:45增量业务处理工作项completed26200、pending574、processing28，心跳有效。此时其他分域任务排队；不能据此宣称整日数据已完成发布。

## 本地验证

- 分接口预算共享、保护预留、跨零点、QPS不伪造日额度：4 passed。
- 管理同步API及新模式日历/已发布覆盖口径：20 passed。
- Web TypeScript/Vite build通过。
- 任务控制、预算暂停、旧调度兼容与迁移组合：171 passed。
- 分页采集、发布范围、维度快照及 daily orchestrator 集成：73 passed。
- 调度器、旧 scheduler 及每请求预算：18 passed；最后收口回归及真实 PostgreSQL 另记。
- 最终候选88e5cd37：新功能组合38 passed；修正00–02维度刷新、失败分域隔离和历史额度重复预留。调度层不再用退款余额阻断全部接口，单候选推进由每请求governor统一控制。
- 完整集成、0053升级、CI与生产启用证据见下方最终记录；整日发布结果仍待后续验收。

## 发布进行中证据

- 候选：88e5cd376def6c02cb034157894e1ccfd2541228。
- 第一轮CI：https://github.com/jojiuchen-blip/dy-data/actions/runs/34382647627 。真实PostgreSQL迁移门禁及额度暂停3项实测通过；全量结果3 failed、2720 passed、155 skipped，部署被阻断。
- 三项失败已修复：dimension_snapshot对无config_version旧适配对象按legacy处理；治理计划选择测试改为独立authority fixture，去除旧计划名硬编码。修复后治理、父任务兼容、资料快照组合73 passed、64 skipped（其余PostgreSQL专项本地无服务）。将重新运行完整流水线，不绕过发布门禁。
- 第二轮CI（34385048190）两次在安装浏览器依赖前因Google Chrome apt索引Hash Sum mismatch失败。CI使用Playwright自带Chromium，故仅在临时runner停用该无关apt源，保留Ubuntu依赖源及所有包完整性校验；生产镜像、机器软件源均未修改。
- 配置备份：`/opt/dy-dashboard/logs/backups/pre-priority-mode-20260909T173047Z.env`；已保存api/worker/web/browser/ops-agent的`rollback-priority-20260910`镜像标签。
- production.env已写入新模式，当前旧进程仍运行8a753e9f，不能把配置文件写入当作模式生效证据。
- 01:36上海时间核销仍在settle，心跳更新；collect/materialize已成功。当前worker此前采样CPU79%、内存204MB，属于持续计算，尚不能宣称核销结算完成。
- 01:49:47之后四个分域collect/materialize/settle均已success；生产读取确认订单2253、券2121、退款974、线索818、核销316，退款账本9月10日已用10/90次。这是本次写入/刷新数，不是新增口径。核销settle最终于01:40:44完成。
- 四个分域的settlement_summary均为completed=true且月份/门店范围格式有效，可供all发布继承。核销涉及11个月/907个门店范围，订单涉及12个月/717个门店范围；月份与门店取并集，不相加。整日统一发布仍待新模式上线后完成。
- 当前第三轮CI：https://github.com/jojiuchen-blip/dy-data/actions/runs/34385571843 ，候选e35787ff7ce49226ea8b5cd8ca8c80e30e196abd；浏览器安装已通过，进入全量测试。

## 启用与回退操作

- 生产配置使用 `WORKER_SCHEDULER_MODE=priority_daily`、`WORKER_HISTORY_DAILY_RESERVE=10`。API和worker必须重建，确保页面与真实调度模式一致。旧 `auto_sync_enabled=false` 不再阻止新模式；不可用旧开关当作新模式停止按钮。
- 切换前优先等待旧子任务完成，备份生产env、数据库和当前容器镜像；通过部署工作流的真实PostgreSQL、全量测试、构建和健康检查门禁。若结算仍在运行，停止整个旧worker并等待其租约失效；已成功collect/materialize会复用，settle的已提交64券批次保留、中断批次回滚，未完成阶段会从impact起点幂等重放。
- 用 `ensure_daily_priority_plan` 为上海2026-09-09建立同一config的all计划。四个手工分域任务未完成时，all业务处理与finalize必须等待；最终发布范围继承分域settle的月份和门店证据。
- 发布验收读取实际worker模式、数据库迁移0053、9月9日任务租约/分页断点/阶段状态和range发布状态。不把采集行数当成已发布证明。
- 回退时先停止worker领取，保留页级断点与0053额度暂停历史；恢复部署前镜像和env后，在旧自动同步关闭且旧daily drain关闭的状态核查。若已产生quota_pause_count，禁止降级数据库迁移来丢弃暂停计数。
- 线索单窗口达到10,000条会明确失败，当前版本不自动拆子窗口；需按时间窗口进一步拆分后补齐，不得标为完整。
- T0.2上线不代表DYDATA-90全部验收完成；72小时运行、状态回补覆盖和接口授权口径仍需单独留证。
- 核销结算存在关系扩展及跨impact page重复coupon处理的计算放大，需后续记录唯一/重复coupon、批次数和耗时。本次只核查重启安全，不夹带未验证性能优化；重启可恢复数据，但未完成settle会重复部分计算。

## Foundation判断

有GAP：预算暂停与真实失败计数分离、新模式日历语义需要补充到foundation，已记录S4-FCR-001。未直接修改历史迁移或既有foundation。

## 最终部署与启动验收（2026-09-10，上海时间）

- CI 34385571843已success：2723 passed、155 skipped；真实PostgreSQL门禁通过，额度暂停专项3 passed；Web与全部生产镜像构建、0053迁移、健康检查通过。
- 实际部署代码：e35787ff7ce49226ea8b5cd8ca8c80e30e196abd。部署记录UTC 2026-09-09T18:21:32Z、worker_started=true；新worker创建于18:21:29Z。旧worker在四个分域全部完成后停机，本次没有中断运行中的结算。
- API与worker实际mode均为priority_daily；worker历史预留10、迁移20260910_0053。effective auto_sync_enabled=true；旧DB开关false不控制新模式。下一次定时为2026-09-11 02:00+08:00。
- worker scheduler源文件SHA256：1c7ad9ff61d03e4401162a8ebd98bc43a89fd58c637904b1a773c0b9001d3934，与部署git源码相符。
- 数据库备份：/opt/dy-dashboard/logs/backups/pre-migrate-20260909T181904Z.dump；工作流环境备份pre-production-cutover-20260909T181842Z.env；切换前原始模式env备份仍为pre-priority-mode-20260909T173047Z.env。
- 新调度器自动建立9月9日all计划range-sync-30c5cbdc07baa45aef0f1a8b4db53b24，窗口[2026-09-09 00:00+08,2026-09-10 00:00+08)。未再执行准备好的手动启动脚本，避免重复动作。
- 资料父任务parent-sync-65416722cd8152bc61ba34ae5db4db15已success，collect_dimensions于02:22:35完成。日期子任务date-sync-7ea6715aaf2f7245a411f75e7dd905f7在02:26:10读取为running/collect/attempt1，无error_code，心跳02:26:03；priority-paged-v1已提交67页（此前7→8），持续推进。
- T0.2初次启用与启动验收完成；整日all的settle/finalize/publish尚未完成验证，不能宣称9月9日数据已统一发布。DYDATA-90保持进行中，后续核验发布与72小时运行、历史状态覆盖。
- 手动管理页补拉仍走既有manual_sync路径；operations/jobs默认daily-sync-v3队列不由新模式领取，当前UI不调用该队列入口。作为后续运维接口统一事项记录，不扩大本次启动变更。
- 正式T0.2仍保留进行中，承接实际整日发布结果收口；实现/部署/启动分项已验收，不将正式状态提前关闭。三文件同步后再次执行S4门禁。
