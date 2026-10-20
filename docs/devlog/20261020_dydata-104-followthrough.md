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
- 内存与数据校验通过，全年完整首屏仍超过严格秒内目标，冷启动筛选 1.190s 的非 SQL 初始化来源未完整拆分。未复现旧 OOM，不宣称事故根因已证实；也不能将本榜单规模结果替代所有财务模块的规模验收。

### 生产只读复核 11:31–11:32

READ ONLY / REPEATABLE READ、statement_timeout 8s、lock_timeout 1s，完成后 rollback。首次查询误用了投影代次表复数名称而失败，事务回滚；按模型单数表名修正后成功，无生产写入。

- 退款日期任务真实 success；九月旧 finalize 仍 failed 3/3、原根 failed、ordinal1 pending，没有虚改任务终态。
- active 已自然推进至 published / depth24，另一个日期任务正在 settle，当前不是空闲窗口。
- 仍是 Alembic 0062，静态发布表未建立；退款金额单位不明确 1375 条、券匹配歧义 27 条仍在。本轮不绕过完整基线或执行未知金额重放。
- API、worker、ops-agent、browser、PostgreSQL healthy。根文件系统可用 21,229,232,128 B（约 19.77 GiB / 16.76%），df 使用率 83%。未执行额外清理或部署。

本轮没有修改用户记忆文件。其余源码实现未发现新 foundation 漂移；范围语义变更以 FCR-015 留待 Foundation 正文同步。
