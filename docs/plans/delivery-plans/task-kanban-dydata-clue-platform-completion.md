# 线索平台收口任务看板

| Task | 子开发计划 | Owner | 前置 | 状态 | 完成日期 | 备注 |
|---|---|---|---|---|---|---|
| T0.1 | [sub-delivery-plan-dydata-clue-platform-completion-T0.1-dydata-56.md](sub-delivery-plan-dydata-clue-platform-completion-T0.1-dydata-56.md) | 主代理 | 远端同步 | 已完成（2026-08-30） | 2026-08-30 | 主档多标识验收闭环 |
| T0.2 | [sub-delivery-plan-dydata-clue-platform-completion-T0.2-dydata-8.md](sub-delivery-plan-dydata-clue-platform-completion-T0.2-dydata-8.md) | 主代理 | T0.1 | 已完成（2026-08-31） | 2026-08-31 | 逐源记录唯一映射、隔离主档、状态版本及 0044 迁移闭环 |
| T0.3 | [sub-delivery-plan-dydata-clue-platform-completion-T0.3-dydata-14.md](sub-delivery-plan-dydata-clue-platform-completion-T0.3-dydata-14.md) | 主代理 | T0.2 | 已完成（2026-08-31） | 2026-08-31 | H01 权限、标准原因、筛选、demo 与前端契约闭环 |
| T0.4 | [sub-delivery-plan-dydata-clue-platform-completion-T0.4-dydata-15.md](sub-delivery-plan-dydata-clue-platform-completion-T0.4-dydata-15.md) | 主代理 | T0.3 | 已完成（2026-08-31） | 2026-08-31 | cycle 证据、权限、审计、试运行详情及 0045 迁移闭环 |
| T1.1 | [sub-delivery-plan-dydata-clue-platform-completion-T1.1-dydata-34.md](sub-delivery-plan-dydata-clue-platform-completion-T1.1-dydata-34.md) | 主代理 | T0.4 | 已完成（2026-08-31） | 2026-08-31 | legacy 原地 formal 化；旧创建/自动再分配路径下线；专项 155、迁移 54 通过 |
| T2.1 | [sub-delivery-plan-dydata-clue-platform-completion-T2.1-dydata-58-foundation.md](sub-delivery-plan-dydata-clue-platform-completion-T2.1-dydata-58-foundation.md) | 主代理 | T1.1 | 已完成（2026-08-31） | 2026-08-31 | 控制面、按日编排、变化捕获；真实 PG/4C8GB 环境门禁归入 T2.4 |
| T2.2 | [sub-delivery-plan-dydata-clue-platform-completion-T2.2-dydata-70.md](sub-delivery-plan-dydata-clue-platform-completion-T2.2-dydata-70.md) | 主代理 | T2.1 | 已完成（2026-08-31） | 2026-08-31 | 增量线索物化、观察防回退、标识冲突隔离和有界投影闭环 |
| T2.3 | [sub-delivery-plan-dydata-clue-platform-completion-T2.3-dydata-58-remaining.md](sub-delivery-plan-dydata-clue-platform-completion-T2.3-dydata-58-remaining.md) | 主代理 | T2.2 | 已完成（2026-08-31） | 2026-08-31 | 增量结算/投影、最高管理员控制台、受限 Ops Agent、命令 fencing、唯一采集触发源和资源护栏闭环 |
| T2.4 | [sub-delivery-plan-dydata-clue-platform-completion-T2.4-final-verification.md](sub-delivery-plan-dydata-clue-platform-completion-T2.4-final-verification.md) | 主代理 -> Human Owner | T2.3 | 进行中（LOCAL GREEN / RELEASE BLOCKED） | - | 全量 2225 passed、Web build、单 head、Compose 与本地 shadow/checkpoint 通过；真实 PG/4C8GB 三轮未执行 |
