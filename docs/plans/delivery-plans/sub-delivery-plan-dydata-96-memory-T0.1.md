# T0.1 内存保护与同步恢复

- 主开发计划：[main-delivery-plan-dydata-96-memory.md](main-delivery-plan-dydata-96-memory.md)
- 任务看板：[task-kanban-dydata-96-memory.md](task-kanban-dydata-96-memory.md)

#### T0.1 内存保护与同步恢复

**Requirement ID**：DYDATA-96

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` §1

**核心逻辑**：收紧为可用<2GiB或容器>80%持续60秒；保护为<1GiB或>90%持续30秒；恢复>2.5GiB且<75%持续180秒，再稳定600秒放行历史。swap静态占用不阻塞。保留硬上限。

**核心文件**：apps/ops_agent/resources.py、apps/worker/资源与调度、admin同步API/UI、tests/、docs/runbook.md。

**完成标准**：分级保护、持续判断、自动恢复、日批优先；资源暂停不耗业务重试，后台展示原因、持续时长、恢复条件和超时提示；相关回归通过。

**Verification Method**：可控时钟策略测试、调度/租约回归、API测试、Web构建、git diff --check。

**Evidence**：生产12:41采样swap_used导致DRAIN；日批pending、绑定停止更新。

**Failure Handling**：保留硬内存上限和租约；资源未知不可默认为安全；测试失败停止发布。

**Owner**：AI

**前置**：已授权策略开发。

**状态**：进行中

**完成收尾：状态同步**：Linear、计划、运行手册与开发日志记录验证及未发布边界；检查foundation漂移。
