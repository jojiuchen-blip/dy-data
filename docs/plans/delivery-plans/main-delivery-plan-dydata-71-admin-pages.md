# DYDATA-71 后台页面体验优化主开发计划

> **版本**：v1
> **发布日期**：2026-08-12
> **前序版本**：无
> **适用范围**：`/admin/accounts` 与 `/admin/rules` 现有页面体验优化
> **开发模式**：团队协作（独立 worktree，AI 执行 -> 人审核）
> **参与角色**：AI 执行；用户审核并验收
> **执行约束**：不修改财务板块，不改后端权限与费率契约，不推送或部署
> **目标**：按用户确认的临时看板和 V0.2 视觉规范，完成账号创建复核与分佣规则连续工作流
> **当前需求基线**：Linear `DYDATA-71`，2026-08-12 已确认进入开发
> **上游发现结论**：`canProceed=true`，`slug=dy-data`，扫描时间 `2026-08-12T07:09:07.765Z`；后台页无独立 subprd，交互细节以 DYDATA-71 用户确认记录为补充权威来源

## 0. 本计划使用指南

1. 先读本计划和[任务看板](task-kanban-dydata-71-admin-pages.md)，每次只执行一个“进行中”任务。
2. 再读任务对应的子开发计划、Linear `DYDATA-71`、实际页面/API/测试文件。
3. 使用测试先行；每项行为先写失败测试，再做最小实现并回归。
4. 完成后回填测试证据、foundation 漂移结论和 Linear 验证记录。

### 0.1 PRD 加载约束

- 全局边界读取 `docs/prd/mainprd-dy-data.md` 的“双费用口径、权限、管理端边界”。
- 费率字段与导入语义读取 `docs/prd/foundation/foundation-api-dy-data/sku-fee-admin.md`。
- 账号角色和权限不重新定义，读取 `docs/rules/account-access-control.md`。
- 页面信息架构与交互细节以 Linear `DYDATA-71` 用户确认记录为准。

### 0.2 读前门禁 / AI 自检清单

- [x] Linear `DYDATA-71` 已存在、范围已确认、状态为 In Progress、当前窗口已认领。
- [x] 独立 worktree 基于最新 `origin/main`，未包含财务板块未提交文件。
- [x] V0.2 视觉规范、现有页面、API 客户端、类型和相关测试已定位。
- [x] 当前 Task 在 main plan、kanban、sub plan 三处均为“进行中”。

### 0.3 完成前验证门禁

- `git diff --check`
- 后台页面、设计系统、用户可见文案相关 pytest
- `npm --prefix apps/web run build`
- 账号创建与分佣规则主流程的浏览器检查；不得出现水平溢出或运行时错误
- 仅在用户已要求提交并推送时创建本地 Git commit 并推送当前功能分支；不合并、不部署

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Node.js | >= 18 | `node -v` |
| npm | >= 9 | `npm -v` |
| Python | >= 3.11 | `python --version` |

| 工程目录 | 就绪标识 |
|---|---|
| `apps/web/` | `node_modules/` 存在 |
| `tests/` | `test_frontend_admin_accounts.py` 存在 |

## 1. 差距基线

| 差距 | 优先级 | 影响 | 对应任务 | 状态 |
|---|---|---|---|---|
| 账号长列表与右侧表单共同拉伸，创建前没有信息复核 | P1 | 容易误建账号且提交入口难到达 | T1.1 | 待处理 |
| 分佣规则页存在人工分类、旧单费率和重复发布模块，主流程顺序混乱 | P1 | 费率发布步骤难理解且易误操作 | T1.2 | 待处理 |

## 2. 分工与边界

| 角色 | 职责 |
|---|---|
| AI | 读取契约、编写失败测试、实现页面、运行验证、整理提交和证据 |
| 用户 | 审核已确认方案的正式实现；决定后续是否合并或部署 |

- 不修改账号角色、后端鉴权、费率/导入 API、数据库或财务功能。
- 人工分类从规则页移除；商品口径页的承载方式不在本次实现中扩张。
- 技术判断由 AI 执行 -> 人审核。

## 3. 执行阶段

### Phase 1：账号创建安全与可达性

**Entry Criteria**：T1.1 三处状态一致；现有账号 API 和测试已读取。
**Exit Criteria**：首次提交只打开确认卡；确认后才创建；列表独立滚动；相关测试与 build 通过。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T1.1 | [账号列表独立滚动与创建确认](sub-delivery-plan-dydata-71-admin-pages-T1.1-account-confirmation.md) | 已完成（2026-08-12） |

### Phase 2：分佣规则连续工作流

**Entry Criteria**：T1.1 完成；T1.2 三处状态切换为“进行中”。
**Exit Criteria**：三页签、四步流程、批量导入抽屉、统一发布记录、例外账号与双 SKU 状态子列表可用；旧区块不显示。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T1.2 | [分佣规则页重组与视觉落地](sub-delivery-plan-dydata-71-admin-pages-T1.2-commission-workflow.md) | 进行中 |

## 4. 任务看板

- 看板入口：[task-kanban-dydata-71-admin-pages.md](task-kanban-dydata-71-admin-pages.md)

## 5. 发布闸门

- [x] T1.1、T1.2 的 Verification Method 全部执行且 Evidence 已回填。
- [x] 页面仅复用现有真实 API，未新增或改变后端契约。
- [x] 密码不写日志、不持久化，确认卡默认掩码且关闭后恢复掩码。
- [x] 费率发布仍使用幂等键，批量导入仍保持全量预校验和原子提交。
- [x] 完整 pytest、Web build、视觉/浏览器检查和 `git diff --check` 通过。
- [x] 用户已要求创建本地提交并推送当前功能分支；合并和部署未授权。

## 6. 风险与应对

| 风险 / 依赖 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| 确认卡展示密码 | 敏感信息泄露 | 默认掩码、临时显示、关闭即复位，不记录日志/埋点 | AI -> 人审核 | 受控 |
| 规则页同时存在新旧 API | 错误混用单费率与双费率 | 正式发布只走双费率接口；旧单费率入口不渲染 | AI -> 人审核 | 已验证 |
| 批量选择输入格式不一致 | SKU 漏选或重复 | 支持换行、空格、中英文逗号/分号并自动去重 | AI -> 人审核 | 已验证 |
| 依赖审计存在既有 high 项 | 扩大变更风险 | 本任务不升级依赖；记录为既有风险 | 人类 Owner | 已知 |

## 7. AI 执行示例

1. 执行 T1.1：先为确认卡和独立滚动写失败契约测试，再修改 `AdminAccountsPage.tsx` 与样式并回归。
2. 切换 T1.2：同步三处状态后，先为三页签/四步流程写失败测试，再重组规则页并做浏览器检查。

## 8. PRD → 任务反向索引

| 需求来源 | Requirement ID | Task | 子开发计划 |
|---|---|---|---|
| Linear DYDATA-71 账号管理验收 | DYDATA-71-ACCOUNT | T1.1 | [T1.1](sub-delivery-plan-dydata-71-admin-pages-T1.1-account-confirmation.md) |
| Linear DYDATA-71 分佣规则验收；Foundation SKU 费率 API | DYDATA-71-RULES | T1.2 | [T1.2](sub-delivery-plan-dydata-71-admin-pages-T1.2-commission-workflow.md) |
