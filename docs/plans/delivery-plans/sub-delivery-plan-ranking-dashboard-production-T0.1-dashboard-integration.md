# T0.1 Ranking dashboard production Sub Delivery Plan

## 任务来源

- 主开发计划：[main-delivery-plan-ranking-dashboard-production.md](main-delivery-plan-ranking-dashboard-production.md)
- 任务看板：[task-kanban-ranking-dashboard-production.md](task-kanban-ranking-dashboard-production.md)

#### T0.1 整合生产打榜看板

**Requirement ID**：LOCAL-RANKING-PRODUCTION-001

**PRD 双链·读**：
- `mainprd-dy-data.md` §1

**核心逻辑**：
- 按已确认的三项指标、1531家适用门店分母、历史首次正式分配组织冻结规则整合原本地实现；修复正式快照接线、全渠道归属、原始核销状态、日期范围和生产迁移接续。用户已授权核验后合并部署；Linear不可用，先记录本地需求草稿。

**核心文件**：
- `apps/api/dy_api/ranking_snapshots.py`
- `apps/api/dy_api/routes/dashboard.py`
- `apps/web/src/pages/DouyinRankingPage.tsx`
- `alembic/versions/`

**完成标准**：
- 2026-09-01数据下限、9月7日至今天默认筛选；正式页面仅读取业务快照；名单更新不改旧组织快照；门店与职人全渠道订单归属可审计；原始核销状态1、撤销和自店判断正确；迁移从最新主分支单线升级；缺失证据显示质量状态。

**Verification Method**：
- 运行打榜 API、快照与归属 pytest；Docker PostgreSQL 迁移升级与真实来源核验；前端构建和页面日期、五级组织切换检查；正式发布经过 CI 和部署工作流。

**Evidence**：
- `docs/devlog/20260911_ranking_dashboard_production.md`

**Failure Handling**：
- PRD 或核心文件定位不到时阻塞。

**完成收尾：状态同步**：
- 本 Task 完成实现、验证和 foundation 漂移判断后，必须把 Task 完成事实、验证证据、完成日期、foundation 漂移结论和建议下一 Task 提交给 `ai-project-manager`。
- 由 `ai-project-manager` 调度 `delivery-planner` 同步 `main-delivery-plan-<slug>.md`、`task-kanban-<slug>.md` 和当前 `sub-delivery-plan-<slug>-<TaskID>-<short-name>.md` 的状态。
- 同步后重新运行 `node <suite-path>/tools/route-check.mjs <host> --target-stage S4 --json`（route-check 是套件的阶段门禁检查工具；`<suite-path>` 指套件根目录：源码仓库联调时为 `project-manager-suite/`，安装到宿主后为 `.agent/project-manager-suite/`，命令默认在宿主项目根目录执行），确认正式开发计划文件组三者一致；未通过前不得宣称本 Task 已完成。

**Owner**：AI 执行 -> 人审核

**前置**：无

**状态**：进行中

### Task 1: 看板日期选择与业务提示

本任务是 T0.1 的前端独立子任务。仅修改 apps/web/src/pages/DouyinRankingPage.tsx，必要时新增专用于日期逻辑的工具和测试；不要修改其他已有文件、后端、迁移或 CI。
需求：首次打开默认 2026-09-07 至北京时间今天，提供开始和结束日期选择，最早2026-09-01，结束不得早于开始。URL已带合法日期时保留所选日期；下钻保持日期。页面现在以当前月首日至月末为默认，需修正。移除422错误提示中硬编码“本地测试请选择2026-09-01至2026-09-30”的文案，改成用户能理解的未准备好数据/筛选错误提示。保留三个主指标和小字“跟进率”、五个组织层级。
限制：不要制造虚拟业务数据，不要修改git分支、暂存或提交任何文件，不要推送。其他代理或主代理会修改后端和迁移，请仅操作你的文件。
验证：检查日期边界（UTC跨北京时间零点、非法URL日期、结束早于开始）和前端TypeScript构建，能运行则运行；遇到依赖安装问题报告准确命令，不要擅自更改依赖版本。
最终报告需包含变更文件、验证命令及结果、遗留问题。报告写入该计划 SDD 工作区 task-1-report.md。不再创建子代理。

### Task 2: 独立订单归属解析器

新增 apps/api/dy_api/ranking_identity.py 与 tests/test_ranking_identity.py，仅修改这两个文件。Root 将把解析器接入 ranking_snapshots.py，因此不要编辑快照计算器。
实现可复用解析器，接收当前已有 DimAwemeAccount、RawAwemeBinding 和 POI 到门店映射，按订单成交时刻解析 owner_account_id、owner_douyin_uid 或名称原文。可自行设计小型类型/类，但报告精确调用方式。输入均为已有模型对象，测试可用 SimpleNamespace。输出包含唯一 store_id 或 None、原因以及用于审计的来源标识/是否缺历史时间证据；不要在审计证据输出昵称原文。
规则：官方职人 bind_status 2=绑定成功、105=运营中、5=已解绑、106=停用、1=待确认。仅2和105作为当前有效数字状态；兼容active/bound/认证成功/绑定成功/已绑定等既有明确成功文本，禁止把1计为成功。DimAwemeAccount 缺状态的直接门店映射可兼容，但有明确失效状态或 valid_from/valid_to 不覆盖成交北京时间日期时，禁止用昵称绕过。
职人 UID 可从 RawAwemeBinding.raw_payload.craftsman_uid 获得，同时识别 account_id_for_settlement；订单owner_account_id与owner_douyin_uid要分别按已知ID匹配，不假设两者命名空间完全相同。raw binding account_id、craftsman_uid、account_id_for_settlement 可作为候选证据。POI 必须唯一对应门店，冲突不自动选一个。
优先明确ID；缺ID匹配时才精确同名匹配（大小写、空格不模糊归一化，空白名不匹配）。昵称候选必须唯一门店，重名多店计冲突。已知失效ID不能fallback到好看的昵称；直接ID与绑定指向不同门店要标记冲突。
绑定起止时间来自 raw_payload.bind_start_time / bind_end_time，正整数秒或毫秒按量级解析，0/缺失视为未提供；已提供但非法时间不能当作无边界。必须排除成交发生在明确绑定区间之外。当前5已解绑仅在明确起止区间覆盖成交时可作历史归属；当前106停用不能仅凭起止区间推断运营状态。有当前成功状态但缺完整时间边界的候选可作当前关系参考，输出 historical_period_unverified 标志，不能宣称历史完整。对于无结束的当前成功绑定，只要有有效开始且开始<=成交，可视为覆盖当前时点的开放区间。
同一身份保留多个状态行时使用现有 updated_at 的最新记录；同时刻冲突不擅选。身份应包含可用账号/职人UID、抖音号、POI，避免把不同门店记录误当同一关系消除冲突。
测试先失败后实现，覆盖官方成功和失效码、UID/结算账号不同、同名冲突、失效ID禁止绕过、跨门店冲突、起止时间边界/毫秒/坏值、历史解绑区间、北京时间日期。
不改结算中心、不访问生产、不暂存或提交文件、不推送、不派生子代理。报告保存 task-2-report.md（同本计划SDD目录），含调用接口与验证结果。

### Task 3: 名单文件解析与版本发布适配

新增 apps/api/dy_api/ranking_configuration_upload.py 和 tests/test_ranking_configuration_upload.py。复用 ranking_configuration.publish_configuration，把正式门店 XLSX/CSV 和精诚养车适用名单转换为完整的组织与资格版本。Root负责HTTP路由/UI。按现有 DimStorePoiMapping 精确POI→store_id，拒绝无法解析/冲突，不按名称猜测。初次必须两个名单，此后允许仅更新其中一个并复用另一份最新版本。初始生效2026-09-01，此后服务器当前时刻，禁止从文件接受生效时间回写历史。仅写ranking sidecars，不更改原业务订单/线索/结算表。整份验证后调用publisher，错误不得产生部分版本。测试覆盖真实列名、POI解析、重复冲突、空表、仅更新其中一份、历史保留及正确生效时间。
