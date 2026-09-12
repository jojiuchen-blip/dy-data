# T0.1 浏览器运行可靠性

- 主开发计划：[main-delivery-plan-dydata-95-browser.md](main-delivery-plan-dydata-95-browser.md)
- 任务看板：[task-kanban-dydata-95-browser.md](task-kanban-dydata-95-browser.md)

#### T0.1 浏览器运行可靠性

**Requirement ID**：DYDATA-95

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` §1

**核心逻辑**：等待真实X连接；VNC和窗口管理器有界恢复；CDP、VNC与WebSocket握手共同决定健康。

**核心文件**：deploy/browser/；deploy/compose.yaml；tests/test_browser_runtime.py；docs/runbook.md。

**完成标准**：延迟就绪不抢跑；VNC退出自动恢复且Chromium不重启；重试耗尽明确失败；任一关键连接故障探针失败；相关测试通过。

**Verification Method**：pytest、Linux隔离容器运行验证、git diff --check。

**Evidence**：生产XOpenDisplay失败、5900拒绝连接；恢复后RFB与HTTP101通过。

**Failure Handling**：有限重试，保留日志及不健康状态；停止发布；不清理profile或制造生产登录失败。

**Owner**：AI

**前置**：已授权且绑定采集恢复。

**状态**：进行中（已部署，待用户验收）

**完成收尾：状态同步**：Linear、计划、运行手册与开发日志记录验证及未发布边界；检查foundation漂移。
