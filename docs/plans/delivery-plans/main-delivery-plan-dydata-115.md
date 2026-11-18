# DYDATA-115：按商品启停的线索三轮流转与统一指标

> **版本**：v2
> **发布日期**：2026-11-18
> **前序版本**：v1 开工计划；本次回写已集成实现与工程验证进度，T1.1 保持进行中。
> **适用范围**：[DYDATA-115](https://linear.app/keith-lim/issue/DYDATA-115) 正文及 2026-11-18 自店核销量评论。
> **开发模式**：团队协作；主 Codex 统一分解、集成和验收，隔离 worker 负责非重叠写集，Keith 审核业务结果。
> **代码基线**：开发起点 `678429d6`；本次已核对主集成快照 `9ab820c0`（含 `97fa2932` 的人工 CLI HTTP 回归与静态投影兼容增量）。各 worker 使用隔离工作树，不覆盖其他任务修改。
> **上游发现结论**：`collect-upstream-context.mjs` 于 2026-11-18T05:24:52.907Z 扫描；slug=dy-data，mode=pipeline，canProceed=true，requiredMissing=[]，未进入失败分支。警告为大文件与拆分 Foundation：大文件按章节定位，Foundation 从索引进入任务所需子文件。
> **当前需求基线与授权**：用户已授权完整实施本 issue；本计划记录既有开工授权，不声称用户另行审阅过此新文件。正文与最新评论是本轮规则权威，历史 BRD/Foundation 用于理解契约与现状。
> **执行约束**：本次仅回写计划、画像和 Foundation 待改请求，不执行生产迁移、部署或开关操作。生产交付默认 OFF；名单发布、部署和验收均不自动开启，正式开启仍须本 issue 规定的负责人确认与明确授权。
> **目标**：在自有引擎交付商品规则/名单、三轮流转、门店跟进、两处看板与核销归属；生产默认关闭流转。

## 0. 本计划使用指南

先读本主计划与看板，再执行唯一活跃 T1.1。AI 执行 -> 人审核；主线程负责整合多个工作面，所有阶段事实从实际命令与目标版本读回得出。

### 0.1 PRD 加载约束

- 从 [mainprd](../../prd/mainprd-dy-data.md) 导航到 Foundation，避免整包读取无关结算 PRD。
- 当前行为以 DYDATA-115 正文与评论为准；[线索 Foundation API](../../prd/foundation/foundation-api-clue-center.md)、[Schema](../../prd/foundation/foundation-schema-clue-center.md) 及子文件是历史契约基线，不能以其旧 15 公里、规则绑定时点、删除跟进或指标口径覆盖本次确认。
- [账号访问规则](../../rules/account-access-control.md) 管身份与门店权限；本轮额外增加商品级授权。交互式管理 CLI 是本 issue 明确授权的专用入口，不向原通用只读 CLI/MCP 令牌扩大写权限。

### 0.2 读前门禁 / AI 自检清单

- Linear issue 已存在且为 In Progress，用户已授权实施，主线程为唯一集成负责人。
- 套件锁、全局文件和 S4 路由通过；本计划三件套结构、一致性、环境及 T1.1 上下文门禁通过后允许编码。
- 写 worker 使用隔离工作树和非重叠写集；共享文件由主线程串行集成。
- 发布名单、部署、验收均不得自动打开生产商品开关；按组织层级启停不在本期。

### 0.3 完成前验证门禁

源码实现、定向回归、真实 PostgreSQL 并发/迁移、浏览器/交互式 CLI、完整 pytest、Web 构建、CI、部署与业务接受分别留证。缺资产明确写未验证，不能用 mock 或旧 CI 代替最终版本证据。

### 本轮计划门禁记录（2026-11-18）

本记录仅证明计划和当前工作树环境可进入实施，不代表业务代码、真实 PG、UI/CLI、部署或业务验收完成。

| 命令（仓库根执行） | 实际结果 |
|---|---|
| `node .agent/project-manager-suite/tools/verify-suite-lock.mjs .` | 锁有效；suite 2.0.1，内容哈希 737ff2de9242febf1b8da301138a1e095c6b881f40adaa7aa4ca2b2cb9077bb9 |
| `node .agent/project-manager-suite/tools/validate-global-files.mjs .` | 0 errors、0 warnings |
| `node .agent/project-manager-suite/tools/route-check.mjs .` | S4；canEnter=yes |
| `node .agent/project-manager-suite/skills/05-01-delivery-planner/scripts/collect-upstream-context.mjs . --json` | 见头部扫描回执；canProceed=true |
| `node .agent/project-manager-suite/skills/05-01-delivery-planner/scripts/validate-plan-structure.mjs docs/plans/delivery-plans/main-delivery-plan-dydata-115.md --json` | passed=true；13/13章节、1 Task；0错误/警告/模糊词 |
| `node .agent/project-manager-suite/skills/05-01-delivery-planner/scripts/check-plan-consistency.mjs docs/plans/delivery-plans/main-delivery-plan-dydata-115.md --json` | passed=true；唯一 T1.1、三处均进行中 |
| `node .agent/project-manager-suite/skills/06-01-coding-standards/scripts/verify-task-context.mjs docs/plans/delivery-plans/main-delivery-plan-dydata-115.md T1.1 --env-check --json` | envReady=true，missingEnv=[]，warnings=[] |
| `node .agent/project-manager-suite/skills/06-01-coding-standards/scripts/verify-task-context.mjs docs/plans/delivery-plans/main-delivery-plan-dydata-115.md T1.1 --json` | canExecute=true，16条真实读链，missingFiles=[] |
| `git diff --check` | 通过 |

环境恢复：隔离工作树最初缺前端依赖，执行 `npm --prefix apps/web ci --no-audit --no-fund` 安装75包；普通上下文检查初次发现5条Schema简写路径，补为仓库相对完整路径后重跑通过。未修改依赖清单或锁文件。集成工作树需按自身依赖状态重跑环境检查。

### 0.4 当前实施与验证快照（2026-11-18）

- 核心模块已集成，工程验证中，待负责人验收。商品配置/授权与0069迁移、首次入库绑定、三轮分配与接续、商品保护期、共享任务指标及核销归属、API和人工交互 CLI 已进入主集成；两看板冻结指标与0070兼容增量已提交并继续做最终复验。
- CLI 分支最新回执为 `PYTHONPATH=apps/api;apps/cli/src;src` 下运行 `python -m pytest tests/cli tests/test_cli_contract_registry.py tests/test_api_cli_readonly.py tests/test_api_cli_auth.py -q`，296 passed、0 skipped、5 warnings（13.77秒），已读取原始pytest回执核对。持久用例为 `tests/cli/test_human_products_http.py`；CLI提交 `d407ec16` 对应商品服务 `f671b9ed`/`5578fecd`，覆盖名单换版拒绝开启、重新预览确认后只重试失败商品。此为真实本地API+SQLite、11轮模拟输入登录/注销验证，不等同真人TTY、生产或最终集成验收。
- 独立本地 PostgreSQL 16.15 验证资产已具备，已取得新连接、真实行锁55P03/提交解锁、错误密码与跨库访问拒绝，以及开发起点迁移至0068的回执。0069/0070及各分支锁/迁移、最终全仓、浏览器和部署证据继续由主线程逐项核验，不以基础环境可用代替业务通过。
- 静态投影保留旧物理合同和旧窄列算法，新增任务列及 `task_metrics_contract` 能力标记；HTTP可合法展示旧完整投影，新增指标缺能力时为 `null`，严格发布就绪检查仍要求新能力。GET不构建、不写入、不扫描业务来源补算；发布切换与旧进程兼容须继续验证。
- Foundation 漂移已提请回捞：[待改请求](../foundation-plans/foundation-change-requests-dydata-115.md)。实际结果统一由主线程写入 `docs/verification/dydata-115-verification.md` 与 `docs/devlog/20261118_refactor_log_Keith_Chen.md`；本计划不复制第二份验收台账。
- T1.1 与 Linear 均保持进行中；CI、实际迁移/部署、生产默认 OFF 读回和负责人接受尚须分别留证。DYDATA-104原待验收及受保护事项继续由原计划管理。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Python | >=3.11，核心后端/测试依赖可导入 | `python -c "import sys; assert sys.version_info >= (3, 11); import pytest, fastapi, sqlalchemy, psycopg, alembic"` |
| Node.js | >=20，Vite 7 支持版本 | `node -e "if (Number(process.versions.node.split('.')[0]) < 20) process.exit(1)"` |
| Git | 支持隔离工作树 | `git --version` |

| 工程目录 | 就绪标识 |
|---|---|
| `apps/web/` | `node_modules/` 存在 |

独立本地 PostgreSQL 16.15 与人工 CLI 资产已建立；各项真实 PostgreSQL、浏览器和终端回执仍由主线程按最终集成版本核验，本表通过不等于并发、迁移或页面验收完成。禁止使用生产数据作试写夹具。

## 1. 差距基线与本轮进度

| 实施前差距 | 原依据与本轮承接 | 对应任务 | 本轮状态 |
|---|---|---|---|
| 规则绑定与商品配置需扩展 | 现有 `clue_rule_versions.py` 为共享规则版本；需补商品授权、开关、独立版本和首次入库绑定，名单另按下一次选店生效 | T1.1 | 已集成，工程复验中 |
| 三轮接续与保护期语义需调整 | 现有引擎/跟进状态机存在，应核对第 1 轮 10 公里、生效轮次、战败/换店直接关闭及真实改约重算 | T1.1 | 已集成，工程复验中 |
| 指标旧定义与新规则冲突 | `clue_followup_metrics.py` 仍有提前核销自动计跟进的旧定义；需改为共用分母、有效人工提交和固定 24 小时 | T1.1 | 已集成，工程复验中 |
| 核销归属与自店跨日去重需统一 | `clue_verification_facts.py` 与两看板需共用有效核销事实、轮次归属和首次有效核销业务日期 | T1.1 | 已集成，工程复验中 |
| 管理 UI/交互 CLI 与迁移证据待补 | 现有后台、CLI、模型与迁移须适配商品批量操作、逐商品结果及存量兼容 | T1.1 | 已集成，工程复验中 |

## 2. 分工与边界

| 角色/工作面 | 职责与结果 | 边界 |
|---|---|---|
| 主 Codex | 安全与契约判断、写集分解、集成、最终回归、证据及状态同步 | 不以 worker 自报通过代替复核 |
| 隔离 worker | 商品配置/授权与迁移、流转/跟进、指标/事实、UI/CLI 等有界实现 | 具体写集由主线程分派，不修改其他工作树或重定义业务 |
| Keith/业务负责人 | 审核业务结果；正式开启前确认已发布有效名单并明确授权 | 本期生产默认 OFF，不因开发授权自动开启 |

不含智慧营销平台对接、任务回执/状态回传/入口迁移/跨平台计时、结算中心、短信和企微提醒。通用跟进、订单终态、核销展示和指标覆盖精诚养车及比亚迪本品。

## 3. 执行阶段

### Phase 1：商品流转与指标统一交付

**Entry Criteria**：DYDATA-115 与评论可读取，用户开工授权成立，套件及本计划结构/一致性/环境/上下文门禁通过。

**Exit Criteria**：T1.1 所列规则、迁移、UI/CLI、并发与指标对账获得最终集成版本验证；生产默认关闭证据可查，未授权开启保持关闭，业务接受与实际发布事实分开记录。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T1.1 | [完整实施与验收](sub-delivery-plan-dydata-115-T1.1-engine.md) | 进行中 |

| 字段 | 内容 |
|---|---|
| 当前活跃 Phase / Task | Phase 1 / T1.1 |
| 当前子开发计划 | [T1.1](sub-delivery-plan-dydata-115-T1.1-engine.md) |
| 当前状态 | 进行中 |

## 4. 任务看板

[任务看板](task-kanban-dydata-115.md) 与当前子计划保持同一 T1.1、状态与链接。内部并行切片仍属于本 Task，不生成第二个进行中任务。

## 5. 发布闸门

- [ ] 商品开关/版本与名单两种生效时机、商品级权限隔离、逐商品失败回退及审计通过。
- [ ] 0/1/2 业务轮次、10 公里边界、缺资料入总部池与无候选关闭、并发交接通过。
- [ ] 跟进不可变、预约必填、有效变更重算及终态优先通过。
- [ ] 两看板三种商品筛选、70/30 评分及跨日自店核销明细对账通过。
- [ ] 存量/未分配/在途兼容、迁移与回滚方案、试运行隔离通过。
- [ ] 最终集成的治理检查、相关及完整测试、Web 构建、必要真实 PG 与 UI/CLI 验证留证。
- [ ] 生产默认 OFF：部署、验收和名单发布后仍关闭；业务确认名单并明确授权的手动开启单独留证。
- [ ] 实际 CI、部署/迁移、业务接受与剩余问题如实回填；未满足完成门禁时 T1.1 与 issue 不关闭。

## 6. 风险与应对

| 风险/依赖 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| 同时到期、改约、核销或重复任务 | 双店同时跟进或重复派单 | 锁后重读最新提交/终态，旧任务失效后再创建新任务，真实 PG 并发验证 | 主 Codex/流转 | 待验证 |
| 新规则污染存量、名单与绑定版本混淆 | 历史归属被重写 | 首次入库原子绑定；迁移保留存量；名单仅下次选店消费新版 | 主 Codex/配置 | 已实现，最终复验中 |
| 专用 CLI 被通用只读令牌调用 | 越权商品配置或启停 | 独立管理授权、每请求服务端重验、UI/CLI 同服务及负向用例 | 主 Codex/权限 | 待验证 |
| 业务时间/采集时间或跨日多券混用 | 重计自店核销量或归错轮次 | 有效核销实际发生时间匹配轮次；订单+门店全期去重归首次有效核销业务日期 | 主 Codex/指标 | 待验证 |
| 历史 Foundation 与本次确认漂移 | 实现回退到旧口径 | 已记录六项 Foundation 待改请求，由主入口裁决并交 foundation-builder 回捞，不擅自改上游权威 | 主 Codex | 已识别 |
| 验证资产缺失 | 无法证明真实并发/UI/迁移 | 独立PG及CLI已具备；最终新增校验、浏览器和发布资产仍逐项验证，缺口保留发布阻断 | 主 Codex | 工程验证中 |

## 7. AI 执行示例

从看板进入 T1.1，按子计划读具体 API/Schema 和实际实现，冻结商品规则/名单与指标契约，隔离实现并由主线程集成；先跑定向与负向，再做最终全仓/构建及真实资产验证；逐项回填事实，不用构建成功勾选业务闸门。

## 8. PRD → 任务反向索引

| 需求/上游 | Task | 子开发计划 |
|---|---|---|
| DYDATA-115 正文 §正式启用、§1 商品规则/名单/权限 | T1.1 | [当前子计划](sub-delivery-plan-dydata-115-T1.1-engine.md) |
| DYDATA-115 正文 §2 三轮、§3 跟进/保护期/关闭 | T1.1 | [当前子计划](sub-delivery-plan-dydata-115-T1.1-engine.md) |
| DYDATA-115 正文 §4 看板/评分/核销与 2026-11-18 跨日评论 | T1.1 | [当前子计划](sub-delivery-plan-dydata-115-T1.1-engine.md) |
| 线索 Foundation API/Schema、账号规则及现有验证资产 | T1.1 | [当前子计划](sub-delivery-plan-dydata-115-T1.1-engine.md) |

本次上游复扫：`collect-upstream-context.mjs` 于2026-11-18T05:47:25.065Z运行，slug=dy-data、canProceed=true、requiredMissing=[]；未进入缺失分支。计划入口另以 `scripts/prepare_governance_plan.mjs` 实测确认选择本115计划，避免历史104入口参与本轮CI。
