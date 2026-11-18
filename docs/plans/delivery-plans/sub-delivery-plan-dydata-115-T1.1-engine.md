# T1.1：DYDATA-115 完整实施与验收

## 任务来源

- 主开发计划：[DYDATA-115](main-delivery-plan-dydata-115.md)
- 任务看板：[T1.1](task-kanban-dydata-115.md)
- 需求权威：[DYDATA-115](https://linear.app/keith-lim/issue/DYDATA-115) 正文及 2026-11-18 评论。

#### T1.1 实施商品流转、跟进保护期、统一指标与管理入口

**Requirement ID**：DYDATA-115（正文全部首期范围与评论）

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md`：全局设计规则与导航；本轮增量以 Linear 为准。
- `docs/prd/foundation/foundation-glossary-clue-center.md`：唯一订单、任务/轮次、业务时间与池位置。
- `docs/prd/foundation/foundation-schema-clue-center.md`：业务键/并发原则及单表索引；按需进入 `docs/prd/foundation/foundation-schema-clue-center/clue_master_lead.md`、`docs/prd/foundation/foundation-schema-clue-center/clue_assignment_round.md`、`docs/prd/foundation/foundation-schema-clue-center/clue_follow_up_record.md`、`docs/prd/foundation/foundation-schema-clue-center/clue_lead_rule_version_binding.md`、`docs/prd/foundation/foundation-schema-clue-center/store_score_snapshot.md`。
- `docs/prd/foundation/foundation-api-clue-center.md`：接口导航；进入 `docs/prd/foundation/foundation-api-clue-center/rules-and-store-groups.md`、`docs/prd/foundation/foundation-api-clue-center/allocation-runtime-and-headquarters.md`、`docs/prd/foundation/foundation-api-clue-center/follow-up-and-rounds.md`、`docs/prd/foundation/foundation-api-clue-center/lead-query-and-contact.md` 与 `docs/prd/foundation/foundation-api-clue-center/jobs-security-and-migration.md`。
- `docs/rules/account-access-control.md`：身份、门店范围和会话；本期专用管理 CLI 由商品级授权单独约束。
- `RELEASING.md`：契约、迁移、规则版本与应用发布分别留证。

**核心逻辑**：
- AI 执行 -> 人审核。按主线程实际分派的隔离写集实现，共享文件串行集成，不覆盖其他需求。
- 商品开关和已发布规则按抖音商品 ID 保存；首次入库即绑定流转归属/规则版本，重拉、发布、改派和启停不改变已入库线索，包含未分配及在途。首次本品开启复制当时精诚养车规则为独立版本；本品关闭时原始就近店跟进至关闭，缺名单是正常状态，24 小时仅作指标，不自动关单/改派。
- 名单按商品 ID+门店编码管理；上传/校验/发布失败沿用旧版，成功发布后下一次选店用新版，当前任务保持。后台与专用交互 CLI 共用商品级服务端权限、预览、发布、审计，支持多选、跨页全选有权限筛选结果、共享名单批量应用、按商品导入不同名单、字段级批量规则/启停；逐商品反馈，失败项保留旧版并可重试。本品负责人只管理授权商品，项目组维护精诚共享基座，不增组织层级开关。
- 先判定是否流转再校验选店资料；确无有效名单或缺必要锚点进入总部池，记录商品、原因、待处理阶段，不创建任务或首触。人工续派先复核订单终态/名单；资料齐全无合格候选走正常轮次关闭。
- 固定原始就近店坐标/城市为锚点。业务第 0 轮为符合名单/资格且距原店 ≤10 公里的可识别销售店；第 1 轮同城 ≤10 公里评分最优；第 2 轮同城无距离上限。每轮排除历史承接店，排序为评分、距离、固定门店 ID。跳过第 0 轮的首次下发仍标第 1 轮；独立任务 ID 与业务轮次分开。每订单独立去重，一时仅一家店有效，先失效旧任务再开放新任务，新店可查跨轮历史，原店按既有可见权限只读。
- 每轮从正式分配起算：精诚首触 24 小时；无提交第 0/1 轮续派、第 2 轮关闭。预约必填日期时间，截止预约+72 小时；待进一步跟进和未联系上改入时从成功提交+168 小时。预约/进一步跟进到期按轮次续派或关闭，未联系上到期直接关闭。战败、客户换店直接关闭，换店由客户自行联系。提交单选、备注选填、有效提交追加且不可撤回/改删；同状态重复/仅备注不重算，真实改约和状态切换重算，取消预约无新时间可转进一步跟进。单轮无累计上限，不禁止晚于订单有效期的预约；订单有效期仍照常生效。
- 有效部分核销、全额退款或订单失效确认后立即关闭，优先于保护期；申请退款/部分退款不当全额退款。到期获得锁后重读最新有效提交与终态，重复执行不重建任务；关闭后可同步事实重算指标，不恢复任务。
- 两看板共用指标和商品范围：全部商品/精诚养车/比亚迪本品只改取样，汇总合并分子分母重算。本店按实际接收任务，各轮合并，每项每任务最多一次。24 小时跟进率只认正式分配后固定 24 小时内首次有效人工提交；累计跟进率认本轮有效期间任一有效提交，两者共用分母。接收后 24 小时内全额退款/失效且结束前无提交时排除；有提交正常计。提前核销无有效跟进保留两分母、分子为零，查看/拨号/核销不作跟进。
- 核销率分母为本店实际接收任务；用实际核销时间匹配有效轮次，仅该轮承接店核销计其分子；跨店不回补前轮。整体关闭后实际核销店曾承接的，补计该店原承接期间，含自然到期/无其他店/战败/换店，更新两看板及指标排名。核销早于首次接收仅计自店量。
- 自店核销量包含未生成或未分配线索的订单，按订单+实际核销店全期去重，归该店首次有效核销的业务日期；同店 11/17、11/18 各核销一券，17 日 1、18 日 0、11 月 1。线索看板加卡片、指标看板加列。精诚第 1/2 轮评分仅用精诚样本，核销率70%+24小时跟进率30%，累计跟进仅辅助。
- 列表核销状态旁显示跨店/关单后摘要，普通自店为已核销；详情按轮次说明核销店/实际时间/是否先跟进/是否计本店核销率/补计轮次。
- 迁移新增配置默认 OFF，保存全部存量绑定与旧处理规则，不将重拉视为新线索；试运行任务、名单预览及验证夹具隔离正式任务/指标。部署、验收、名单发布不自动开启；业务负责人确认有效名单并明确授权后才手动开启，关闭/重开只影响之后首次入库线索。

**核心文件**：
- 数据/权限/契约：`apps/api/dy_api/models.py`、`apps/api/dy_api/schemas.py`、`apps/api/dy_api/routes/clues.py`、`apps/api/dy_api/access_control.py`、`apps/worker/clue_rule_versions.py`、`alembic/versions/`（新 revision 由迁移负责人在主线 head 上确定）。
- 流转/跟进：`apps/worker/clue_allocation.py`、`apps/worker/clue_allocation_engine.py`、`apps/worker/clue_allocation_cycles.py`、`apps/worker/clue_follow_up_state.py`、`apps/worker/clue_headquarters_pool.py`、`apps/worker/clue_state_locking.py`。
- 指标/核销：`apps/api/dy_api/clue_followup_metrics.py`、`apps/api/dy_api/clue_verification_facts.py`、`apps/api/dy_api/dashboard_publications/clues.py`、`apps/api/dy_api/douyin_ranking.py`。
- UI/CLI：`apps/web/src/pages/ClueCenterPage.tsx`、`apps/web/src/pages/AdminClueAllocationPage.tsx`、`apps/web/src/api/client.ts`、`apps/cli/src/dydata_cli/parser.py`、`apps/cli/src/dydata_cli/commands.py`、`apps/cli/src/dydata_cli/client.py`。
- 验证基线：`tests/test_api_clues.py`、`tests/test_api_clue_rule_versions.py`、`tests/test_clue_allocation_engine.py`、`tests/test_clue_follow_up_state.py`、`tests/test_clue_follow_up_postgres.py`、`tests/test_clue_followup_metrics.py`、`tests/test_clue_verification_facts.py`、`tests/test_dashboard_publication_clues_postgres.py`、`tests/cli/test_commands.py`。

**完成标准**：
1. 商品独立开/关/重开、入库时点绑定、名单版本独立生效、跨商品权限、批量部分失败和服务端审计可通过 API/UI/CLI 保存后刷新读回；生产种子/迁移/名单发布均保持 OFF。
2. 销售店不适用时跳过；同城 10 公里整可选，11 公里和邻市 3 公里排除，第 2 轮可选同城远店；资料异常入池与资料齐全无候选关闭分别验证，轮次/任务 ID/候选/历史门店均可追溯。
3. 重复提交、仅备注、真实改约、取消预约、未联系上到期、战败/换店、部分/全额退款、订单失效与核销均覆盖；真实 PG 并发证明一线索至多一个有效任务，旧任务先失效，新任务后开放，重复事件零新增任务。
4. 首触配置 48 小时且第 30 小时首次有效提交，24 小时率=0/1、累计=1/1；无跟进自店核销两跟进率均0/1、核销率1/1、自店量+1；覆盖提前退款、分配前核销、有效期内跨店、关闭后原承接店和晚到核销。
5. 同组明细对齐两看板及三种商品筛选，汇总按分子分母重算；精诚评分不含本品。跨日两券示例严格为17日1/18日0/月1，重复采集/补采/取消无效核销不重复计数，摘要与详情归属可核对。
6. 隔离库迁移验证存量未分配/在途继续旧规则，试运行不污染正式任务/指标；相关/完整测试、Web构建、必要真实 PG 与 UI/交互 CLI 测试均留结果与具体未测项。CI、实际部署、迁移、业务接受不得互相替代。

**Verification Method**：
- 先执行本组结构、一致性与 T1.1 环境/上下文检查；`git diff --check`。
- 使用上述现有测试扩展新验收用例，运行商品权限/规则版本、分配/跟进、指标/核销、CLI 定向 pytest；新增测试文件由主线程在证据中记录，不假称现有文件已覆盖新行为。
- 对可丢弃 PostgreSQL 执行迁移升级、存量种子对照、规则发布/入库/到期/终态并发反例，核对任务唯一性、旧绑定和逐商品失败原子性；禁止仅以 SQLite 代替并发验收。
- 最终集成执行 `python -m pytest`、`npm --prefix apps/web run build`，运行真实浏览器按角色/商品操作及专用 CLI 交互流程，记录取消/预览无写、保存读回、逐商品失败与重试结果。
- 同一组受控订单明细逐项比对两看板分子/分母、自店核销量日期和排名；另检查生产默认 OFF 的迁移/服务/UI/CLI，生产实证未执行时写“未验证”。

**Evidence**：
- 由主线程落盘 `docs/verification/dydata-115-verification.md`，记录源码 SHA、命令、结果/跳过、测试资产、迁移、页面/CLI截图或终端回执、指标明细对账及剩余问题；当前计划建立时业务实现与验证尚未完成。
- 主计划本轮门禁记录与正式三件套；开发日志、CHANGELOG、Foundation 漂移待改请求由各授权责任人写入其正确入口，本计划不扩大写集。

**Failure Handling**：
- 商品权限/并发/存量兼容/核销归属失败则阻止该候选交付并修复；失败商品保留旧版，不能批量静默部分覆盖或扩大授权。
- 验证资产缺失先补可恢复依赖；无法补齐则明确具体用例未验证及发布阻断，不能用生产试写代替。
- 历史 PRD/Foundation 与115冲突以已确认115为本轮目标，记录漂移并提交主入口，不能改写历史事实或声称上游已更新。新增业务决定回到主线程。
- 未明确授权生产开启时开关保持 OFF，不以开工/部署/验收授权推导业务开启授权。

**Owner**：主 Codex 统筹与集成；隔离 worker 有界执行；AI 执行 -> Keith/业务负责人审核。

**前置**：DYDATA-115 开工授权、有效套件与 S4 门禁、本组一致性及环境/上下文检查。

**状态**：进行中

**完成收尾：状态同步**：
- 实现、验证和 Foundation 漂移判断后，把 Task 完成事实、验证证据、完成日期、漂移结论和建议下一步交给 `ai-project-manager`。
- 主入口调度 `delivery-planner` 同步主计划、看板、当前子计划及驾驶舱；用户/责任协作者接受前不宣称业务完成。
- 同步后重跑本组结构与一致性及 `node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S4 --json`。未完成状态同步不得标记 T1.1 已完成；生产默认 OFF 及业务手动开启状态分别留证。
