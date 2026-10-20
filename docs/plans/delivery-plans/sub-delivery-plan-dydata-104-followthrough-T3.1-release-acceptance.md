# T3.1 静态首版发布与生产业务验收

## 任务来源

- [主计划](main-delivery-plan-dydata-104-followthrough.md) / [任务看板](task-kanban-dydata-104-followthrough.md)
- [DYDATA-104](https://linear.app/keith-lim/issue/DYDATA-104)

### T3.1 静态首版发布与生产业务验收

**Requirement ID**：DYDATA-104 F / 全项

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` 全局规则
- `docs/prd/subprd/02-subprd-store-settlement.md` §3–4
- `docs/prd/subprd/03-subprd-order-fee-details.md` 筛选与导出
- `docs/prd/subprd/05-subprd-finance-promotion.md` §3
- `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md` 账单/财务契约
- `docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md` 费用、调整与冻结来源
- `docs/api/dashboard-publications.md` 不可变发布与读取

**核心逻辑**：代码合并与生产发布分别验收。最终提交完整 CI、真实 PG 门禁和前端构建通过后，核对实际生产版本及磁盘峰值预算，再走备份、迁移、五模块完整首版和 API 切换流程。首版失败保留旧版，不跳过来源与后处理门禁。保护原工作区未提交改动，不自动确认/开票/付款，不删除核销表现模块。

**核心文件**：
- `deploy/tencent/deploy.sh`
- `docs/api/dashboard-publications.md`
- `docs/rules/storage-management.md`
- `docs/devlog/20261020_dydata-104-followthrough.md`
- `tests/`

**完成标准**：五模块同版本筛选和导出、真实更新时间、冷/热耗时及内存有可复核记录；九月金额逐层一致、8/9/10 月切换及下载内容正确；实际部署源码/镜像、服务健康、磁盘余量及新错误均核对。未满足生产业务验收不得关闭 104 或把源问题写成合法零。

**Verification Method**：完整 CI、真实 PG、真实浏览器下载/权限与筛选测试、生产有界只读 smoke 和备份/磁盘容量记录。

**Evidence**：`docs/devlog/20261020_dydata-104-followthrough.md`，对应最终 CI 与脱敏运行记录。

**Failure Handling**：证据不符、资源/配额不足或保护指纹变化时停止相关写入；保留真实状态并记录具体阻碍，不绕过门禁。未满足验收不标记完成。

**完成收尾：状态同步**：核对验证与 foundation 漂移；新增契约缺口只追加待改请求。由 ai-project-manager 调度 delivery-planner 同步主计划、看板、子计划与执行驾驶舱，重跑一致性和 route-check；生产结果没有实证时不能写完成。

**Owner**：Codex 执行与独立复核 → 用户业务验收

**前置**：T0.1、T0.2、T1.1、T2.1 达到对应发布条件

**状态**：待开发

