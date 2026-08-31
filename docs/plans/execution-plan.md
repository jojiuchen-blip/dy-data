# 当前执行计划

> 本文件是当前执行驾驶舱，不复制 Linear Backlog，也不替代 S3 正式交付计划。

## 0. 当前增量交付：DYDATA-81 G5

- 用户已于 2026-08-30 明确授权：基于已确认《财务页面合同矩阵》、书面裁决、冻结原型和正式 API/Schema，完成六页实现、测试、隔离 UAT、受控生产部署与部署后验证；任一门禁失败即停止，不自行关闭 DYDATA-81。
- 当前隔离分支：`codex/dydata-81-finance-contract`；专用 worktree 与其他未提交工作树隔离，不复用旧冲突改动。
- 正式计划入口：[主交付计划](delivery-plans/main-delivery-plan-dy-data.md)；[任务看板](delivery-plans/task-kanban-dy-data.md)；当前子计划为 [T5.7 系统测试与用户验收](delivery-plans/sub-delivery-plan-dy-data-T5.7-system-uat.md)，控制器规格为 [DYDATA-81 财务合同 G5](2026-08-30-dydata-81-finance-contract-controller-spec.md)。
- G4 一级“财务”导航已由 `df617e7` 生产部署；G5 六页内部合同、推广费 5 卡口径、订单筛选/表头、SAP 财务值生效与版本审计、单条矫正、真实异步检测和三视口隔离 UAT 已完成本地实现与验证，当前停在生产发布硬门禁。
- 页面内部结构与业务交互以冻结原型逐项验收；视觉继续以 `docs/design-system/tokens.json`、`docs/design-system/README.md`、`apps/web/src/design-tokens.css` 和共享组件为权威。
- DYDATA-82 证明材料受控上传的发布影响仍需关闭；在其与其他数据正确性、正式 API、CI/迁移/备份/smoke 门禁全部通过前不得生产部署。

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
- 当前正式计划：[main-delivery-plan-dy-data.md](delivery-plans/main-delivery-plan-dy-data.md)。
- 当前正式计划文件组：主计划、[任务看板](delivery-plans/task-kanban-dy-data.md)、[T5.7 子计划](delivery-plans/sub-delivery-plan-dy-data-T5.7-system-uat.md) 与 [G5 控制器规格](2026-08-30-dydata-81-finance-contract-controller-spec.md)。
- 当前子开发计划：[sub-delivery-plan-dy-data-T5.7-system-uat.md](delivery-plans/sub-delivery-plan-dy-data-T5.7-system-uat.md)。
- 当前 Task：G4 已部署；G5 进行中。任一合同、数据正确性、正式 API、迁移、权限、CI、备份、部署或 smoke 门禁失败必须停止发布并记录证据。

## 2. 当前目标

- 在主系统一级“财务”下逐项交付推广服务费、管理服务费、订单明细、门店基础信息、SAP/账单异议和导入记录；内部合同对齐冻结原型，业务事实只来自 Linear 与正式 API/Schema。
- 以可审计版本实现财务 SAP 导入和单条矫正，以正式异步任务实现异议检测，并在 1440/768/390 隔离 UAT 与受控生产流程中验证。

## 3. 进行中任务

- 本地实现、完整 pytest、Web build、独立审查和 1440/768/390 隔离 UAT 已完成；证据归档与 Linear 回填进行中。
- 当前生产发布被 DYDATA-82 受控证明对象合同、GitHub/CI 鉴权、目标 PostgreSQL/备份/部署凭据门禁阻塞，禁止绕过。
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
- T5.7 G5 新鲜全量回归：完整视觉 242 passed；其余 1233 passed、2 skipped；合计 1475 passed、2 skipped、0 failed。高风险组合 167 passed，DYDATA-81 专项浏览器 7 passed，Web build 717 modules。独立复审关闭四项 Important，未发现新的 Critical/Important；DYDATA-82 受控证明对象仍为 Critical 发布阻塞。PR/CI、目标 PostgreSQL、备份、生产部署与线上 smoke 未执行。

## 5. 完成标准摘要

- 8 张目标表、20 个接口与 8 条生产路由可追溯到 PRD、验证方法和证据。
- 系统不创建开票申请、不执行真实开票或厂端审核；只登记信息、导入结果、回传状态、查询、导出与审计。
- 四类导入全量校验且整批原子；发票、异议、账单和导入更正只生成新版本，不删除历史。
- 全量 pytest、Web build、真实浏览器、迁移、并发、权限、系统测试及用户验收通过。

## 6. 状态与权威边界

- Issue 范围、优先级、负责人、状态和验收以 Linear 为准。
- 业务规则以 `docs/prd/` 与 Foundation 为准；页面文件不复制服务端财务计算或权限真相。
- 正式任务状态以主开发计划、任务看板和当前子计划三处一致为准。

## 7. 本轮验证证据

- 页面原型测试 74/74 与构建通过，关键流程已完成浏览器验证。
- PRD 9/9 功能块已确认；结构与跨文档校验均为 0 错误、0 警告。
- S3 正式计划包含 19 个总任务，其中新增 T5.1～T5.7；结构校验 `passed=true`，缺失字段、缺失子计划和模糊验收均为 0。
- 规格检查点 `b445cb9` 已推送至 `codex/dydata-19-page-loop`。
- T5.6：设计系统/前端契约 54 passed；账单/导入 API 27 passed；Web build 与 diff check 通过；相关浏览器 30 passed（含 8 路由 × 3 视口、旧路由兼容及真实 API 403/409/422），24 张生产路由截图位于 `output/playwright/`。
