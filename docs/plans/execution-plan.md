# 当前执行计划

> 本文件是当前执行驾驶舱，不复制 Linear Backlog，也不替代后续 S3 正式交付计划。

## 1. 当前阶段

- 套包阶段：`S1 权威 BRD 已完成；S0.5 项目级 page-delivery 已完成，刷新后的 baseline 推荐 PAGE_EXPLAINER`，本轮不虚构进入 S3/S4。
- 当前 Linear issue：无进行中事项；`DYDATA-37` 已完成，`DYDATA-36` 仍为 Backlog。
- 当前子开发计划：无；本轮补齐页面交付元数据、验收截图和索引，不修改业务代码。
- 当前正式计划文件组：无；项目尚未进入 S3，需先完成 PAGE_EXPLAINER 和 DYDATA-36。
- 紧邻顺序：补齐 14 个现有页面的 `PAGE_EXPLAINER` -> `DYDATA-36` 线索中心 BRD V1.0 及必需规格 -> `DYDATA-34` 全面下线旧线索分配引擎。
- 关联需求：`DYDATA-35` 门店地理与 POI 数据质量闭环。

## 2. 当前目标

- 固化现有 14 个页面的可运行交付基线，让下游 PAGE_EXPLAINER 能从同一套 V0.2 页面、路由和 mock 数据开始工作。

## 3. 进行中任务

- 无进行中实现任务；等待以独立事项进入 PAGE_EXPLAINER。

## 4. 下一步任务

- 按刷新后的路由由 `page-explainer` 补齐 14 个现有页面的流程、角色、权限和交互语义。
- 进入 `DYDATA-36`，形成线索中心 BRD V1.0 及专项 PAGE_EXPLAINER、FOUNDATION、PRD 和正式交付计划。
- S4 门禁通过后再进入 `DYDATA-34`，执行旧引擎下线和隔离 PostgreSQL 验收。

## 5. 完成标准

- `page-delivery-dy-data.md` 覆盖全部 14 个页面组件、实际路由、绝对文件路径和可复现启动命令。
- 桌面与 390px 视口能打开全部有效页面路由；认证页三种模式可渲染。
- V0.2 仍是唯一运行时设计权威，生成式设计建议不得覆盖现有 token。
- baseline 刷新后路由目标为 `page-explainer`，前置检查通过且 `canEnter=true`。
- 不修改业务代码，不执行 DYDATA-34 的旧引擎删除。

## 6. 状态与权威边界

- issue 范围、优先级、负责人、状态和验收以 Linear 为准。
- 当前阶段快照以 `project-profile.md` 为准。
- 历史计划只记录当时事实，不反向覆盖本文件或 Linear。
- 本文件只保留当前 issue 和紧邻下一步，不扩写未来 Backlog。

## 7. 本轮验证证据

- 项目管理套包已升级到 `2.0.1`；完整测试 122 项通过，协议一致性 0 错误、0 警告。
- 宿主套包锁校验通过，内容哈希为 `737ff2de9242febf1b8da301138a1e095c6b881f40adaa7aa4ca2b2cb9077bb9`。
- 页面交付：14 个页面组件、17 个 demo 运行路由、3 个认证模式；桌面与移动根节点均无横向溢出。
- 前端构建通过；V0.2 设计系统测试 25 项通过。
- 真实 `dy-data` 路由结果：`canEnter=true`，目标能力为 `page-explainer`，缺失前置产物为空。
- 项目链接索引已刷新为 466 个节点、145 条边；发现 16 条历史 QA 截图或旧计划路径坏链，本轮不改写历史材料。
- Linear：`DYDATA-37` 已完成；`DYDATA-34` 已退回 Backlog，并由 `DYDATA-36` 阻塞。
- 业务代码尚未修改；DYDATA-34 继续等待 DYDATA-36 和 S4 前置产物。
