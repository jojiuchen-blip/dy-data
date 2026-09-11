# T0.1 Ranking source identity Sub Delivery Plan

## 任务来源

- 主开发计划：[main-delivery-plan-ranking-source-identity.md](main-delivery-plan-ranking-source-identity.md)
- 任务看板：[task-kanban-ranking-source-identity.md](task-kanban-ranking-source-identity.md)

#### T0.1 补齐只读订单归属核验字段

**Requirement ID**：LOCAL-RANKING-IDENTITY-001

**PRD 双链·读**：
- `mainprd-dy-data.md` §1

**核心逻辑**：
- 保留现有最高管理员、分页、日期范围和只读约束；补充订单/账号/绑定的同名匹配键及绑定起止时间，禁止返回昵称原文。用户已授权继续核验、合并和部署。Linear DYDATA 当前连接不可用，记录本地需求草稿，不在其他团队建票。

**核心文件**：
- `apps/api/dy_api/ranking_source_evidence.py`
- `tests/test_ranking_source_evidence.py`

**完成标准**：
- 匹配键跨订单和绑定一致；空名称不产生匹配键；不同名称保持不同；原文昵称与 raw_payload 不输出；起止时间保留原始值；所有现有访问控制、分页和日期测试通过。

**Verification Method**：
- 执行 `pytest tests/test_ranking_source_evidence.py`；检查响应仅含允许字段。

**Evidence**：
- `docs/devlog/20260911_ranking_source_identity.md`

**Failure Handling**：
- PRD 或核心文件定位不到时阻塞。

**完成收尾：状态同步**：
- 本 Task 完成实现、验证和 foundation 漂移判断后，必须把 Task 完成事实、验证证据、完成日期、foundation 漂移结论和建议下一 Task 提交给 `ai-project-manager`。
- 由 `ai-project-manager` 调度 `delivery-planner` 同步 `main-delivery-plan-<slug>.md`、`task-kanban-<slug>.md` 和当前 `sub-delivery-plan-<slug>-<TaskID>-<short-name>.md` 的状态。
- 同步后重新运行 `node <suite-path>/tools/route-check.mjs <host> --target-stage S4 --json`（route-check 是套件的阶段门禁检查工具；`<suite-path>` 指套件根目录：源码仓库联调时为 `project-manager-suite/`，安装到宿主后为 `.agent/project-manager-suite/`，命令默认在宿主项目根目录执行），确认正式开发计划文件组三者一致；未通过前不得宣称本 Task 已完成。

**Owner**：AI 执行 -> 人审核

**前置**：无

**状态**：进行中
