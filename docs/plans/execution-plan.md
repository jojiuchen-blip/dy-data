# 当前执行计划

> 本文件是当前执行驾驶舱，不复制 Linear Backlog，也不替代后续 S3 正式交付计划。

## 1. 当前阶段

- 套包阶段：`S0.5 既有项目 baseline`
- 当前 Linear issue：`DYDATA-7`
- 当前正式计划文件组：尚未生成；`docs/plans/delivery-plans/` 在 S3 后接管正式交付计划。
- 当前子开发计划：无；DYDATA-7 已完成并通过用户验收。

## 2. 当前目标

- DYDATA-7 已完成：中途接入治理套包的 dy-data 已具备可长期执行的宿主规则和可信项目入口；套包脚本支持 `docs/devlog/`，文档覆盖经营与结算、线索运营、后台管理和数据平台全貌，项目画像不再继承过期 README 的狭窄定位。

## 3. 进行中任务

- 无；DYDATA-7 的实现、验证和用户验收均已完成。

## 4. 下一步任务

- 另行建立 S0.5 文档补齐需求，按 BRD → 页面说明 → FOUNDATION → PRD 的缺口顺序推进。
- 每个新需求继续以 Linear 为生命周期权威，并在本文件中只保留当前 issue 与紧邻下一步。

## 5. 完成标准

- 六类 `docs/rules/` 文件存在并符合 FastAPI / React / PostgreSQL / pytest 实际栈。
- `docs/devlog/` 可由 `project-profile.md` 配置，`/logs/` 仍只承载被忽略的运行日志。
- README、项目产品介绍书、架构、API、运行和部署文档不再把项目描述为仅有结算或静态 HTML。
- 项目画像明确四个业务域、证据边界、真实入口和 S0.5 缺口。
- 文档不含真实生产项目 ID、主机地址或固定线上 URL。
- 套包测试、锁校验、协议一致性、全局文件校验、路由、pytest、前端构建和 `git diff --check` 全部通过。

## 6. 状态与权威边界

- issue 范围、优先级、负责人、状态和验收以 Linear 为准。
- 当前阶段快照以 `project-profile.md` 为准。
- 历史计划只记录当时事实，不反向覆盖本文件或 Linear。
- 本文件只保留当前 issue 和紧邻下一步，不扩写未来 Backlog。

## 7. 本轮验证证据

- 标准套包：`119 passed`；版本锁有效，协议一致性 0 错误、0 警告。
- 全局治理：0 错误、0 警告；devlog 解析为 `docs/devlog/`；S0.5 路由可进入。
- 宿主测试：`472 passed`；31 条为现有 Alembic / SQLite 弃用警告，无测试失败。
- 前端：TypeScript 检查和 Vite 生产构建通过。
- baseline：14 个页面、63 个 API 端点、37 个模型定义、17 个迁移；画像冲突 0。
