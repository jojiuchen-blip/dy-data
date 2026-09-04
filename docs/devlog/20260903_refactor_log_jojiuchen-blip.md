# DYDATA-87 分佣规则发布后的门店榜单重算闭环

> 日期：2026-09-03
>
> 状态：本地修复与针对性验证完成；尚未部署生产，生产数据和 worker 执行结果待发布窗口核对。

## 目标

修复双费率分佣规则已经写入、但门店榜单仍读取旧 `agg_store_ranking` 投影而没有数据的问题。用户点击手工发布或批量导入完成后，应留下可追踪的结算重算任务并更新下游投影。

## 根因与实现

- `/admin/sku-fee-rules` 原先只创建不可变 `sku_fee_rule` 版本，没有像旧管理员规则接口一样排队 `settlement_rebuild`。
- 新增 `POST /api/v1/admin/sku-fee-rules/rebuild`，以幂等键和请求摘要生成稳定任务 ID，写入 `job_runs` 后注册后台 runner；同键同参重试返回同一任务，同键异参返回结构化 409。
- 手工多 SKU 发布在所有规则版本成功写入后只触发一次重算；任务触发失败时保留可重试意图并提示“规则已保存、任务未排队”。
- 规则页新增二次确认的“重建结算投影”人工入口，可覆盖已存在但此前没有重算任务的历史规则；该操作只提交重算任务，不新增或修改规则版本。
- 批量导入把规则、批次状态和重算任务放在同一提交边界；已完成批次重试会补齐缺失任务，不重复写规则。冲突或原子写入失败不创建重算任务。
- 抽取共享 runner，保留既有管理员规则重建入口和失败标记行为；不改变订单资格、账期、正式起算日或空榜单不造数规则。

## 单店分账链路补充

- 单店月度汇总通过 `/stores/{storeId}/monthly-settlement` 读取结算投影，费用明细通过 `/order-fee-details` 读取同一费用结果链路；分佣规则重算完成后，两者与门店榜单都必须指向同一活动投影代际。
- 发现榜单带 `rankingBasis` 时会提前走旧 `agg_store_ranking` 分支，绕过活动投影；已改为在活动指针存在时按活动代际读取带财务字段的榜单数据，修复榜单与单店页读到不同代的问题。
- 管理员重算和队列兜底执行在旧结算表提交后，会构建受影响月份的 sparse overlay、校验 manifest、通过活动指针 CAS 发布；同一已发布任务重试为幂等空操作。
- `/store-settlements` 读取的是 `SettlementStatement(is_current=true)`。规则发布不会虚构账单；若账单生成流程尚未产出当前账单，单店页的确认卡片仍显示“尚未生成”，这与月度投影是否刷新是两个状态。

## 涉及文件

- `apps/api/dy_api/routes/_settlement_jobs.py`
- `apps/api/dy_api/routes/admin.py`
- `apps/api/dy_api/routes/fee_admin.py`
- `apps/api/dy_api/schemas.py`
- `apps/web/src/api/client.ts`
- `apps/web/src/types/dashboard.ts`
- `apps/web/src/pages/AdminSkuRulesPage.tsx`
- `apps/web/src/components/AdminSkuRuleImportDrawer.tsx`
- `tests/test_api_fee_admin.py`
- `tests/test_frontend_admin_rules_workflow.py`
- `tests/test_visual_smoke.py`

## 已执行验证

- 新增回归测试先在未实现状态失败：重算端点 405、导入响应缺少 `settlementRebuild`、前端没有重算调用。
- `python -m pytest tests/test_api_fee_admin.py tests/test_api_admin_sku_rules.py tests/test_frontend_admin_rules_workflow.py -q`：`59 passed, 1 warning`。
- `python -m pytest tests/test_api_fee_admin.py tests/test_api_admin_sku_rules.py tests/test_frontend_admin_rules_workflow.py tests/test_visual_smoke.py::test_admin_fee_publish_reuses_idempotency_key_after_uncertain_network_failure tests/test_legacy_projection_bootstrap.py::test_r2c2_external_writer_lock_is_transient_and_retryable -q`：`61 passed, 1 warning`；随后前端页面契约回归为 `11 passed`。
- 首次 `python -m pytest` 全量收集为 `2320 passed / 128 skipped / 2 failed`；失败分别是全量运行时 Windows SQLite 外部锁用例清理异常，以及可视化用例尚未 mock 新重算接口。补充 mock 后，两项失败用例均单独复测通过；全量命令未在该测试修正后再次完整运行。
- `npm --prefix apps/web run build`：最终 TypeScript 检查通过，Vite production build 成功；仅保留既有大 chunk warning。
- `git diff --check`：通过；仅报告既有/本轮文本文件的 LF → CRLF 提示，无空白错误。
- 补充回归：`tests/test_api_admin_sku_rules.py`、`tests/test_settlement_generation_api.py`、`tests/test_api_dashboard.py`、单店分账前端契约、投影发布/结算投影测试合计 `150 passed`；覆盖活动代际刷新、单店月度汇总、带分佣口径榜单和重复发布幂等。

## 未完成与下一步

- 全量 pytest 首次运行未完全通过；当前变更相关的 61 个聚焦/受影响用例已通过，完整重跑尚未在可视化 mock 修正后再次执行。
- 尚未部署生产，也未直接改写生产数据库；部署后需核对规则数、`job_runs` 状态、重算后的 `settlement_fee_result`、活动投影代际及单店月度/榜单行数与样本，并刷新 `/admin/rules`、门店榜单和单店分账页面。账单确认卡片还需单独核对 `SettlementStatement` 当前账单是否已生成。
- Foundation 契约漂移已登记为 `S4-FCR-008`，等待评审，不直接改写 Foundation 正文。

## 2026-09-04 订单归属账号例外修复

- 业务口径确认：商品主数据归属账号只用于商品与结算范围匹配；是否参与分佣按订单归属账号判断。订单归属账号命中不分佣名单时，推广费和管理服务费两个方向均不生成结果。
- 根因：旧 `settlement_order_details` 物化路径已经读取 `dim_non_commission_owner_accounts`，但新的 `_materialize_dual_fee_direction` 没有读取该名单，导致双费率结果链路与旧链路口径不一致。
- 修复：在双费率方向物化入口按订单 `owner_account_name` 读取现有不分佣名单并记录 `dual_fee_non_commission_owner` 数据质量问题；商品归属账号仍保留为结算范围规则的匹配键。
- TDD 回归：新增“商品归属为比亚迪销售但订单归属为其他账号仍保留结果、订单归属为比亚迪销售两个方向均阻断”的用例；修复前 `1 failed`，修复后 `1 passed`。
- 受影响专项回归：`tests/test_data_settlement.py tests/test_worker_order_collector.py` 为 `48 passed`。结算、增量和采集组合回归为 `115 passed, 2 failed`；两项失败均位于既有 `test_worker_collection_pipeline.py` 调度器场景，当前变更未触及调度器代码，需单独处理。
- 本任务无 foundation 漂移；现有例外账号表与 API 契约足以承载该口径，不改写 Foundation。

## 2026-09-04 生产发布与重算观察

- 生产部署工作流成功：`33832277314`，Verify 与 Deploy 均通过，生产落地 SHA 为 `128b1d54fd070d26dfd59d53f5b7b4d126f16a4c`；部署脚本完成 API、Worker、Web、Browser、Ops Agent 健康检查。
- 已在生产后台确认当前有 `10` 个已生效 SKU，并提交结算投影重建任务 `admin_sku_fee_rules-2ad6f368fdee2ad690bf5da5`。
- 观察记录：提交后任务列表暂显示“已排队”，尚未出现成功或失败最终回执；后台重建在同一事务完成后才提交最终状态，不能把当前状态误判为成功。
- 生产后台的 worker 重启入口返回“当前账号没有执行此操作的权限”，未绕过权限，也未重复触发重算；如任务长时间不提交，需要有运维执行权限的账号处理 worker。

## 2026-09-04 结算重建运行态与重复执行修复

- 进一步根因：`run_settlement_job` 在整批重算的长事务内才把任务改为 `running`，因此后台列表在事务提交前一直读取到旧的 `queued`；同时 API `BackgroundTasks` 与 Worker 队列兜底都可能读取该排队记录并执行同一任务。
- 修复：新增独立短事务的原子抢占，仅允许 `job_id + settlement_rebuild + queued` 命中的一个执行者提交为 `running`；API 后台入口和 Worker 入口统一复用该抢占，未抢到者直接跳过。昂贵重算及原有失败回写、活动投影发布流程保持不变。
- TDD 证据：运行态可见性用例修复前观察到 `queued`，接口/Worker 竞态用例修复前记录到同一任务执行两次；修复后两项均通过。结算重建聚焦回归为 `10 passed, 68 deselected, 1 warning`，管理员规则接口全文件回归为 `13 passed, 1 warning`。
- 既有基线：`tests/test_worker_collection_pipeline.py` 全文件另有 2 个自动商品同步/父任务调度用例失败；这两个用例已 monkeypatch 掉结算重建处理器，失败路径不经过本次改动，继续按独立调度问题记录，不混入 DYDATA-87 修复范围。
- 生产观察：截至 2026-09-04 13:07，任务 `admin_sku_fee_rules-2ad6f368fdee2ad690bf5da5` 仍显示“已排队”；旧版本无法区分尚未领取与长事务实际运行，且不能排除两个执行入口竞争，部署本修复前不重复提交任务。
- Foundation 漂移：登记 `S4-FCR-011`，补充后台结算重建的原子抢占和可观测运行态合同；等待治理评审，不直接改写 Foundation 正文。
- GitHub 发布门禁：`2410 passed, 129 skipped`，治理、真实 PostgreSQL、Web production build 及四类镜像均通过；工作流 `33840008506` 完成生产备份、Worker 队列运行时检查和在线 smoke，生产 SHA 为 `d04180cf9b50204877b65fcdaef23266b7cdeae6`。
- 本地全量：`2408 passed, 129 skipped, 2 failed`；失败仍为上述两个 Windows 自动商品同步/父任务调度基线用例，GitHub Linux 全量对应 `2410 passed`，本次新增及受影响回归无失败。
- 在线验证：原任务于 13:35 返回 `success / 332019`，但活动投影仍为空；部署后确认后台已有 10 个启用 SKU，随后通过“仅重建结算投影”提交任务 `admin_sku_fee_rules-c983afef58d22133eded232d`。该任务从 13:58 起明确显示 `running`，证明运行态短事务已在线生效，且未出现重复任务。
- 待验收：重算完成后仍需确认活动投影发布、2026-08 全国门店榜单、单店月度指标和双方向订单费用明细；部署重启使浏览器登录会话失效，需用户自行重新登录后继续线上核对。
