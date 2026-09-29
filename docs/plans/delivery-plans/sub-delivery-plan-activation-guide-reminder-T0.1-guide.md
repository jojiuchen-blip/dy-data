# T0.1 激活提醒与导出资格提示

主计划：[激活指南提醒](main-delivery-plan-activation-guide-reminder.md)。

#### T0.1 激活提醒与指南同步

**Requirement ID**：DYDATA-101。

**PRD 双链·读**：`mainprd-dy-data.md` 产品背景；增量需求见 DYDATA-101。

**核心逻辑**：进入激活模式显示可跳过的指南 Dialog；本次流程不反复弹出。指南新标签页公开访问。第五部分导出步骤强调账号类型及认证状态，保留现有子机构门店号/区域号资格，HTML/PDF同步。

**核心文件**：`apps/web/src/pages/AuthPage.tsx`、`apps/web/public/account-activation-guide/index.html`、`tests/test_frontend_auth_guidance.py`；独立指南目录同步。

**完成标准**：直接访问及切换弹出，关闭/核验/第二屏不重复，重新进入再次提示；指南无需登录；手机/桌面明暗主题无溢出；HTML/PDF提示一致。

**Verification Method**：pytest 前端规范与引导测试，Web build，Playwright 模式切换、弹窗焦点、新标签页、窄屏测试；PDF文本检查。

**Evidence**：`docs/devlog/20260929_activation_guide_reminder.md`。

**Failure Handling**：失败不发布，不绕过认证、不修改生产账号。

**完成收尾：状态同步**：用户已验收并授权部署，生产4662d6b2公网验证通过；验证事实回写 Linear、日志与计划。

**Owner**：Codex

**前置**：无

**状态**：已完成
