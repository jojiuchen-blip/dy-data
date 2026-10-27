# DYDATA-104 2026-10-27 交付证据与未完成项

本文件是验证证据台账；需求以 [DYDATA-104](https://linear.app/keith-lim/issue/DYDATA-104) 为准，执行规则和责任只在原 [T3.1](../plans/delivery-plans/sub-delivery-plan-dydata-104-followthrough-T3.1-release-acceptance.md#2026-10-27-当前有效执行矩阵) 维护。[主计划](../plans/delivery-plans/main-delivery-plan-dydata-104-followthrough.md)、[看板](../plans/delivery-plans/task-kanban-dydata-104-followthrough.md)及[驾驶舱](../plans/execution-plan.md)继续承接，不另立权威计划。

## 事实基线与证据边界

- 计划基线为本地 `d206a65`：包含PR63、PR65及最新main的PR64，本地合并未推送。该基线用于制定执行矩阵，不是已部署版本或新集成CI通过证据。
- PR63旧CI：4599 passed / 342 skipped；PR65 `d950233` 的run `40302948158`：4595 passed / 329 skipped，PG/Nginx/API启动/Web及四镜像通过，部署作业skipped。来源为10月26日交接及10月27日续记；不把两组数量相加，不以旧规则CI证明新增月末合同。
- 10月26日D1–D7是多时点只读核查和候选预演，包含各自输入摘要与保护边界；不是原子整库快照、生产入账或本轮部署。[归属证据](dydata-104-data-rootcause-oct26.md)及[商品类型证据](dydata-104-product-types.md)保留当时结论。
- 10月27日资料3095行、当前合格1151行、128券中120当前唯一候选/8当前未通过，是最新需求中已记录的离线核对结果；本计划更新未重新执行Excel核对。它们不能证明8/9月身份、费用、账单或票据已全部对齐。10月末真实资格依据尚未发生。
- 本计划子任务只编辑指定文档，未执行生产探针、DML、补录、票据登记、迁移、部署或Linear写入。主线程后续按实际结果追加，注明时间、环境与精确版本。

## 本轮交付证据索引

【用户确认，2026-10-27本轮追加】当月以月末最后一次成功且完整采集冻结，保留实际采集时间；月底失败或不完整暂停月结。待交付的是实现和验证，不是再次确认该规则；10月27日资料仍不证明月末事实。

| 子集 | 当前证据 | 待交付 / 未执行 |
|---|---|---|
| A 月末资格 | 最新同记录类型/状态及上海月末合同已写入T3.1 | 实现与迁移/API合同（如有）、月界/跨月/迟到/重试/冻结回归；真实月末依据待发生 |
| B 阜阳8券/票据 | 窄范围、保护流程、查重/票据/双端一致标准已写入T3.1 | 可读原表及历史票据、精确逐券预演、分金额/账单关联、目标外指纹、正式应用和回读；当前无金额编造 |
| C 长期SKU | 已确认现有`product_sync.py`及SKU查询测试资产；23SKU为旧基准 | 完整自动流程、正确参数/分页/集合核对、清单外订单、有界重试/告警、实际查询与覆盖统计 |
| D 财务全部导入导出 | 现代码/页面具备BASIC_INFO、PROMOTION_FACTORY_RESULT、MANAGEMENT_FACTORY_RESULT、SAP_CONFIRMATION；T3.1已给逐类型允许/禁止迁移矩阵 | 目标版本全部入口清单、可控样例摘要、前后全状态/金额、API/浏览器/实际文件、失败/幂等/并发/撤销保护结果；目前不记通过 |
| E 全票及生产 | 旧权限/发布/筛选、全量对账、自动维护、分类/月默认及独立打榜保护已纳入当前矩阵 | 最终集成提交、全仓/PG/Web/镜像CI、迁移/回滚（如有）、目标源码/镜像/DB版本、后台任务和生产页面/文件/角色验收 |

## 追加结果的最小记录

每项追加：Requirement ID与入口ID；执行人/时间/环境/精确commit；输入/文件摘要与脱敏样本；允许/禁止转换；前后费用/账单/审核/发票及分配/付款或结算/SAP/锁账的版本、行数与分金额；目标外指纹；API和浏览器/文件内容证据；失败/幂等/并发；CI链接、部署版本和回滚；通过/失败/未执行/跳过及原因。

写入与状态迁移测试先在隔离环境执行；生产只读验收独立记录。正式批准的历史更正使用单独应用收据，不把测试、软件部署、分类转换与财务应用混写。没有部分开票新合同，不据历史状态样本放宽当前完整分配规则；不存在的入口记录“不提供/替代流程”。

## 仍受保护的决定边界

- 后22券正式补录暂停；阜阳8券不属于后22券。当前合格候选不等于8/9月历史月末事实，不恢复补录。
- 八月19方向3.59元、首次漏记26券/27方向488.88元、新回放另4券保护134.40元分别交逐笔原始依据、原新金额、受保护关联、预演和拟入账月/更正方案后决定；候选不是已入账。
- 原账号→UID桥、实收4券、八月128旧来源、首次漏记和发布差异继续执行取证，不因“仅阜阳更正”而假称其他问题已清零。
- 已确认规则不重复提问。确需反馈时给具体缺口、已查来源、方案及推荐、金额/账期/确认票据影响和一句话决定项，独立可执行工作继续。

## 文档验证结果

2026-10-27计划更新子任务实际结果（均为本地文档门禁）：

- `verify-suite-lock.mjs .`：exit 0，project-manager-suite@2.0.1锁有效。
- `collect-upstream-context.mjs . --json`：exit 0，2026-10-27T05:51:49Z，slug=dy-data、pipeline、canProceed=true；大文件/拆分文件警告按章节与相关合同读取。
- `validate-plan-structure.mjs ...main-delivery-plan-dydata-104-followthrough.md --json`：exit 0，13/13章节、5个Task、errors/warnings均为空。
- `check-plan-consistency.mjs ...main-delivery-plan-dydata-104-followthrough.md --json`：exit 0，passed=true，唯一活跃Task=T3.1，主计划/看板/子计划一致。
- `validate-global-files.mjs .`：exit 0，0 errors / 0 warnings；`route-check.mjs . --target-stage S4 --json`：exit 0，canEnter=true，developmentPlanReady明确指向本104主计划/T3.1，当前交付物来自本轮画像与驾驶舱。
- `python -m pytest tests/test_project_governance.py -q`：exit 0，9 passed in 6.85s。
- 链接索引诊断`run-project-link-indexer ... --trigger need_broken_link_or_reverse_link_check --json`与`collect-project-links ... --dry-run --json`：命令exit 0，但诊断仍有37项历史缺失引用；本写集未命中新增问题，不宣称全库链接通过。为遵守限定写集未改`docs/index/*`，主线程在最终集成树正式刷新。
- `git diff --check`：exit 0。未运行本轮业务测试、最终集成CI或生产验收；文档门禁不代表这些项目通过。foundation预期请求仍待实现后由主线程回收具体路径、行号及正式状态。
