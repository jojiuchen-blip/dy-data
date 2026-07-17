# T0.1 Demo Sub Delivery Plan

## 任务来源

- 主开发计划：[main-delivery-plan-demo.md](main-delivery-plan-demo.md)
- 任务看板：[task-kanban-demo.md](task-kanban-demo.md)

#### T0.1 实现演示任务

**Requirement ID**：REQ-DEMO-001

**PRD 双链·读**：
- `mainprd-demo.md` §1

**核心逻辑**：
- 根据 PRD 处理演示任务。

**核心文件**：
- `src/demo.js`

**完成标准**：
- 运行 `node src/demo.js` 输出 demo-ok。

**Verification Method**：
- 执行 `node src/demo.js`。

**Evidence**：
- `logs/demo-task.md`

**Failure Handling**：
- PRD 或核心文件定位不到时阻塞。

**完成收尾：状态同步**：
- 本 Task 完成实现、验证和 foundation 漂移判断后，必须把 Task 完成事实、验证证据、完成日期、foundation 漂移结论和建议下一 Task 提交给 `ai-project-manager`。
- 由 `ai-project-manager` 调度 `delivery-planner` 同步 `main-delivery-plan-<slug>.md`、`task-kanban-<slug>.md` 和当前 `sub-delivery-plan-<slug>-<TaskID>-<short-name>.md` 的状态。
- 同步后重新运行 `node <suite-path>/tools/route-check.mjs <host> --target-stage S4 --json`（route-check 是套件的阶段门禁检查工具；`<suite-path>` 指套件根目录：源码仓库联调时为 `project-manager-suite/`，安装到宿主后为 `.agent/project-manager-suite/`，命令默认在宿主项目根目录执行），确认正式开发计划文件组三者一致；未通过前不得宣称本 Task 已完成。

**Owner**：AI 执行 -> 人审核

**前置**：无

**状态**：待审阅
