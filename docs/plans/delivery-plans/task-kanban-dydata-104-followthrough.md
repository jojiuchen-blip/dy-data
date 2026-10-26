# DYDATA-104 任务看板

> 2026-10-26 当前：T3.1 继续进行中，仅推进用户新授权的商品类型统一、精诚养车分类转换和默认上一完整月。数据核查由协作者负责；本会话不执行暂停的补录/账务更正。验收标准见 T3.1 最新增量，历史行不代表本次功能完成。

> 集成状态：三个功能代码已齐，真实PG及浏览器专项通过，完整回归/CI待收口；生产发布与目录转换尚未执行。详见[当前验证](../../verification/dydata-104-product-types.md)。

> 2026-10-23：T3.1保持进行中，新增商品规则、八九月重算对账、月榜与发票页面范围已获用户批准；当前Codex负责集成，详见T3.1增量。下表旧验证记录为历史，不代表新增范围完成。

| Task | 子开发计划 | Owner | 前置 | 状态 | 完成日期 | 备注 |
|---|---|---|---|---|---|---|
| T0.2 | [API 内存归因与限额验证](sub-delivery-plan-dydata-104-followthrough-T0.2-api-capacity.md) | Codex | 统一 main；T0.1 可独立 | 并行实施 | - | DYDATA-104 A，优先验证 API 可用性 |
| T0.1 | [账期默认值与现有下载反馈](sub-delivery-plan-dydata-104-followthrough-T0.1-filters-exports.md) | Codex | PR #50 / #51 合入统一 main | 并行实施 | - | DYDATA-104 E |
| T1.1 | [自然月运行与结算链自动维护](sub-delivery-plan-dydata-104-followthrough-T1.1-monthly-maintenance.md) | Codex | 统一 main；先审阅既有执行器契约 | 待验收 | - | DYDATA-104 D |
| T2.1 | [九月来源恢复、范围与费用对账](sub-delivery-plan-dydata-104-followthrough-T2.1-september-recovery.md) | 当前 Codex 会话 | 生产资源允许；受控工具与证据审阅通过 | 待验收 | - | 2026-10-21 九月30/30；452张待确认账单；两费各10,032.68元，逐层金额差异0，非九月保护指纹不变；八月不恢复 |
| T3.1 | [静态首版发布与生产业务验收](sub-delivery-plan-dydata-104-followthrough-T3.1-release-acceptance.md) | Codex | T0.1、T0.2、T1.1 代码验证；未完成账期展示保护 | 进行中 | - | DYDATA-104 F；2026-10-21 12:47 f66cdd5d上线，九月月榜及单店被八月误阻断已修复；完整CI4098通过/284跳过、真实PG和生产两页/月份切换验收通过；九月两费与452账单一致，八月累计继续保护；保留整体用户业务验收 |

