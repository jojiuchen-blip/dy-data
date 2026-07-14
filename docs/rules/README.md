# dy-data 宿主专项规则入口

本目录是 dy-data 专项开发规则的唯一权威落点，但 DYDATA-6 只建立入口，不在这里复制套包默认规则。

当前套包默认规则包含 Java、Vue、MySQL 等假设，直接生成会与 dy-data 的 FastAPI、React/Vite、PostgreSQL、pytest 和现有部署方式冲突。因此在 DYDATA-7 完成适配前：

- 不从套包默认规则直接复制 `backend-tasks.md`、`frontend-tasks.md`、`database-tasks.md` 等文件。
- 实现任务继续遵守 `AGENTS.md`、当前代码配置、相关测试和 `docs/governance/authority-map.md` 声明的证据入口。
- 普通新功能暂停进入开发；生产紧急修复沿用 `AGENTS.md` 的 Linear、风险和验证例外通道。
- DYDATA-7 将补齐并验证 FastAPI、React/Vite、PostgreSQL、测试、Linear/计划边界和开发日志落点规则。
