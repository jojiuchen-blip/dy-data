# T1.1 双 ID 激活前端交互与指南入口

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-22-dual-id-activation.md](main-delivery-plan-dydata-22-dual-id-activation.md)
- 任务看板：[task-kanban-dydata-22-dual-id-activation.md](task-kanban-dydata-22-dual-id-activation.md)

#### T1.1 实现两阶段双 ID 激活表单与独立指南入口

**Requirement ID**：DYDATA-22-FE

**PRD 双链·读**：
- Linear `DYDATA-22` 的“前端交互”和“独立指南入口”章节
- `../account-activation-guide/docs/superpowers/specs/2026-07-16-dual-id-account-activation-design.md`

**核心逻辑**：
- 激活容器分为两屏。第一屏从上到下只包含必填 `账户所属 ID`、必填 `所属账户关联 POI ID` 和主按钮“激活状态核验”。
- 用户点击“激活状态核验”后调用后端状态核验接口：未精确匹配时显示“账户所属ID和所属账户关联POI ID不正确”；匹配但已有密码时显示“账户已激活过，需要前往账户登录”，并提供“前往账户登录”操作；匹配且未激活时进入第二屏。
- 第二屏只要求账号名、密码和确认密码。账号名仅接受数字和英文字母，沿用现有长度约束；不再要求显示名称，后端默认使用门店名称。
- 第二屏允许返回第一屏修改两个 ID，返回时保留已输入的两个 ID，但不得保留密码。
- 忘记密码也采用两屏双 ID 流程。第一屏输入账户所属 ID 与所属账户关联 POI ID：`activated` 进入第二屏设置新密码；`invalid` 显示双 ID 不正确；`ready` 提示“账户尚未激活，请先完成账号激活”并提供前往账号激活入口。
- 忘记密码第二屏只包含密码和确认密码，不修改账号名或显示名称；激活和忘记密码都不再渲染认证主体全称。
- 第一屏两个字段标签右侧各放置 Solar 问号图标按钮。点击任一按钮，在桌面端激活容器旁显示帮助卡；移动端在字段组下方显示同一内容。帮助卡说明：进入抖音来客的【店铺管理】-【抖音号管理】-【子机构经营号】，若无子机构经营号先创建并完成认证，再点击【导出数据】，从对应记录获取【账户所属id】和【所属账户关联poi_id】。
- 在激活模式提供“查看账号激活指引”入口，新标签打开同源 `/account-activation-guide/`。
- 两屏共用原登录组件的位置、宽度和视觉体系，切换和帮助卡出现时不得推动主容器位置或造成桌面端、移动端内容溢出。

**核心文件**：
- `apps/web/src/pages/AuthPage.tsx`
- `apps/web/src/api/client.ts`
- `apps/web/src/types/dashboard.ts`
- `apps/web/src/styles.css`
- `tests/test_frontend_auth_guidance.py`

**完成标准**：
- 激活模式不再渲染或提交 `certified_subject_name`。
- 第一屏只提交 `external_account_id`（账户所属 ID）与 `poi_id`（所属账户关联 POI ID）进行状态核验，两个字段未填写时“激活状态核验”不可提交。
- 第一屏对后端三种状态分别显示约定错误、登录引导或进入第二屏，且核验请求期间按钮进入加载状态并防止重复提交。
- 第二屏不渲染显示名称；账号名不符合 `^[A-Za-z0-9]+$` 时在字段旁显示明确错误并禁止提交。
- 最终激活请求提交两个 ID、账号名、密码和确认密码；不得仅凭前端已通过状态完成激活。
- 点击两个问号图标均能显示字段获取帮助卡，图标按钮有可访问名称和完整键盘焦点状态。
- 忘记密码第一屏提交两个 ID 做状态核验，第二屏只提交两个 ID、密码和确认密码；页面不再出现认证主体、账号名或显示名称字段。
- 忘记密码仅在核验状态为 `activated` 时进入第二屏；`ready` 状态必须引导到账号激活。
- 指南按钮使用新标签打开 `/account-activation-guide/`，包含可访问名称和安全的 `rel` 属性。
- 前端指导测试先因旧字段/缺少新入口失败，实装后通过。
- `npm run build --workspace apps/web` 或项目等价 Web 构建命令通过。

**Verification Method**：
- 先运行 `pytest tests/test_frontend_auth_guidance.py -q` 并记录预期失败。
- 实装后重跑 `pytest tests/test_frontend_auth_guidance.py -q`。
- 在 `apps/web/` 执行 `npm run build`。
- 三种真实核验状态、桌面和移动端视觉及新标签入口统一在 T1.3 的前后端联调中使用 Playwright 验证，避免用临时假接口替代真实证据。

**Evidence**：
- `python -m pytest tests/test_frontend_auth_guidance.py -q`：4 passed（2026-07-16）。
- `apps/web` 下 `npm run build`：TypeScript 检查和 Vite 构建退出码 0（2026-07-16）。
- 桌面与移动端截图按主计划由 T1.3 生成。

**Failure Handling**：
- 若激活与重置类型无法在现有 API 客户端中分离，先阻塞并明确最小类型拆分；不得让重置请求携带账号名、显示名称或认证主体全称。
- 若状态核验接口只返回自由文本而无法稳定区分三种状态，先调整为受控状态枚举，不在前端解析错误文案。
- 若指南路径无法进入 Web 构建产物，不临时改成外部绝对链接，转入 T1.3 处理静态发布结构。
- 若现有视觉 token 与新增字段冲突，以保持登录卡片位置和响应式稳定为优先，提交人类 Owner 审核。

**完成收尾：状态同步**：
- 本 Task 完成实现、验证和 foundation 漂移判断后，必须把 Task 完成事实、验证证据、完成日期、foundation 漂移结论和建议下一 Task 提交给 `ai-project-manager`。
- 由 `ai-project-manager` 调度 `delivery-planner` 同步主开发计划、任务看板和本子开发计划状态。
- 同步后重新运行 `node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S4 --json`；未完成状态同步前不得标记本 Task 已完成。

**Owner**：AI 执行 -> 人审核

**前置**：无

**状态**：已完成（2026-07-16）
