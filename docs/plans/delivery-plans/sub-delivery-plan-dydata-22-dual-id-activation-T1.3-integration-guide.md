# T1.3 联调、独立指南与真实截图

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-22-dual-id-activation.md](main-delivery-plan-dydata-22-dual-id-activation.md)
- 任务看板：[task-kanban-dydata-22-dual-id-activation.md](task-kanban-dydata-22-dual-id-activation.md)

#### T1.3 完成双 ID 激活联调并同步 HTML/PDF 指南

**Requirement ID**：DYDATA-22-GUIDE

**PRD 双链·读**：
- Linear `DYDATA-22` 的“独立指南入口”和“验收标准”章节
- `../account-activation-guide/index.html`
- `../account-activation-guide/docs/superpowers/specs/2026-07-16-dual-id-account-activation-design.md`

**核心逻辑**：
- 将独立静态指南以单独目录纳入 Web 构建产物，线上同源路径固定为 `/account-activation-guide/index.html`；该页面必须脱离 SPA 登录门禁，未登录用户可直接访问。
- 使用实装后的真实账号激活第一屏和第二屏生成桌面截图，替换指南中旧表单示意图。
- HTML 与 PDF 必须说明先核验双 ID、再设置账号密码的两阶段流程，以及两个 ID 右侧问号帮助卡的使用方式；不再要求认证主体全称或显示名称。
- HTML 与 PDF 的忘记密码说明同步改为“双 ID 核验后设置新密码”，不再出现认证主体全称。
- 完成前后端真实联调，验证同记录成功、跨记录失败及错误反馈可恢复。

**核心文件**：
- `apps/web/public/account-activation-guide/`
- `apps/web/src/pages/AuthPage.tsx`
- `../account-activation-guide/index.html`
- `../account-activation-guide/styles.css`
- `../account-activation-guide/assets/`
- `../account-activation-guide/output/pdf/account-activation-guide.pdf`

**完成标准**：
- Web 构建产物中存在 `/account-activation-guide/index.html` 及其 CSS、图片资源。
- 未登录进入激活模式后，点击指南按钮在新标签打开同源指南且无 404，不触发 `/auth/me`。
- 指南 HTML 与 PDF 使用真实第一屏、第二屏截图；第一屏展示两个 ID 和“激活状态核验”，第二屏只展示账号名、密码和确认密码。
- 指南字段获取说明与页面帮助卡一致，明确从认证成功的子机构经营号导出数据中获取两个字段。
- PDF 为 4 页，常见问题展开，后两部分保持合并排版。
- 桌面和移动端无字段溢出、卡片错位或按钮不可见。
- 端到端验证证明同记录组合激活成功、跨记录组合失败。

**Verification Method**：
- 构建 Web 后检查 `apps/web/dist/account-activation-guide/index.html` 及关联资源存在。
- 使用 Playwright 从登录页打开指南新标签，检查 HTTP/文件加载和关键双 ID 文案。
- 使用 Playwright 截取真实激活页桌面/移动端和指南页面。
- 运行静态指南测试并重新生成 PDF，检查页数与关键文案。
- 运行前后端相关测试和 Web build 作为最终回归。

**Evidence**：
- `<projectRoot>/output/playwright/dydata-22-activation-desktop.png`
- `<projectRoot>/output/playwright/dydata-22-activation-mobile.png`
- `<projectRoot>/output/playwright/dydata-22-guide-new-tab.png`
- `<projectRoot>/output/playwright/dydata-22-guide-mobile.png`
- `../account-activation-guide/output/pdf/account-activation-guide.pdf`
- 25 项账号相关 pytest、17 项静态指南测试和 Web build 均通过；PDF 为 4 页且源码、公共资源、构建产物哈希一致。

**Failure Handling**：
- 若 Railway 构建上下文无法访问兄弟目录，必须将可发布静态资产同步到 `apps/web/public/account-activation-guide/`，不得依赖部署机外部路径。
- 若真实截图包含敏感账号数据，使用空表单状态或脱敏测试数据重新生成。
- 若 PDF 页数或布局回归，阻塞发布并修正打印样式，不以仅 HTML 正常作为完成依据。

**完成收尾：状态同步**：
- 本 Task 完成实现、验证和 foundation 漂移判断后，必须把 Task 完成事实、验证证据、完成日期、foundation 漂移结论和建议下一 Task 提交给 `ai-project-manager`。
- 由 `ai-project-manager` 调度 `delivery-planner` 同步主开发计划、任务看板和本子开发计划状态。
- 同步后重新运行 `node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S4 --json`；未完成状态同步前不得标记本 Task 已完成。

**Owner**：AI 执行 -> 人审核

**前置**：T1.1、T1.2

**完成记录**：2026-07-16 完成双 ID 前后端联调、公共静态指南、真实脱敏截图、4 页 PDF、桌面与 390px 移动端验收。未发现新增 foundation 漂移，沿用已登记的 `S4-FCR-001`。

**状态**：已完成（2026-07-16）
