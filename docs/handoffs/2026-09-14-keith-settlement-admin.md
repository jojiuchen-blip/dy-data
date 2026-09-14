# 抖音经营引擎：协作者接手说明

交接日期：2026-09-14。此文件是交接快照，任务状态、验收与归属以 Linear 及其最新评论为准。用户已授权继续修复、测试、部署和受控补算，现要求整体交给协作者。接手人为 Linear 用户 Keith（keith_lim1998）。本轮将任务转交该用户；原线程自动执行已暂停。

## 1. 接手范围与顺序

按用户最近优先级：先完成新手引导及管理员权限收口，再优化账号管理，随后完成默认账期、管理费补算及最终验收。数据修复不能漏掉财务与门店开票流程。

| 任务 | 当前状态 | 接手后必须完成 |
| --- | --- | --- |
| [DYDATA-92](https://linear.app/keith-lim/issue/DYDATA-92/) 四页面新手引导 | 本地未提交；专项测试和 Web build 有通过记录；未部署 | 普通管理员真实角色验证、动态步骤边界、完整测试失败收口、审查、提交/PR/CI/部署、线上验收 |
| [DYDATA-93](https://linear.app/keith-lim/issue/DYDATA-93/) 普通管理员规则权限 | PR25 已合入 f173e9d；历史记录确认已生产部署；Linear 仍 In Progress | 复核部署/权限验证证据，补必要普通管理员验收，记录剩余风险与用户验收后关闭，不重复开发权限 |
| [DYDATA-76](https://linear.app/keith-lim/issue/DYDATA-76/) 账号管理操作优化 | 已有三步配置、门店搜索和页面权限的详细需求，Backlog，尚未开发 | 沿用此工单；核对旧财务页面清单依赖是否已解决，完成范围内优化并同步新手引导；不重复建票 |
| [DYDATA-87](https://linear.app/keith-lim/issue/DYDATA-87/) 分账数据、默认账期、管理费补算 | 部分修复已有历史部署；限定补算保护代码仍本地未提交；最终验收未完成 | 完成受控补算机制与数据库门禁、默认账期、部署及限定补算，完成全国/单店/财务/明细对账和开票流程验收 |

## 2. 已确认的业务口径

- 推广和管理服务费均须销售订单产生有效核销后计入；未核销、未知、待处理、已撤销核销不能计有效费用。
- 两方向按有效核销日确定账期和匹配费率，采用同一有效核销实收基数。8月销售、9月核销，两费均计9月；同券同费率应同金额，不能直接强制门店合计相等。
- 推广服务费归订单归属账号对应门店；管理服务费归核销 POI 对应门店。
- 按订单归属账号判断排除。归属“比亚迪汽车销售有限公司”的订单不参与；商品主数据归属该公司不等于订单归属该公司。
- 保留正式起算时间、渠道、商品资格、有效门店绑定、退款/重核销规则、不可变规则版本和锁账保护。
- 默认账期取当前账号授权范围内可用账期，保留 URL 和手动选择，不硬编码8月。
- 新手引导复用线索板块 GuidedTour 的背景压暗、橙色聚焦、说明卡和导航风格。涵盖门店分账、分账规则、产品范围、账号管理，各账号/页面偏好隔离，能跳过和重看。
- 普通管理员允许单条/批量发布分账规则；保留页面权限和服务端权限校验，不提升为最高管理员。

## 3. 代码交接：仅拉远程仓库会丢失未提交工作

以下路径相对于原仓库根目录；协作者在另一台机器上无法直接访问原机 worktree。本次将业务源码、相关测试和必要文档保存为交接快照，远程分支为 `handoff/keith-dydata92-20260914` 和 `handoff/keith-dydata87-20260914`。提交及推送结果以 Linear 交接评论所列 commit 为准。下方未提交列表描述打包前状态；代码为 WIP，尚未通过最终验收。不要打包 .env、浏览器会话、SSH 私钥、真实导出数据或运行日志。

### DYDATA-92

- worktree：`.worktrees/dydata-93-admin-rules`（目录名称仍是93，实际分支是92）。
- branch：`codex/dydata-92-page-onboarding`。
- HEAD：`f173e9dff755f40ed87da497a78b966fc7e2ba55`。
- 已修改：`apps/web/README.md`、`apps/web/src/App.tsx`、`apps/web/src/pages/AdminAccountsPage.tsx`、`AdminProductTypeVisibilityPage.tsx`、`AdminSkuRulesPage.tsx`、`StoreSettlementPage.tsx`。
- 新增未跟踪：`apps/web/src/hooks/usePageOnboarding.ts`、`tests/test_visual_settlement_onboarding.py`。
- 同工作树还有 `docs/index/` 和 `pwScreenShot/` 改动，必须逐项核对归属，不要整体盲目提交。
- 引导不得产生发布、保存、账单确认、开票或重算等业务写入，不得破坏当前草稿；补齐缺锚点、错误、忙状态、账号切换和动态步骤变化测试。

### DYDATA-87

- worktree：`.worktrees/dydata-87-poi-integration`。
- branch：`codex/dydata-87-poi-integration`。
- HEAD：`65ee07b9a6684b3e699b530957d0001801b548ab`。
- 本次核对有未提交改动：`.github/workflows/ci-cd.yml`、`.github/workflows/tencent-lighthouse-deploy.yml`、`apps/worker/settlement_rebuild.py`、`tests/test_deploy_compose_config.py`、`tests/test_shop_poi_settlement_repair.py`，以及计划、安全记录、devlog 和截图。
- 新增未跟踪：`apps/worker/settlement_repair_lock.py`、`apps/worker/settlement_repair_manifest.py`、`tests/test_settlement_repair_lock.py`、`tests/test_settlement_repair_manifest.py`、`tests/test_settlement_repair_scope.py`。
- 历史未完成项：生产执行入口的首次读取前加锁、数据库来源/指纹校验、续租与失效执行者隔离、持久化恢复/幂等，以及真实 PostgreSQL 并发和备份恢复验证。接手后逐项核实代码，不将这些草稿视为已可生产运行。

## 4. 测试和数据证据：均需区分历史记录与当前线上状态

- DYDATA-92 最近历史全量：2843 passed、163 skipped、1 failed；不是全绿。
- 唯一失败：`tests/test_legacy_projection_bootstrap.py::test_r2c2_external_writer_lock_is_transient_and_retryable`。测试将期限压到0.05秒，释放锁后重试也受到该期限影响；单项不改代码重跑通过，存在时限敏感证据。不能为迎合测试削弱生产锁语义。
- 引导专项和 Web build 有通过记录。历史结果位于该 worktree 的 `logs/dydata92-full-suite.xml`、`logs/dydata92-lock-repro.xml`（本地运行文件，交接时核验，不提交真实敏感日志）。
- 历史8月数据：443条账单；推广 1,201,097 分、管理 1,012,377 分，差额188,720分。这不是本次实时数据库复查结果。
- 历史限定补算候选：10 SKU、91 POI、120券，预计管理费增加188,720分；保留4处映射冲突。执行前重新核验清单、资格、金额和冲突，不能直接按历史差额写金额。
- 最终验收要提供源订单/合格与排除数量、逐券样本、两方向归属与金额、账期及四页面对账结果。

## 5. 财务与开票验收

在隔离数据下覆盖：门店双方向账单确认、版本冲突、截止时间、异议、开票前置、金额/号码校验、幂等提交、状态回传，以及财务导入、更正和撤销。已开票金额需有登记来源、操作者和审计证据，不能把计算费用当作开票事实。

生产计算重建已有授权，但须先完成备份、验证和范围限制。现有授权不包含真实账单确认、发票登记/提交、财务导入/审核、资金动作或擅自启用新账期。

## 6. 接手完成标准

1. 阅读 AGENTS.md、相关 Linear issue 和最新评论；确认负责人和写集，遵守仓库治理门禁。
2. 拉取上述两个远程交接分支，核对 Linear 中的 commit，审查已有代码后继续开发。未收录的本地截图与生成索引保留在原机，不是本次代码交接依赖。
3. 相关测试、`git diff --check`、完整 `python -m pytest`、`npm --prefix apps/web run build`；失败需记录并处理，不把单项重跑通过称为全量通过。
4. 代码审查、PR/CI、部署版本、备份/回滚方案与线上验证证据齐全。
5. 默认账期正确、限定补算完成、全国/单店/财务/明细同口径对账通过；引导四页与普通管理员权限验收通过。
6. 将验证记录、PR/commit/部署链接和剩余问题回填 Linear，获得业务验收后关闭。

## 可转发的接手指令

请整体接手本说明中的 DYDATA-92、DYDATA-93、DYDATA-87 和账号管理操作优化。先读取 Linear 最新评论和两个本地工作树未提交修改，保留已有成果。按已确认口径推进到测试、部署、受控补算与验收；不重复要求用户确认已批准的开发范围。只在新增业务决策或超出现有授权的真实财务操作时询问。请先确认代码实际可取得并登记负责人，再开始改动。


## 远程接手命令

```sh
git fetch origin
git switch --track origin/handoff/keith-dydata92-20260914
# 另一独立工作树承接补算，避免将两份历史基线混合部署：
git worktree add ../dydata87-keith --track -b keith/dydata87 origin/handoff/keith-dydata87-20260914
```

仓库：https://github.com/jojiuchen-blip/dy-data 。本次仅保存交接版本，不合并主线、不部署、不补算。分支可能基于较早主线，接手后先比较 origin/main 并有选择地整合，不直接将旧发布配置覆盖最新版本。
