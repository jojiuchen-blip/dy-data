# 当前执行计划

> 本文件是当前执行驾驶舱，不复制 Linear Backlog，也不替代后续 S3 正式交付计划。

## 1. 当前阶段

- 套包阶段：`S1 业务需求文档已完成；S0.5 历史项目标准化继续按最新 baseline 缺口路由`
- 当前 Linear issue：`DYDATA-22`；双 ID 账号激活实现与验收已完成，进入主分支同步和 CI/CD 收口。
- 当前正式计划文件组：`docs/plans/delivery-plans/main-delivery-plan-dydata-22-dual-id-activation.md` 及其 T1.1-T1.3 子计划。
- 当前子开发计划：T1.1 前端、T1.2 后端、T1.3 联调与指南均已完成。

## 2. 当前目标

- 将 DYDATA-22 双 ID 激活、重置密码、公共指南和 PDF 产物同步到远端 `main`，并通过 GitHub Actions 与腾讯云部署门禁。

## 3. 进行中任务

- DYDATA-22 已完成本地实现与验收；当前仅执行提交、远端 `main` 同步和 CI/CD 结果核验。

## 4. 下一步任务

- 完成远端同步后，以 Linear 中下一项已确认需求为准；不自动进入未立项开发。

## 5. 完成标准

- 项目类型已由需求方确认为运营型；台账已由 brd-writer 官方脚本初始化，后续决策继续通过脚本维护。
- 适用 P0 字段确认率 100%，冲突为 0，四项前提挑战和七项质量门全部通过。
- 权威 BRD 覆盖四个业务域、角色、痛点、价值、范围、指标、风险和非资金动作边界，并区分用户确认、当前事实、代码线索与历史材料。
- BRD 通过 `ledger-render.mjs save-brd` 落盘，画像、执行驾驶舱、authority map、devlog、baseline 和链接索引完成同步。
- baseline 将 BRD 标记为 `present`，再按最新缺口路由；S1 完成前不进入 S2。
- DYDATA-22 双 ID 激活、重置密码、静态指南和 4 页 PDF 已通过自动化测试、前端构建及桌面/移动端验收。

## 6. 状态与权威边界

- issue 范围、优先级、负责人、状态和验收以 Linear 为准。
- 当前阶段快照以 `project-profile.md` 为准。
- 历史计划只记录当时事实，不反向覆盖本文件或 Linear。
- 本文件只保留当前 issue 和紧邻下一步，不扩写未来 Backlog。

## 7. 本轮验证证据

- 套包版本锁 2.0.0 有效，安装清单 204 个文件可复算。
- 全局治理：0 错误、0 警告；S1 route-check `canEnter=true`，独占交付能力为 `brd-writer`。
- baseline：BRD 已为 `present`，项目画像冲突 0；最新推荐下一能力为 `page-explainer`。
- 项目链接索引：340 个节点、102 条关系、0 issue；已按套包伴随动作复核，当前无需再次重建。
- Linear：DYDATA-20 已写入收口证据并进入 `Done`。
- BRD 台账：`dy-data`，运营型，状态 `DONE`，15 个适用字段已全部锁定、冲突 0；四项前提挑战和七项质量门均已通过，正式 BRD 为 `docs/brd/BRD-dy-data-20260716-1255.md`。
- DYDATA-22：双 ID 同记录核验、两阶段激活、双 ID 重置密码和公共激活指南已完成；PDF 为 4 页，发布产物包含指南 HTML、CSS、图片和 PDF。
