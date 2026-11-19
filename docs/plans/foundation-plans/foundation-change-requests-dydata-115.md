# DYDATA-115 Foundation 待改请求

> 来源：DYDATA-115 / S4 / T1.1；2026-11-18。业务权威为[本票](https://linear.app/keith-lim/issue/DYDATA-115)正文及11月18日跨日核销评论；实施入口为[主计划](../delivery-plans/main-delivery-plan-dydata-115.md)。
> 本文件记录上游契约漂移，未直接修改任何 Foundation 正文。六项均为待评审，由 `ai-project-manager` 裁决，`foundation-builder` 回捞；已确认业务规则不因待评审重新变为未确认。
> 代码证据按本轮集成快照 `9ab820c0`（开发起点 `678429d6`）核对；静态投影能力标记来自已提交的兼容增量 `4ad98551`。工程完整复验与负责人接受仍在进行中，正式结果由主线程写入 `docs/verification/dydata-115-verification.md` 与 `docs/devlog/20261118_refactor_log_Keith_Chen.md`。

## S4-FCR-001：任务跟进指标与旧终态自动计跟进口径分开

| 字段 | 内容 |
|---|---|
| ID | S4-FCR-001 |
| 来源 Task | DYDATA-115 / T1.1 实施商品流转、跟进保护期、统一指标与管理入口 |
| 分类 | DRIFT |
| 改动项 | 新任务指标只认本轮有效期间的有效人工提交；24小时率固定从分配起算，不随首触配置改变，累计率仅去掉24小时限制，两者共用接收任务分母。24小时内全额退款/失效且结束前无提交才排除；提前核销无提交仍为0/1。每任务最多一次；精诚70/30评分仅取精诚样本。旧兼容指标与新任务指标须明确分名，不把保留旧列误写成新口径。 |
| 原因 | `clue_followup_metrics` 的旧兼容定义仍含“24小时内核销自动1/1”，而115明确核销不是人工跟进。既有Foundation又按成熟窗口/唯一订单解释部分评分，尚未完整表达新任务共同分母；若不回捞，会把旧兼容算法复用到新看板/评分。 |
| 指向代码块 | `apps/api/dy_api/clue_followup_metrics.py:56`（旧兼容定义）；`apps/api/dy_api/clue_task_metrics.py:45`、`:225`（新任务口径）；`tests/test_clue_task_metrics.py:95`、`:110`、`:129`、`:311` |
| 目标 foundation 文件:章节 | `docs/prd/foundation/foundation-glossary-clue-center.md` §经营指标术语；`docs/prd/foundation/foundation-schema-clue-center/store_score_snapshot.md` 评分证据；`docs/prd/foundation/foundation-api-clue-center/jobs-security-and-migration.md` §6 J05指标刷新 |
| 严重度 | 建议 |
| 状态 | 待评审 |

## S4-FCR-002：商品规则、适用名单及权限采用独立生效时点

| 字段 | 内容 |
|---|---|
| ID | S4-FCR-002 |
| 来源 Task | DYDATA-115 / T1.1 实施商品流转、跟进保护期、统一指标与管理入口 |
| 分类 | GAP |
| 改动项 | 补商品ID级开关、独立规则版本、名单发布版本、授权和逐商品审计。首次入库即冻结归属/规则，包含未分配存量；名单成功发布只影响下一次选店。上传/校验/发布失败保留旧版，启用确认与预览所见有效名单版本绑定。允许跨页权限筛选全选、共享名单/分商品名单和字段级批量变更，逐商品失败可重试。专用人工交互CLI与后台共用商品授权；通用只读CLI/MCP凭据仍不得写。 |
| 原因 | 旧Foundation规定首次正式分配才绑定规则，并把规则范围定义为门店/组/城市/全局，缺商品级配置、名单和授权模型。本品缺名单但关闭流转是正常状态，直接原始就近店跟进；首次正式开启才由当时精诚共享基座生成独立版本。 |
| 指向代码块 | `apps/api/dy_api/models.py:4695`；`apps/api/dy_api/clue_product_routing.py:85`、`:150`、`:177`；`apps/api/dy_api/clue_product_routing_policy.py:6`；`tests/test_clue_product_routing.py:49`、`:62`、`:158`；`tests/test_api_clue_product_routing.py:95`；`apps/cli/src/dydata_cli/human_products.py:402` |
| 目标 foundation 文件:章节 | `docs/prd/foundation/foundation-schema-clue-center.md` §2总表/§3单表索引；`docs/prd/foundation/foundation-schema-clue-center/clue_lead_rule_version_binding.md` 绑定时点；`docs/prd/foundation/foundation-api-clue-center/rules-and-store-groups.md` §1/§8及新增商品管理契约；`docs/prd/foundation/foundation-api-clue-center/jobs-security-and-migration.md` 权限/迁移 |
| 严重度 | 建议 |
| 状态 | 待评审 |

## S4-FCR-003：业务三轮、异常入池与无候选关闭

| 字段 | 内容 |
|---|---|
| ID | S4-FCR-003 |
| 来源 Task | DYDATA-115 / T1.1 实施商品流转、跟进保护期、统一指标与管理入口 |
| 分类 | DRIFT |
| 改动项 | 明确业务轮次0/1/2与实际任务ID/物理连续轮次分开：销售店≤10公里优先、同城≤10公里评分优选、同城不限距离兜底；跳过第0轮首次任务仍记第1轮。每轮校验商品名单/承接资格，排除历史承接店，评分后依距离/固定门店ID排序。应流转但缺名单/必要锚点入总部池并记录待处理阶段，资料齐全无候选按轮次关闭。 |
| 原因 | 旧术语保留“第1轮销售店/15公里城市优选”及泛化总部池耗尽语义，不能表达本票业务轮次和10公里边界。续派必须订单隔离，锁后重验最新终态/名单，先失效旧任务再开放新任务，重复事件不重建。 |
| 指向代码块 | `apps/worker/clue_allocation_engine.py:572`、`:628`、`:721`、`:819`；`tests/test_product_routing_allocation_postgres.py:53`、`:100`、`:126` |
| 目标 foundation 文件:章节 | `docs/prd/foundation/foundation-glossary-clue-center.md` §分配规则与轮次术语；`docs/prd/foundation/foundation-schema-clue-center/clue_assignment_round.md` 任务/轮次；`docs/prd/foundation/foundation-api-clue-center/allocation-runtime-and-headquarters.md` 正式分配/总部续派 |
| 严重度 | 建议 |
| 状态 | 待评审 |

## S4-FCR-004：追加式跟进、真实改约及到期关闭规则

| 字段 | 内容 |
|---|---|
| ID | S4-FCR-004 |
| 来源 Task | DYDATA-115 / T1.1 实施商品流转、跟进保护期、统一指标与管理入口 |
| 分类 | DRIFT |
| 改动项 | 商品规则绑定后的提交为追加式不可撤回/改删；单选结果、备注选填，预约必填含时区日期时间。预约截止=预约+72小时，进一步跟进/未联系上改入时=成功提交+168小时；同状态重复或仅备注不延长，真实改约/状态切换重算，可取消预约转进一步跟进，无单轮累计上限。未联系上到期、战败/换店直接关闭；其余按轮次续派/关闭。 |
| 原因 | 旧Foundation允许软删除跟进，并规定首次保护动作后唯一一次7天保护、后续永不延长、战败/换店续派，与115冲突。旧存量按原绑定规则继续，不把新规则全量回写存量；订单有效核销/全额退款/失效仍最高优先，部分退款或申请退款不算全退。 |
| 指向代码块 | `apps/worker/clue_follow_up_state.py:39`、`:254`、`:335`、`:353`、`:407`；`tests/test_dydata115_follow_up_postgres.py:50`、`:81` |
| 目标 foundation 文件:章节 | `docs/prd/foundation/foundation-glossary-clue-center.md` §跟进/SLA/保护期；`docs/prd/foundation/foundation-schema-clue-center/clue_follow_up_record.md`、`clue_assignment_round.md` 记录/预约/期限；`docs/prd/foundation/foundation-api-clue-center/follow-up-and-rounds.md` §2/§3/§5/§6 |
| 严重度 | 建议 |
| 状态 | 待评审 |

## S4-FCR-005：核销按实际时间归任务，自店量归首次有效业务日

| 字段 | 内容 |
|---|---|
| ID | S4-FCR-005 |
| 来源 Task | DYDATA-115 / T1.1 实施商品流转、跟进保护期、统一指标与管理入口 |
| 分类 | GAP |
| 改动项 | 每条有效核销按实际发生时间匹配有效任务；当轮承接店核销才计该任务核销分子。有效轮次内异店核销不回补前轮；线索整体关闭后，实际核销店曾承接的补计其原任务，关闭原因不限制为超期。自店核销量另按订单+实际核销店全期去重，归该店首次有效核销的中国业务日期，含未生成/未分配线索的订单。 |
| 原因 | 旧Foundation主要描述唯一订单/下单月的总体核销，不足以表达任务核销率与自店量两套归属。11月18日已确认同店跨日多券示例为17日1、18日0、月1；需先全期去重再按报表日期筛选。取消无效核销/晚到事实可重算，不能恢复已关闭任务。 |
| 指向代码块 | `apps/api/dy_api/clue_task_metrics.py:174`、`:225`、`:404`；`apps/api/dy_api/clue_verification_facts.py:46`；`tests/test_clue_task_metrics.py:152`、`:167`、`:182`、`:207`、`:226`、`:238`、`:253` |
| 目标 foundation 文件:章节 | `docs/prd/foundation/foundation-glossary-clue-center.md` §经营指标术语；`docs/prd/foundation/foundation-schema-clue-center/clue_order_metric_fact.md` 指标边界；`docs/prd/foundation/foundation-api-clue-center/lead-query-and-contact.md` 列表/详情/导出核销展示；`docs/prd/foundation/foundation-api-clue-center/jobs-security-and-migration.md` §6回补 |
| 严重度 | 建议 |
| 状态 | 待评审 |

## S4-FCR-006：冻结投影新能力与旧读进程的发布兼容

| 字段 | 内容 |
|---|---|
| ID | S4-FCR-006 |
| 来源 Task | DYDATA-115 / T1.1 实施商品流转、跟进保护期、统一指标与管理入口 |
| 分类 | GAP |
| 改动项 | 记录0070仅加列/加自店核销表与两类退款来源计数器；不清旧run/head/counter。保留旧物理header（线索仍为product-type-v2）与旧窄列算法，新增任务列通过独立 `task_metrics_contract` 标记识别：clue-overview=clue-task-v3、douyin-ranking=clue-task-v1；响应分别提供contractVersion/taskMetricsContract。指纹包含新能力，缺标记不可复用为新发布成功。 |
| 原因 | 直接改旧物理合同会使仍运行的旧线索reader在预热切head时503；排名旧进程也可能把新语义按旧列解释。候选HTTP可显示旧完整投影为refreshing，但缺能力的新指标必须null；严格resolve/check-ready仍拒绝缺标记。GET不得构建、写入或扫描业务来源现算，部署/CLI须验证切换前后同一版本读取。生产商品开关与发布head独立，迁移/预热/验收/名单发布均不打开流转。 |
| 指向代码块 | `apps/api/dy_api/dashboard_publications/sources.py:88`、`:142`；`apps/api/dy_api/dashboard_publications/lifecycle.py:52`、`:126`、`:269`、`:359`；`alembic/versions/20261119_0071_clue_task_publications.py:10`、`:37`；`tests/test_api_dashboard_publications.py:92`（禁止GET现算的既有断言） |
| 目标 foundation 文件:章节 | `docs/prd/foundation/foundation-api-clue-center/jobs-security-and-migration.md` 迁移/发布与就绪；`docs/prd/foundation/foundation-api-clue-center/lead-query-and-contact.md` 看板能力/缺值；`docs/prd/foundation/foundation-schema-clue-center.md` 冻结投影索引；`docs/prd/foundation/foundation-api-dy-data.md` 静态看板发布索引与版本元信息 |
| 严重度 | 建议 |
| 状态 | 待评审 |

回捞后须由主入口记录各项采纳/修订/驳回结论，重新核对术语、Schema、API、代码与验证资产；不得把本文件的提出日期、阶段回执或计划门禁通过当成Foundation已改、生产已部署或负责人已验收。
