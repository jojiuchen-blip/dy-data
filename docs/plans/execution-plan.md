# 当前执行计划

> 本文件是当前执行驾驶舱，不复制 Linear Backlog，也不替代 S3 正式交付计划。

## 0. 当前增量交付：DYDATA-81 G5

- 用户已于 2026-08-30 明确授权：基于已确认《财务页面合同矩阵》、书面裁决、冻结原型和正式 API/Schema，完成六页实现、测试、隔离 UAT、受控生产部署与部署后验证；任一门禁失败即停止，不自行关闭 DYDATA-81。
- 当前隔离分支：`codex/dydata-81-finance-contract`；专用 worktree 与其他未提交工作树隔离，不复用旧冲突改动。
- 正式计划入口：[DYDATA-81 增量主交付计划](delivery-plans/main-delivery-plan-dy-data.md)；[任务看板](delivery-plans/task-kanban-dy-data.md)；当前子计划为 [T5.7 系统测试与用户验收](delivery-plans/sub-delivery-plan-dy-data-T5.7-system-uat.md)，控制器规格为 [DYDATA-81 财务合同 G5](2026-08-30-dydata-81-finance-contract-controller-spec.md)。
- G4 一级“财务”导航已由 `df617e7` 生产部署；G5 六页内部合同、推广费 5 卡口径、订单筛选/表头、SAP 财务值生效与版本审计、单条矫正、真实异步检测和三视口隔离 UAT 已完成本地实现与验证，当前停在生产发布硬门禁。
- 页面内部结构与业务交互以冻结原型逐项验收；视觉继续以 `docs/design-system/tokens.json`、`docs/design-system/README.md`、`apps/web/src/design-tokens.css` 和共享组件为权威。
- 2026-08-31 用户已裁决取消账单异议文件上传，改为填写具体原因；reason-only API/UI、三档 UAT 与截图证据已补齐。对象存储不再是 DYDATA-81 发布依赖。

## 0.1 并行增量入口：DYDATA-46

- DYDATA-46 的 production 入口升格由其独立计划与工作树继续管理，本驾驶舱当前不编辑其代码或状态，也不把它的未完成项混入 DYDATA-81 验收。
- 正式计划入口：[DYDATA-46 主交付计划](delivery-plans/main-delivery-plan-dydata-46-production-promotion.md)；Linear 仍是其范围、验收与状态权威。

## 0.2 历史增量交付：DYDATA-45

- 隔离 worktree `feat/dydata-45-agent-connect` 已完成腾讯云测试环境 Agent 一句话接入层；Linear `DYDATA-45` 已于 2026-08-27 在既有黑盒 UAT 证据和用户生产升格确认后进入 Done。该任务中的“未来企业内网 production”属于当时历史定义，当前生产决策已由 DYDATA-46 覆盖。
- 正式计划入口：[`main-delivery-plan-dydata-45-test-agent-connect.md`](delivery-plans/main-delivery-plan-dydata-45-test-agent-connect.md)，T1.1、T1.2、T2.1、T2.2、T3.1 均已完成，等待人类 Owner 最终审核。
- 运行时代码 `cab6aec` 已合入远端 `main` 并由 GitHub Actions run `29934737788` 成功部署腾讯云；最终安全复审为 `ALLOW`，Critical/Important/Minor 均为 0。全量 916 项通过、2 项 opt-in PostgreSQL 用例另在真实 PostgreSQL 连续 5 轮通过；Web production build、API/Web 镜像、空库迁移、Compose、两套 Nginx、锁定依赖审计、增量 Bandit 与公开 smoke 均通过。
- 独立 Agent 黑盒重试 verdict 为 `PASS`：CLI 0.3.0 与官方 Node MCP SDK 均完成用户浏览器授权；测试账号仅返回 3 家授权门店，默认/显式日期统计口径成立，未授权门店整单拒绝，两通道的门店数、行数和完整脱敏聚合一致。非阻断观察为顶层 `--help` / `--version` 不受支持，机器入口 `commands --json` / `version --json` 正常。
- 权威规格：[`2026-07-22-dydata-45-test-agent-connect-design.md`](../superpowers/specs/2026-07-22-dydata-45-test-agent-connect-design.md)。本增量仅覆盖当前腾讯云测试环境；未来企业内网生产版由 DYDATA-46 对入口、OAuth、keyring、部署、文档和 smoke 做彻底切换。
- 本增量不改变下文 DYDATA-41 线索中心 Foundation 的业务基线与依赖顺序；当前由 `DYDATA-46` 将腾讯云入口、OAuth、keyring、部署、文档和 smoke 切换为 production，禁止复用测试凭据。

## 0.3 生产缺陷修复入口：DYDATA-87

- 2026-09-09 安全收口修复：已核清 browser 三包12项High，构建阶段local覆盖 urllib3 2.7.0、msgpack 1.2.1、Pillow 12.3.0，并同时更新 idna 3.19、jwcrypto 1.5.7；保留apt文件，不改共享requirements或业务计算。契约红测后24项通过；隔离probe已通过实际导入路径/版本、pip check、非root包功能检查。probe不是最终发布候选，新提交CI和最终digest复审仍待完成，生产未切换。
- 2026-09-09 最新发布门禁：PR24 候选 `35eba47` CI `34322218989` 成功，全套2591 passed/141 skipped，真实PG账单并发26 passed及0051空库/已有数据升级通过；本机非visual最终2236 passed/141 skipped。候选安全审计确认 browser 实际使用的 Debian urllib3 仍受 High CVE-2025-66471 影响，当前 BLOCK，正补最小镜像依赖修复及复测；CI通过不等于已部署。旧生产仍运行，尚未迁移/重算，不替用户确认账单或开票。
- 2026-09-09 本轮最新确认：两费均按有效核销月计入、有效核销日匹配各自费率、同一核销实收基数计算，责任门店归属及订单账号排除不变；用户已明确授权部署。此前“待用户明确”仅为历史阶段记录。当前修复跨月迁移时原账单确认/开票保护缺口，Web build 已通过，最终回归、安全审查及发布尚在进行。生产核验仍为 `e979501` / schema `20260903_0050` / 正式账单 0；不得把本地通过当成上线成功。
- 2026-09-09 当前修复进展：用户授权全部排查修复部署及门店财务开票闭环；执行 [本轮控制规格](2026-09-09-dydata-87-settlement-invoice-controller-spec.md)。有效核销共同门槛、无效结果退出、两费取消冲回、重核销血缘及退款幂等已补修；0051 增加核销快照、锁账恢复关联和私有账单来源包。生产只读确认正式账单为 0，已补发布与待确认账单生成同事务入口、零账期新版本、来源漂移终止任务；不自动确认或开票。采集隔离回归 46 passed，结算/增量/来源/生成 API 一轮 260 passed，之后投影边界和表单重试仍在最终复核，不能当作最终树全量通过。确认/异议/开票锁与幂等目标绑定、SAP 快照已补修，真实 PG 并发门禁待 CI。跨月共同费率/基数及计入月待用户明确；本批未提交、未部署、金额未验收，旧发布记录不能替代本轮放行。
- 2026-09-09 规则审计纠正：用户明确推广服务费必须有效核销后计入，优先于旧 DYDATA-31/PRD 的相反条款，不再重复确认。PR23 的 `e979501` 已于 11:36 北京时间部署成功，但只证明查询展示恢复，不证明金额正确。审计发现无核销计推广、未知/待处理核销放行、撤销只冲管理、旧撤销冲减重新核销的新结果、默认费率一致未开启、单店/榜单累计来源不同六项缺陷；共同计费基数及跨月规则版本还需按既定业务口径对齐。8组内存样例已复现；140项既有回归通过却包含旧错误断言，不能作为业务验收。本轮未改计算代码或重算生产，修复与金额验收仍未完成，详见 Linear DYDATA-87 最新审计及当日开发日志。
- 2026-09-09 发布推进：单店及财务修复已提交 `4734b1c`，整合当前生产主线为 `2e2b95f`；最终清洁全量 `2497 passed / 139 skipped / 0 failed`，JUnit 0 errors，Web build、122 项治理测试与协议检查通过。独立审查无 Critical/Important；候选代码在生产只读事务核验财务 530 门店、推广 6716413 分，单店汇总与榜单一致，空权限为 0。增量安全报告见 `docs/security/dydata-87-finance-release-20260909.md`。现进入 PR/CI 与生产发布，尚未部署，不自动生成/确认/锁定账单。
- 2026-09-09 最新验收：已通过授权 SSH 查明结算范围表为空，按既有发布逻辑补齐 2026-08 商品来源的直播/短视频范围；单次重算于 2026-09-08 19:44 成功发布，当前费用结果 7069 条，线上榜单恢复 530 家门店、推广服务费 67164.13 元。订单归属排除不变，未生成/确认/锁定账单。单店明细有数据但汇总因 PostgreSQL 空参数类型推断失败返回 500；本地显式 CAST 最小修复及 118 项回归通过，目标数据库只读验证与榜单样本金额一致，尚未部署。
- 当前本地全量为 2472 passed / 139 skipped / 2 failed，两项采集测试受本机配置影响；隔离配置的完整采集模块 46 passed。独立审查后已修复无活动代次回退旧表及筛选丢失跨月负数抵扣；旧源码清洁全量已停止，须对最终源码重新收口。单店及财务提前展示增量未提交或部署，不能宣称三页面全部恢复；导出 SAP 逐行查询性能风险待处理。
- 用户确认财务应在分佣计算后即展示：本地补充未确认正式账单和无正式账单的已发布投影只读展示、权限筛选、分页、导出、总额以及办理状态，不自动确认、开票或锁账。相关138项回归和活动投影/删除标记2项测试通过；财务修改未部署，全量与生产验收尚未完成。
- 用户已授权修复、生产部署和重算现有规则；本窗口在 `codex/dydata-87-production-release-v2` 承接，关联 T5.7 生产验收，不修改其他窗口任务。
- 业务口径不变：分佣例外按订单归属账号判定，不按商品主数据归属账号替代；不虚构门店或金额。
- 当前实现将规则与重算任务原子入队，Worker 负责租约续期、失联恢复、提交围栏、过时任务合并和发布事实对账；发布必须先替换旧 API 执行器，再恢复 Worker。
- 2026-09-07 持久任务修复已由 `7eb0904` 通过 GitHub run `34076845161` 部署；遗留重算已完成，但发布结果为 0 行。只读取证确认订单归属 UID 与后台绑定账号 ID 不同，双费用链路直接等值查账号漏掉有效门店绑定。
- 当前增量修复复用订单名称精确匹配原始绑定，要求唯一、有效、真实门店，并校验账号有效期、归属冲突和候选绑定身份状态并存；待审核、明确失效 direct 不能被其他同名绑定绕过。最新核心结算与增量组合 123 项回归通过，最终独立审查 Ready，无 Critical/Important；完整回归与本次部署尚未收口，线上金额未验收。
- 2026-09-07 16:13 清洁配置全量收口：2463 passed、139 skipped，JUnit 0 failures / 0 errors；原始运行的两个调度失败已通过隔离本地配置及继承凭据消除，未禁用产品同步、未改生产配置。当前进入提交及受控发布，生产部署与重算验收仍待完成。
- 当前证据见 [2026-09-07 开发日志](../devlog/20260907_refactor_log_jojiuchen-blip.md)，需求与验收状态以 Linear DYDATA-87 为准；未获用户验收前不关闭。

## 0.4 并行增量入口：DYDATA-89

- 最新发布授权（2026-09-07）：用户明确要求“提交、推送、部署”。当前增量进入 PR CI、合并与腾讯云生产发布；以下“不涉及生产部署”为前序实现阶段记录。发布与 smoke 结果以 Linear DYDATA-89 最新记录为准。

- Linear `DYDATA-89`（线索中心增加逐步聚焦的新手引导）提交 In Review，等待用户验收；本入口与 DYDATA-81、DYDATA-46、DYDATA-45、DYDATA-58 的全局 cockpit 并行。
- 正式计划入口：[DYDATA-89 主开发计划](delivery-plans/main-delivery-plan-dydata-89-clue-onboarding.md)；[任务看板](delivery-plans/task-kanban-dydata-89-clue-onboarding.md)；当前子计划为 [T0.1 线索中心逐步聚焦引导](delivery-plans/sub-delivery-plan-dydata-89-clue-onboarding-T0.1-clue-onboarding.md)。
- T0.1 状态为 `进行中`（2026-09-07 实现与验证完成，待验收）：已接入 `/clues` 与 `/clues/details` 的七步真实页面引导、首次邀请/重播、当前筛选内可操作行优先、空/加载/只读 fallback、键盘与响应式协作。
- 验证结果：完整回归 2418 passed / 129 skipped；17 项引导专项、119 项相关回归、6 项既有浏览器回归、122 项套包测试通过；Web build、设计系统 build、`git diff --check` 通过。覆盖 1440/768/390、浅深色、reduced-motion、焦点与滚动/resize；完整证据见主计划 §5.1–5.2。功能代码已本地提交 `95dff72`，PR 与 CI 最新证据见 Linear DYDATA-89；本任务无 foundation 漂移，未改 API/Schema，不涉及生产部署，用户验收后再同步完成状态。

## 1. 当前阶段

- 套包阶段：`S4 DYDATA-81 T5.7 G5 六页财务合同实现与生产放行进行中`。
- 当前 Linear issue：`DYDATA-81`，状态 `In Progress`；当前分支由本任务单一窗口负责，完成后等待 Owner 验收，不自行关闭。
- 当前正式计划文件组：[主开发计划](delivery-plans/main-delivery-plan-dydata-clue-platform-completion.md)与[任务看板](delivery-plans/task-kanban-dydata-clue-platform-completion.md)。
- 当前 DYDATA-81 增量计划文件组：[主交付计划](delivery-plans/main-delivery-plan-dy-data.md)、[任务看板](delivery-plans/task-kanban-dy-data.md)、[T5.7 子计划](delivery-plans/sub-delivery-plan-dy-data-T5.7-system-uat.md) 与 [G5 控制器规格](2026-08-30-dydata-81-finance-contract-controller-spec.md)。
- 当前子开发计划：[sub-delivery-plan-dy-data-T5.7-system-uat.md](delivery-plans/sub-delivery-plan-dy-data-T5.7-system-uat.md)。
- 当前 Task：G4 已部署；G5 进行中。任一合同、数据正确性、正式 API、迁移、权限、CI、备份、部署或 smoke 门禁失败必须停止发布并记录证据。

## 2. 当前目标

- 在主系统一级“财务”下逐项交付推广服务费、管理服务费、订单明细、门店基础信息、SAP/账单异议和导入记录；内部合同对齐冻结原型，业务事实只来自 Linear 与正式 API/Schema。
- 以可审计版本实现财务 SAP 导入和单条矫正，以正式异步任务实现异议检测，并在 1440/768/390 隔离 UAT 与受控生产流程中验证。

## 3. 进行中任务

- 本地实现、完整 pytest、Web build、独立审查和 1440/768/390 隔离 UAT 已完成；证据归档与 Linear 回填进行中。
- 当前生产发布仍被 GitHub/CI 鉴权、目标 PostgreSQL/备份/部署凭据门禁阻塞，禁止绕过；reason-only 异议改动的专项回归和 UAT 已通过。
- 门禁恢复后先执行 PR/CI、目标 PostgreSQL 升级/回滚与并发核查，再按既有受控流程部署并完成入口、六页、权限、导入、SAP 审计、筛选/跳转和 worker 线上 smoke。

## 4. 下一步任务

- T5.5 已完成：四模板、六接口、五场景、全部错误行、原子写入、并发冲突、更正版本及受控大文件证据已闭合。
- T5.6 已完成：8 条生产路由、加载/空态/权限/冲突/提交回读、真实 FastAPI 联调与 `output/playwright/` 中 24 张三视口截图均已闭合。
- T5.7 G1a 已完成：0037 单头可逆迁移、固定购买方/6% 税率、北京时间 10/11 日结算批次及多账期同批次已通过 8 项核心契约、32 项 API/导入回归、迁移往返、前端契约、浏览器场景和独立代码审查；PostgreSQL 回填分支仍待目标数据库门禁。
- T5.7 G0 已完成：0038 不可变来源/应用、组合退款取消归零、发票事实不可变、跨锁期顺延、异议应用 Vn+1 和费用结果换版投影已通过专项 9 项、完整相关 90 项及二次独立审查；目标 PostgreSQL 两会话并发保留为发布前门禁。
- T5.7 G1b/G1c 已完成：0039/0040 可逆迁移、外部红冲/作废、多来源替换、完整关系追溯、全局号码禁用、负数账期结转与恢复入口已通过账单 API 49 项、Alembic 24 项、前端契约 11 项、Web build 和最终独立审查；目标 PostgreSQL 真实升级与并发仍为发布前门禁。
- T5.7 G2 已完成：0041/0042 单头迁移、管理费单店更正、SAP 建议/确认双版本、四类导入逐业务键撤销、管理费负数结转投影与不可变应用已通过最终相关回归 104 项、Web build、`git diff --check` 和三轮独立复审；真实 PostgreSQL 双事务压力测试保留为发布前门禁。
- T5.7 G3 已完成：0043 固化账单头与订单明细快照，历史缺失值进入异常清单，查询不再回退可变主数据，部署前强制异常归零；最终完整相关回归 `152 passed, 170 warnings`，Web build、Alembic 单头 `20260824_0043` 和 `git diff --check` 均通过，独立复审 Critical/Important/Minor 均为 0、`Ready: yes`。
- 发布前主线预检：当前隔离分支直接基于 `origin/main@ef547ab4` 建立，已避免旧分支硬合并与历史迁移链冲突。ahead/behind 是随本轮证据提交变化的运行时状态，不在计划中写死；发布前必须重新 `fetch` 并以 `git rev-list --left-right --count origin/main...HEAD` 的新鲜结果为准。后续仍须通过 PR/CI、目标 PostgreSQL 迁移与回滚门禁、部署后 smoke，才可进入生产发布。
- T5.7 本地全量回归已完成：视觉 229 passed；其余 1182 passed、2 skipped；合计 1411 passed、2 skipped、0 failed。此前视觉失败已确认由 v2-clean 标题基线漂移与 SPA/StrictMode 时序断言导致，并在测试层修正；结算页面另关闭上下文切换期间旧账单误确认与 409 冲突后旧版本残留两个 Important 缺口，线索演示模式恢复 D05-D08 管理分配验收路径且未扩展演示边界。最终独立复审 Critical/Important/Minor 均为 0，Ready: yes。迁移回滚契约仍为：空库可逆；已有不可变事实时拒绝有损降级，生产使用备份恢复或前向修复。PR/CI、目标 PostgreSQL 门禁、目标环境部署与 smoke 尚未完成。
- T5.7 G5 reason-only 增量：API/前端回归 `62 passed`；三档真实 FastAPI UAT `3 passed`；DYDATA-81 专项视觉/真实 API 回归 `10 passed`；全量视觉回归 `245 passed`。全量 pytest 已在清理后的环境重跑通过：`1480 passed, 2 skipped, 271 warnings`（36:12）；此前通用 ranking 768 视觉导航的 Windows `ERR_NO_BUFFER_SPACE` 未复现，技术门禁已收口。DYDATA-82 对象存储门禁已由 2026-08-31 用户裁决解除；PR/CI、目标 PostgreSQL、备份、生产部署与线上 smoke 仍未执行。

## 5. 完成标准

- 8 张目标表、20 个接口与 8 条生产路由可追溯到 PRD、验证方法和证据。
- 系统不创建开票申请、不执行真实开票或厂端审核；只登记信息、导入结果、回传状态、查询、导出与审计。
- 四类导入全量校验且整批原子；发票、异议、账单和导入更正只生成新版本，不删除历史。
- 全量 pytest、Web build、真实浏览器、迁移、并发、权限、系统测试及用户验收通过。
- DYDATA-81 的六个财务页面、一级财务入口、导入入口、SAP 有效值/单条矫正/版本审计、账单异议异步检测、三档响应式 UAT 和部署后 smoke 均有可复现证据；任一生产数据、权限、备份、迁移或部署门禁未通过时不得发布。

## 6. 状态与权威边界

- Issue 范围、优先级、负责人、状态和验收以 Linear 为准。
- 业务规则以 `docs/prd/` 与 Foundation 为准；页面文件不复制服务端财务计算或权限真相。
- 正式任务状态以主开发计划、任务看板和当前子计划三处一致为准；DYDATA-81 未经 Owner 验收不关闭。

## 7. 本轮验证证据

- DYDATA-81 本地实现、真实 FastAPI 三档 UAT、页面截图、专项回归和 Web build 已完成；PR/CI、目标 PostgreSQL、备份、生产部署和线上 smoke 仍须以受控环境证据为准。
- 并行线索主线的历史验证事实保留在其正式交付计划和开发日志中，不作为 DYDATA-81 生产部署证据。

> 以下并行主线的历史交付事实保留在各自正式交付计划和开发日志中。

## 8. 并行主线：DYDATA-58

- 套包阶段：`S4 线索平台收口`。
- 当前 Linear issue：`DYDATA-58`。
- 当前需求序列：`DYDATA-56 -> DYDATA-8 -> DYDATA-14 -> DYDATA-15 -> DYDATA-34 -> DYDATA-58 基础能力 -> DYDATA-70 -> DYDATA-58 剩余能力与最终门禁`。
- 当前正式计划文件组：[主开发计划](delivery-plans/main-delivery-plan-dydata-clue-platform-completion.md)与[任务看板](delivery-plans/task-kanban-dydata-clue-platform-completion.md)。
- 当前子开发计划：[T2.4 全量、等价性和 8GB 最终门禁](delivery-plans/sub-delivery-plan-dydata-clue-platform-completion-T2.4-final-verification.md)。

### 当前目标

- 完成 `DYDATA-56、8、14、15、34、70、58` 的代码、迁移、专项测试和用户视角验收证据收口。
- 保持当前产品决策：自动采集可以运行；自动正式分配与自动再分配保持关闭，现有有效正式轮次仍可由当前门店跟进。
- 将真实 PostgreSQL 和 4C/8GB Linux 三轮资源验证作为独立发布门禁，不用 SQLite、Windows 或合成数据替代。

### 进行中任务

- `T2.4 / DYDATA-58`：本地代码、真实 PostgreSQL 候选子任务和 4C/8GB 三轮资源门禁已完成，状态为 `LOCAL PG + 4C/8GB GREEN / SERVICE-PROBE RELEASE BLOCKED`。
- 本地证据包括全量 `2227 passed / 128 skipped`、Web production build、Alembic 单 head、真实 PostgreSQL 空库/带数据升级、日任务心跳/租约，以及 155,000 行在 4C/8GB Linux 下的三轮 shadow 与资源报告。
- 保护未跟踪规格文件、旧隔离 worktree 和 `stash@{0}`；不执行生产部署、重启或数据写入。

### 下一步任务

- 在已填充大量脱敏数据的真实 PostgreSQL 测试库完成原子领取、租约抢占、epoch fencing、崩溃恢复和跨日统计验证。
- 在三轮资源运行期间同步探测 HTTPS、SSH、API 和 PostgreSQL 可用性；已完成的本地文件级 4C/8GB benchmark 不替代该服务栈门禁。
- Linear OAuth 恢复后，将本地完成证据回写对应 issue；`DYDATA-58` 在外部发布门禁通过前不改为完成。

### 完成标准

- T0.1-T2.3 的代码、迁移、专项测试和文档证据全部闭合，运行时不再创建 `execution_mode=legacy` 轮次。
- 全量 pytest、Web production build、Alembic 单 head、Compose 配置和 `git diff --check` 全部通过。
- 真实 PostgreSQL 与 4C/8GB Linux 三轮资源门禁有可复现报告；在此之前 `DYDATA-58` 保持发布阻断，不宣称生产完成。

## 6. DYDATA-81 门店端财务交付记录

- 当前正式计划文件组：`docs/plans/delivery-plans/main-delivery-plan-dydata-81-store-finance.md`、`task-kanban-dydata-81-store-finance.md` 与对应子开发计划。
- 当前子开发计划：`sub-delivery-plan-dydata-81-store-finance-T1.3-production-release.md`。
- 本记录仅保存 DYDATA-81 已合入主线的发布证据，不改变当前主线 Linear 交付序列；生产发布仍以本轮门禁和用户最终验收为准。
- 自动正式分配和自动再分配未被隐式开启，且未触碰腾讯云生产环境。
