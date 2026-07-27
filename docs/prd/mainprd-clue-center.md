# 线索中心 — mainprd

> 生成时间: 2026-07-22 14:43
> 来源: prd-writer Phase 3
> 技术栈: React + TypeScript

---

## 上游引用

| 产物 | 文件 | 来源 Skill |
|------|------|-----------|
| 功能列表 | [prd-feature-list-clue-center.md](prd-feature-list-clue-center.md) | prd-writer |
| 用户流程 | [explainer-flow-dy-data.md](../../src/frontend/page-preview/explainer-flow-dy-data.md) | page-explainer |
| 交互语义 | [explainer-b-interaction-dy-data.md](../../src/frontend/page-preview/explainer-b-interaction-dy-data.md) | page-explainer |
| 页面解释交付清单 | [explainer-delivery-dy-data.md](../../src/frontend/page-preview/explainer-delivery-dy-data.md) | page-explainer |
| 术语表 | [foundation-glossary-clue-center.md](foundation/foundation-glossary-clue-center.md) | foundation-builder |
| 数据库 Schema | [foundation-schema-clue-center.md](foundation/foundation-schema-clue-center.md) | foundation-builder |
| API 接口 | [foundation-api-clue-center.md](foundation/foundation-api-clue-center.md) | foundation-builder |
| Foundation 交付清单 | [foundation-delivery-clue-center.md](foundation/foundation-delivery-clue-center.md) | foundation-builder |
| BRD | [BRD-clue-center-20260721-2134.md](../brd/BRD-clue-center-20260721-2134.md) | brd-writer |
| 页面交付清单 | [page-delivery-dy-data.md](../../src/frontend/page-preview/page-delivery-dy-data.md) | page-designer |

---

## subprd索引

| # | 区块 | 所属页面 | subprd文件 | 状态 |
|---|------|---------|-----------|------|
| 1 | 视图导航与范围筛选 | 线索中心 | [01-subprd-view-navigation-and-filters.md](subprd/01-subprd-view-navigation-and-filters.md) | 待开始 |
| 2 | 经营指标看板 | 线索中心 | [02-subprd-operating-metrics-dashboard.md](subprd/02-subprd-operating-metrics-dashboard.md) | 待开始 |
| 3 | 线索明细与导出 | 线索中心 | [03-subprd-lead-list-and-export.md](subprd/03-subprd-lead-list-and-export.md) | 待开始 |
| 4 | 联系方式与订单摘要 | 线索中心 | [04-subprd-contact-and-order-summary.md](subprd/04-subprd-contact-and-order-summary.md) | 待开始 |
| 5 | 当前有效轮次跟进操作 | 线索中心 | [05-subprd-current-round-follow-up.md](subprd/05-subprd-current-round-follow-up.md) | 待开始 |
| 6 | 分配轮次与跟进历史 | 线索中心 | [06-subprd-rounds-and-follow-up-history.md](subprd/06-subprd-rounds-and-follow-up-history.md) | 待开始 |
| 7 | 线索采集状态与配置 | 数据同步 | [07-subprd-clue-sync-status-and-config.md](subprd/07-subprd-clue-sync-status-and-config.md) | 待开始 |
| 8 | 手动补拉与线索数据维护 | 数据同步 | [08-subprd-manual-backfill-and-maintenance.md](subprd/08-subprd-manual-backfill-and-maintenance.md) | 待开始 |
| 9 | 分配规则与版本 | 线索分配后台 | [09-subprd-allocation-rules-and-versions.md](subprd/09-subprd-allocation-rules-and-versions.md) | 待开始 |
| 10 | 分配试运行与受控重建 | 线索分配后台 | [10-subprd-trial-and-controlled-rebuild.md](subprd/10-subprd-trial-and-controlled-rebuild.md) | 待开始 |
| 11 | 分配记录与审计 | 线索分配后台 | [11-subprd-allocation-records-and-audit.md](subprd/11-subprd-allocation-records-and-audit.md) | 待开始 |
| 12 | 总部线索池 | 线索分配后台 | [12-subprd-headquarters-pool.md](subprd/12-subprd-headquarters-pool.md) | 待开始 |

---

## 全局设计规则

| 规则 | 说明 |
|------|------|
| 数据范围 | 所有查询、统计、导出和详情访问先受账号数据范围约束；全国、区域、多店或单店可见不自动等于可操作。 |
| 角色与写权限 | 门店用户只操作当前分配给本店的有效轮次；普通管理员默认只读；最高管理员仅执行明确授权的配置、试运行、重建、删除和审计操作。 |
| 状态分层 | 订单状态、线索生命周期状态、池位置和分配轮次状态分别表达；店端只显示术语表定义的业务化线索状态，不直接暴露内部状态码。 |
| 唯一当前责任 | 同一活跃线索任一时刻最多存在一个当前有效轮次和一个当前责任门店；历史轮次仅可追溯，不再授予联系方式或跟进操作权。 |
| 订单终态优先 | 已核销或已退款高于跟进动作、首次跟进 SLA 和核销保护期；终态确认后立即关闭线索并回收当前轮操作权。 |
| 联系方式 | 默认展示脱敏手机号；完整手机号的查看、复制和导出逐条校验联系方式操作权，并记录敏感操作审计。 |
| 时间口径 | 日期筛选按自然日计算且结束日包含整日；总体核销率按下单时间归月，线索生成、分配、跟进和失效时间不得互相替代。 |
| 正式与试运行隔离 | 试运行不得改变池位置、创建正式轮次、授予门店责任或进入门店及总体效果指标；正式分配结果单独构成权威数据集。 |
| 历史不可改写 | 已发布规则版本、规则版本绑定、评分快照、分配决策、真实轮次和跟进历史不因后续配置或数据变化而静默重算或覆盖。 |
| 加载态 | 区块独立显示加载状态并保持页面骨架稳定；刷新、筛选和翻页不以整页跳转替代局部反馈。 |
| 空状态 | 指标无数据展示零值并保留口径说明；列表、历史、任务和日志无数据时分别展示与业务语境一致的空状态。 |
| 错误提示 | 错误留在当前工作区，说明失败对象、可恢复动作和权限原因；不得在提示中输出完整手机号、访问令牌、应用密钥或原始敏感载荷。 |
| 成功反馈 | 查看、复制、保存、发布、预览和执行结果使用不遮挡工作区的轻量反馈；高风险操作仍需明确影响范围和二次确认。 |
| 响应式行为 | 桌面端保持高密度表格和并列工作区；移动端改为可滚动任务卡片或单列工作台，写操作不得因内容溢出而不可达。 |
| 审计 | 手机号访问与导出、规则发布与退役、试运行、重建、特权覆盖和跟进记录删除均保留操作者、对象、时间、结果及必要原因。 |
| 术语 | 页面文案、状态、指标和验收条件统一引用 Foundation 术语表；禁用“第 0 轮”“跟进成功率”“处理范围”和抖音归属作为内部责任等表达。 |

---

## 一致性自查结果

- 检查时间: 待 Phase 5 执行
- P1 数据链路覆盖: 待检查
- P2 接口引用覆盖: 待检查
- P3 术语覆盖: 待复核
- P4 功能列表→subprd: 0/12 (0%)
- P5 mainprd 索引完整: 索引已建立，待 subprd 生成与确认
- P6 交互语义一致: 待检查
- P8 流程覆盖: 待复核
- P9 功能子区域 ↔ 验收对应性: 待检查
- 需回溯 foundation-builder: 待 Phase 4/5 识别

---

## 待回溯缺口

| 缺口 | 类型 | 回溯目标 | 状态 |
|---|---|---|---|
| 暂无已确认缺口；Phase 4/5 如发现权威源不足，在此登记后回溯对应上游 | 待检查 | page-explainer / foundation-builder / brd-writer | open |
