# T1.1 PDCA管理员兼容修复

- 主开发计划：[main-delivery-plan-dydata-110.md](main-delivery-plan-dydata-110.md)
- 任务看板：[task-kanban-dydata-110.md](task-kanban-dydata-110.md)

#### T1.1 PDCA管理员兼容修复

**Requirement ID**：DYDATA-110

**PRD 双链·读**：
- `mainprd-dy-data.md` 全局权限、查询边界
- `foundation/foundation-api-dy-data/common-contract.md` 认证与错误契约

**核心逻辑**：在独立只读会话中保留签名、状态、初始化及auth_version检查，复用AuthContext的全局管理员能力；不调用有初始化副作用的普通会话依赖。

**核心文件**：`apps/api/dy_api/pdca_readonly_access.py`、`tests/test_pdca_readonly_access.py`、相关PDCA路由回归。

**完成标准**：admin/all登录与明细、快照、分页一致；受限账号与失效会话拒绝；无写SQL；专项及完整验证分别记录；实际上线后先一天再累计范围，保留旧数据与实验。

**Verification Method**：`python -m pytest`、`npm --prefix apps/web run build`、`git diff --check`、最终SHA的CI、生产版本和同步实测。

**Evidence**：回填Linear DYDATA-110及专项发布记录，不以孤立测试代表部署。

**Failure Handling**：失败停止对应路径，保留旧产物及数据；不放宽权限或容量门槛。

**Owner**：当前Codex执行；用户业务验收。

**前置**：用户明确开发及上线授权，DYDATA-110 In Progress。

**状态**：进行中

**完成收尾：状态同步**：同步主计划、看板、子计划和Linear，明确实际验证及foundation漂移；业务未接受不关闭需求。
