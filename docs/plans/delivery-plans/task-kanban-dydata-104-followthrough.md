# DYDATA-104 任务看板

| Task | 子开发计划 | Owner | 前置 | 状态 | 完成日期 | 备注 |
|---|---|---|---|---|---|---|
| T0.2 | [API 内存归因与限额验证](sub-delivery-plan-dydata-104-followthrough-T0.2-api-capacity.md) | Codex | 统一 main；T0.1 可独立 | 并行实施 | - | DYDATA-104 A，优先验证 API 可用性 |
| T0.1 | [账期默认值与现有下载反馈](sub-delivery-plan-dydata-104-followthrough-T0.1-filters-exports.md) | Codex | PR #50 / #51 合入统一 main | 并行实施 | - | DYDATA-104 E |
| T1.1 | [自然月运行与结算链自动维护](sub-delivery-plan-dydata-104-followthrough-T1.1-monthly-maintenance.md) | Codex | 统一 main；先审阅既有执行器契约 | 待验收 | - | DYDATA-104 D |
| T2.1 | [八月缺失日追查、九月 14 日恢复与费用对账](sub-delivery-plan-dydata-104-followthrough-T2.1-september-recovery.md) | Codex | 目标执行环境与只读通道验证；生产资源允许；受控工具与证据审阅通过 | 进行中 | - | 2026-10-21 用户恢复；仅八月缺失日与 9/14；复用原根/v2 键，不复活 7/24、不重置预算 |
| T3.1 | [静态首版发布与生产业务验收](sub-delivery-plan-dydata-104-followthrough-T3.1-release-acceptance.md) | Codex | T0.1、T0.2、T1.1 代码验证；未完成账期展示保护；T2.1 对账与 UI/导出验收 | 待验收 | - | DYDATA-104 F；5da13df1已于21:26上线，最终CI、生产筛选/榜单下载/未完成账期保护及资源验收通过；保留技术成功，金额对账与用户业务验收未完成 |

