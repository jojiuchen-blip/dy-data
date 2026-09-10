# DYDATA-93 管理员分账规则权限增量计划

> **版本**：v1
> **发布日期**：2026-09-10
> **前序版本**：无，独立增量
> **适用范围**：DYDATA-93；DYDATA-92 操作指引另行执行
> **开发模式**：团队协作 / isolated worktree
> **参与角色**：当前 AI 执行 -> 用户审核
> **执行约束**：不更改真实账号角色，不发布真实规则，不触发生产重算
> **目标**：已获 D03 页面权限的普通管理员可以发布 SKU 分账规则
> **需求基线**：Linear DYDATA-93 2026-09-10 用户确认普通管理员可设置、发布，随后明确开始；本计划初稿待审阅
> **上游发现结论**：2026-09-10T08:13:38.313Z，slug=dy-data，canProceed=true；未进入失败分支。API/Schema 存在拆分文件，大文件按相关章节读取。

## 0. 本计划使用指南

先读本计划、看板与子计划。仅处理本权限增量，不修改 DYDATA-87 补算工作树或 DYDATA-91 当前交付记录。

### 0.1 PRD 加载约束

读取 docs/prd/mainprd-dy-data.md 的权限和系统边界；具体发布契约读取 docs/prd/foundation/foundation-api-dy-data/sku-fee-admin.md §5、§9，以及 common-contract.md §5。账号规则以 docs/rules/account-access-control.md 为准。
原最高管理员发布限制由 DYDATA-93 用户确认覆盖；不把财务模块角色等价误推广到所有后台操作。

### 0.2 读前门禁 / AI 自检清单

Linear issue 已存在并进入 In Progress，当前 AI 单一负责。初稿待审阅，不把聊天开工许可伪装为对尚未生成计划的审阅。审阅后同步三处状态，运行 check-plan-consistency.mjs 和 verify-task-context.mjs，再进入实装。

### 0.3 完成前验证门禁

先 git diff --check；权限正负例、既有规则发布回归、完整 pytest 与 Web build；隔离浏览器验证普通管理员发布和最高管理员专用按钮。生产只读 smoke，不使用真实发布验证。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Node.js | 项目锁定版本 | `node -v` |
| Python | 项目依赖可导入 | `python -m pytest --version` |
| Git | 可用 | `git --version` |

## 1. 差距基线

| 差距 | 影响 | 对应任务 | 状态 |
|---|---|---|---|
| 单条发布与导入 commit 依赖 get_current_super_admin | 普通管理员发布被拒绝 | T0.1 | 已静态定位 |
| 页面手动重建入口缺少可见角色判断 | 开放发布后可能继续展示不可用操作 | T0.1 | 待隔离验证 |

## 2. 分工与边界

2026-09-10 用户明确同意发布前整合此前 DYDATA-87 已提交采集修复。仅纳入 aa3373a（完整分页/归属防覆盖）、bab2612（PG并发门禁）、52500ae（已确认推广来源保护测试）；保留 df33f73 的全部线索更新。不纳入另一工作树未提交补算 driver、锁或真实数据修复。整合后重新验证最终代码，并回填两个 issue。

AI 在 codex/dydata-93-admin-rules 独立分支处理代码、测试和证据；人类审核业务边界并验收。
仅替换两类规则发布入口的固定角色要求，保留 get_current_user 页面鉴权。手工多 SKU 当前循环调用单条接口，不另建批量协议。保留幂等、版本、审计、受控入队。
手动重建与 settlement-scope-rules 发布继续最高管理员；不开放其他后台高风险动作。门店角色即使获得 D03 也不得发布。历史 viewer 按账号迁移合同处理，不新增第四种角色。

## 3. 执行阶段

### Phase 0：最小权限发布闭环

**Entry Criteria**：计划审阅通过，Linear 授权不变，独立分支无重叠写入，环境检查通过。
**Exit Criteria**：授权正例、禁止负例和发布不变量回归通过，证据回填；未验收不标记 Done。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T0.1 | [sub-delivery-plan-dydata-93-admin-rules-T0.1-permissions.md](sub-delivery-plan-dydata-93-admin-rules-T0.1-permissions.md) | 进行中 |

## 4. 任务看板

[任务看板](task-kanban-dydata-93-admin-rules.md)

## 5. 发布闸门

- [ ] 用户审阅计划，三处状态一致
- [ ] 真实认证路径测试和隔离页面验证通过
- [ ] git diff --check、完整 pytest、Web build 通过
- [ ] 独立安全复审、PR/CI、部署协调及回滚版本已记录
- [ ] 生产只读 smoke 完成；发布权限变化未被误当作金额验收
- [ ] 用户验收

## 6. 风险与应对

| 风险 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| 全局替换 super admin 依赖 | 越权 | 只改两类发布，反测重建和范围接口 403 | AI | 待验证 |
| 授权 D03 被前端绕过 | 未授权发布 | 真实会话与页面撤销测试，不覆盖认证依赖 | AI | 待验证 |
| 测试发布产生生产数据 | 金额受影响 | 仅隔离种子库发布；生产只读 | AI | 持续 |
| 与其他部署同时修改主线 | 丢失在途修复 | 发布前 fetch、核对 SHA、协调 DYDATA-87 | AI | 待发布 |

## 7. AI 执行示例

审阅后先增加普通管理员发布成功的测试，确认旧实现返回 403，再最小修改两处依赖；随后验证门店、无页面权限、失效会话仍被拒绝。不可直接删除旧负例来让测试通过。

## 8. PRD → 任务反向索引

| PRD / 需求 | Task | 验证 |
|---|---|---|
| DYDATA-93 用户确认；sku-fee-admin §5、§9 | T0.1 | 单条、导入发布与幂等 |
| account-access-control §2、§3、§9 | T0.1 | 页面授权、角色、会话撤销 |
| common-contract §5 | T0.1 | 错误、审计与幂等契约 |
