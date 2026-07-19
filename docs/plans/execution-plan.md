# 当前执行计划

> 本文件是当前执行驾驶舱，不复制 Linear Backlog，也不替代后续 S3 正式交付计划。

## 1. 当前阶段

- 套包阶段：`S1 权威 BRD 已完成；S0.5 历史项目标准化继续按 baseline 缺口路由`，本轮不虚构进入 S3/S4。
- 当前 Linear issue：无进行中事项；`DYDATA-37` 已完成，下一项为 `DYDATA-36`。
- 当前子开发计划：无；本轮只修改项目管理套包、回归测试和宿主套包锁，不修改业务代码。
- 当前正式计划文件组：无；项目尚未进入 S3，需先完成页面交付物、baseline 刷新和 DYDATA-36。
- 紧邻顺序：补齐 `page-delivery` 并刷新 baseline -> `DYDATA-36` 线索中心 BRD V1.0 及必需规格 -> `DYDATA-34` 全面下线旧线索分配引擎。
- 关联需求：`DYDATA-35` 门店地理与 POI 数据质量闭环。

## 2. 当前目标

- 当 baseline 推荐 `page-explainer` 时，先验证 BRD 和 `page-delivery` 是否存在；缺失时禁止错误放行，并路由到对应补件能力。

## 3. 进行中任务

- 为 BRD 缺失、`page-delivery` 缺失和前置齐备三种情况建立路由回归测试。
- 将验证通过的套包补丁版本安装回宿主，并校验版本锁、全局文件和真实项目路由结果。

## 4. 下一步任务

- 按修复后的路由先由 `page-designer` 补齐 `page-delivery`，再刷新 baseline。
- 进入 `DYDATA-36`，形成线索中心 BRD V1.0 及后续 PAGE_EXPLAINER、FOUNDATION、PRD 和正式交付计划。
- S4 门禁通过后再进入 `DYDATA-34`，执行旧引擎下线和隔离 PostgreSQL 验收。

## 5. 完成标准

- 缺少 BRD 时恢复到 `brd-writer`；缺少 `page-delivery` 时恢复到 `page-designer`。
- 硬前置产物不完整时 `canEnter=false`，不得通过维护或技术债快速路径绕过治理门禁。
- 前置产物完整时仍可按 baseline 进入 `page-explainer`，不破坏既有正确路径。
- 套包测试、协议一致性、宿主版本锁和真实 `dy-data` 路由验证全部通过。
- 不修改业务代码，不执行 DYDATA-34 的旧引擎删除。

## 6. 状态与权威边界

- issue 范围、优先级、负责人、状态和验收以 Linear 为准。
- 当前阶段快照以 `project-profile.md` 为准。
- 历史计划只记录当时事实，不反向覆盖本文件或 Linear。
- 本文件只保留当前 issue 和紧邻下一步，不扩写未来 Backlog。

## 7. 本轮验证证据

- 项目管理套包已升级到 `2.0.1`；完整测试 122 项通过，协议一致性 0 错误、0 警告。
- 宿主套包锁校验通过，内容哈希为 `737ff2de9242febf1b8da301138a1e095c6b881f40adaa7aa4ca2b2cb9077bb9`。
- 真实 `dy-data` 路由结果：`canEnter=false`，恢复能力为 `page-designer`，缺失前置产物为 `page-delivery`。
- Linear：`DYDATA-37` 已完成；`DYDATA-34` 已退回 Backlog，并由 `DYDATA-36` 阻塞。
- 业务代码尚未修改；DYDATA-34 继续等待 DYDATA-36 和 S4 前置产物。
