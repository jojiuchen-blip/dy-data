# T0.2 历史归属、全量审计与上线

## 任务来源

- [main-delivery-plan-dydata114.md](main-delivery-plan-dydata114.md)
- [task-kanban-dydata114.md](task-kanban-dydata114.md)

#### T0.2 历史归属、全量审计与上线

**Requirement ID**：DYDATA-114

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` 全局设计规则
- `docs/api/dashboard-publications.md` 发布与读取协议
- `docs/api/ranking-lifecycle.md` 源变化跟踪

**核心逻辑**：
- AI 执行 -> 人审核。激活审计、采集记录、绑定来源和实际匹配分别取证；核对精诚养车 SKU、订单日期、退款统计口径。
- 先出全量候选与实际受影响订单差异；多 POI、跨店、状态或时间冲突不自动合并。
- 历史修复必须有明确身份和适用范围，不将当前关系直接视为历史事实；旧 API 原始账户/抖音号、认证门店号和该抖音号的唯一归属门店一致，同时核验订单账户无竞争身份。按用户补充要求不要求新昵称有订单。其他账户、抖音号、多个 POI、无有效证据及显式冲突保持原状。
- 保持静态发布、生命周期与原始事实不变；上线后逐单验收。

**核心文件**：
- `apps/api/dy_api/ranking_identity.py`
- `apps/api/dy_api/ranking_snapshots.py`
- `docs/devlog/20261105_dydata114_history.md`

**完成标准**：目标店逐单解释、全量影响分类、修复测试通过、主分支与生产版本可验证、静态结果读回一致。

**Verification Method**：针对性 pytest、SQL 前后对照、部署健康检查、线上静态榜单读回。

**Evidence**：`docs/devlog/20261105_dydata114_history.md`

**Failure Handling**：歧义行不修；发布失败保留旧版；不能绕过容量门禁。

**完成收尾：状态同步**：三计划状态与 Linear 验证记录同步。

**Owner**：AI 执行 -> 人审核

**前置**：T0.1

**状态**：进行中
