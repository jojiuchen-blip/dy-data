# T0.3 回溯更正榜单区域

## 任务来源

- [main-delivery-plan-dydata114.md](main-delivery-plan-dydata114.md)
- [task-kanban-dydata114.md](task-kanban-dydata114.md)

#### T0.3 榜单历史区域纠错

**Requirement ID**：DYDATA-114

**PRD 双链·读**：
- `docs/api/dashboard-publications.md` 发布与读取协议
- `docs/api/ranking-lifecycle.md` 源变化跟踪

**核心逻辑**：保留原名单及历史发布；只追加有证据的更正，限定原始版本、门店、编码和唯一目标区域，自原版本业务日期生效。按观察时间读取。不修改账号授权。

**核心文件**：`ranking_area_corrections.py`、0067 迁移、参数化运维脚本。

**完成标准**：旧观察时点仍可重现；新榜单区域对转，门店与全国总量不变。

**Verification Method**：历史迁移、不可变性测试、源变化跟踪、生产榜单前后回读。

**Evidence**：`docs/devlog/20261105_dydata114_history.md`

**Failure Handling**：目标身份歧义时事务回滚；保留完整发布头和审计证据。

**完成收尾：状态同步**：验收后更新计划、看板和 Linear。

**Owner**：AI 执行 -> 人审核

**前置**：T0.2

**状态**：进行中
