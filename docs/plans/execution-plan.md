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
- 自动正式分配和自动再分配未被隐式开启，且未触碰腾讯云生产环境。
