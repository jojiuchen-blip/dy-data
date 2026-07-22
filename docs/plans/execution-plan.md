# 当前执行计划

> 本文件是当前执行驾驶舱，不复制 Linear Backlog，也不替代后续 S3 正式交付计划。

## 0. 当前增量交付：DYDATA-45

- 隔离 worktree `feat/dydata-45-agent-connect` 已完成腾讯云测试环境 Agent 一句话接入层；Linear `DYDATA-45` 已进入 In Review。这里的 `production` 专指未来尚未部署的企业内网服务器版本。
- 正式计划入口：[`main-delivery-plan-dydata-45-test-agent-connect.md`](delivery-plans/main-delivery-plan-dydata-45-test-agent-connect.md)，T1.1、T1.2、T2.1、T2.2、T3.1 均已完成，等待人类 Owner 最终审核。
- 运行时代码 `cab6aec` 已合入远端 `main` 并由 GitHub Actions run `29934737788` 成功部署腾讯云；最终安全复审为 `ALLOW`，Critical/Important/Minor 均为 0。全量 916 项通过、2 项 opt-in PostgreSQL 用例另在真实 PostgreSQL 连续 5 轮通过；Web production build、API/Web 镜像、空库迁移、Compose、两套 Nginx、锁定依赖审计、增量 Bandit 与公开 smoke 均通过。
- 独立 Agent 黑盒重试 verdict 为 `PASS`：CLI 0.3.0 与官方 Node MCP SDK 均完成用户浏览器授权；测试账号仅返回 3 家授权门店，默认/显式日期统计口径成立，未授权门店整单拒绝，两通道的门店数、行数和完整脱敏聚合一致。非阻断观察为顶层 `--help` / `--version` 不受支持，机器入口 `commands --json` / `version --json` 正常。
- 权威规格：[`2026-07-22-dydata-45-test-agent-connect-design.md`](../superpowers/specs/2026-07-22-dydata-45-test-agent-connect-design.md)。本增量仅覆盖当前腾讯云测试环境；未来企业内网生产版由 DYDATA-46 对入口、OAuth、keyring、部署、文档和 smoke 做彻底切换。
- 本增量不改变下文 DYDATA-41 线索中心 Foundation 的业务基线与依赖顺序；后续仅在 `DYDATA-46` 生产 Release Gate 中切换企业内网入口、OAuth、keyring、部署、文档和 smoke，禁止复用测试凭据。

## 1. 当前阶段

- 套包阶段：`S2 线索中心 FOUNDATION Phase 4`；术语表与 Schema 已确认，API 契约已生成并等待业务确认，当前尚未进入 Phase 5、PRD、S3/S4。
- 当前 Linear issue：`DYDATA-41` 建立线索中心 FOUNDATION 技术地基，状态为 In Progress；`DYDATA-36` 已完成并关闭。
- 当前子开发计划：无；本轮只建立线索中心技术规格，未修改业务代码。
- 当前正式计划文件组：无；进入代码实施前，仍需由下游能力补齐 FOUNDATION、PRD 和正式交付计划。
- 紧邻顺序：`DYDATA-41` FOUNDATION -> `DYDATA-42` PRD -> `DYDATA-43` 正式交付计划与 S4 门禁 -> `DYDATA-34` 全面下线旧线索分配引擎。
- 关联需求：`DYDATA-35` 门店地理与 POI 数据质量闭环。

## 2. 当前目标

- 以已冻结的《线索中心业务模型 V1.0》为输入，先冻结术语，再依次补齐 Schema、API、运行交付、产品细则和正式交付计划。

## 3. 进行中任务

- DYDATA-41 FOUNDATION Phase 4 进行中；API 索引及 6 份拆分契约已生成，23 张目标单表定义已回填使用接口，等待用户确认后进入 Phase 5。

## 4. 下一步任务

- 用户确认 FOUNDATION API；未确认前不进入 Phase 5。
- FOUNDATION Phase 5 按已确认 Schema 与 API 继续定义状态迁移、定时任务、权限安全、迁移和运行方案。
- PRD 按 BRD 定义页面字段、操作反馈、异常状态、角色交互和逐项验收条件。
- 正式交付计划把追踪矩阵中的 `部分实现`、`未实现` 和 `应删除` 映射到 Linear、代码、测试和上线门禁；S4 门禁通过后进入 `DYDATA-34`。

## 5. 完成标准

- 每个实体、状态、策略、时间规则、指标和权限只有一个明确口径。
- 第 0 轮、策略阶段和实际第 N 轮等历史术语歧义全部消除。
- DYDATA-8～17 均映射到 BRD 条款、实现位置、自动化测试和浏览器验收场景。
- 待分配、双第 1 轮、未知枚举、CORS、性能和退款断点均有明确验收门槛。
- 用户逐章确认并冻结 V1.0；本轮不修改业务代码，不执行 DYDATA-34 的旧引擎删除。

## 6. 状态与权威边界

- issue 范围、优先级、负责人、状态和验收以 Linear 为准。
- 当前阶段快照以 `project-profile.md` 为准。
- 历史计划只记录当时事实，不反向覆盖本文件或 Linear。
- 本文件只保留当前 issue 和紧邻下一步，不扩写未来 Backlog。

## 7. 本轮验证证据

- 项目管理套包锁校验通过，版本 `2.0.1`，内容哈希为 `737ff2de9242febf1b8da301138a1e095c6b881f40adaa7aa4ca2b2cb9077bb9`。
- PAGE_EXPLAINER 已覆盖 8 条流程和 57 条交互语义，全部 `locked`；结算中心相关内容仅作为当前版本历史基线。
- V0.2 设计系统文档测试 25 项通过；交互卡片与机读表 57/57 一致。
- baseline 已刷新并识别 PAGE_EXPLAINER 为 `present`，维护文档下一缺口为 FOUNDATION。
- 项目链接索引已刷新为 470 个节点、154 条边；仍有 16 条历史 QA 截图或旧计划路径坏链，本轮不改写历史材料。
- Linear：`DYDATA-36` 已补充交付证据并关闭；`DYDATA-41` 已进入 In Progress，`DYDATA-42`、`DYDATA-43` 按顺序阻塞，`DYDATA-34` 继续等待 S4 门禁。
- 《线索中心业务模型 V1.0》已生成，BRD 决策台账为 `DONE`，包含截至 2026-07-21 的现状追踪矩阵。
- FOUNDATION 术语表已生成，共 212 行，明确主池、状态、池位置、策略步骤、真实轮次、跟进动作、权限和指标的统一含义。
- FOUNDATION Schema 已生成：1 个索引、23 个单表定义，覆盖原始证据、完整主池、真实轮次、规则版本、评分、候选决策、总部池、指标事实和安全审计；本阶段未生成 DDL 或修改业务代码。
- FOUNDATION API 已生成：1 个索引、6 份拆分契约，覆盖公共响应与错误、自然日筛选、线索查询与联系方式、跟进与轮次、规则与门店组、正式分配与总部池、任务安全及一次性迁移；23/23 单表文档已回填使用接口。
- API 延续宿主项目 `/api/v1`、snake_case 与 `data/meta` 契约；完整手机号查看、复制和明文导出均独立鉴权并审计，正式分配仅允许内部任务触发，试运行不写正式轮次。
- 全量测试 516 项通过；仅出现现有 Alembic/SQLite 弃用警告，未发现本轮文档变更导致的回归。
- S2 路由检查仍推荐停留 S2；当前 `canEnter=false` 来自项目画像三个既有页面任务字段待确认，不是 Foundation API 结构或内容校验错误，须在后续页面/PRD 门禁前补齐。
- 业务代码尚未修改；DYDATA-34 继续等待 FOUNDATION、PRD、正式交付计划和 S4 门禁。
