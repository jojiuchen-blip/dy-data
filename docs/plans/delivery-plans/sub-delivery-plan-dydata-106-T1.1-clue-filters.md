# T1.1 核销事实与手机号精准筛选

- 主开发计划：[main-delivery-plan-dydata-106.md](main-delivery-plan-dydata-106.md)
- 任务看板：[task-kanban-dydata-106.md](task-kanban-dydata-106.md)

#### T1.1 核销事实与手机号精准筛选

**Requirement ID**：DYDATA-106

**PRD 双链·读**：
- `mainprd-dy-data.md` 全局权限与导出一致性
- `foundation/foundation-api-clue-center/lead-query-and-contact.md` 查询、导出及手机号
- `foundation/foundation-schema-clue-center.md` 原始证据、读模型、轮次与指标事实

**核心逻辑**：
- 保留 `is_self_store_verified` 的考核原意；details/export核销筛选使用成功、未撤销、分配后且与门店POI匹配的原始核销事实；状态组合与分页导出同口径。
- 完整11位手机号精准筛选采用POST正文，避免URL与日志泄露；服务端验证并沿用既有范围权限，与其他筛选AND组合，不改变旧非号码查询行为。

**核心文件**：
- `apps/api/dy_api/routes/clues.py`
- `apps/web/src`
- `tests/test_api_clues.py`
- `docs/prd/foundation/foundation-api-clue-center/lead-query-and-contact.md`

**完成标准**：
- 超期后本店核销可在明细命中且考核标记不变；取消、分配前、异店和重核销分别有断言。
- 同尾号不同完整号码不混入；无效号码拒绝且不回显；POST、分页、组合条件与导出一致；越权查询/导出保持拒绝。
- 专项、完整pytest、Web构建、精确SHA CI及生产 smoke据实记录；失败不得标记完成。

**Verification Method**：`python -m pytest -q tests/test_api_clues.py`；`python -m pytest`；`npm --prefix apps/web run build`；`git diff --check`；最终CI与生产受限账号、列表、导出和日志验收。

**Evidence**：本轮验证结果、CI与部署链接由主 Codex 回填至 Linear DYDATA-106 及开发日志；当前未宣称发布完成。

**Failure Handling**：来源或权限证据冲突停止对应路径；测试/CI/部署失败修复后复验；保留旧服务与回滚镜像，不为筛选修复修改业务事实。

**Owner**：AI 执行 -> 人审核；主 Codex 统一集成

**前置**：用户已明确审阅会话方案并授权开发、合入main和部署；Linear DYDATA-106 In Progress。

**状态**：进行中

**完成收尾：状态同步**：
- 实现、验证及foundation漂移判断后提交完成事实、日期、证据、漂移结论和后续建议给 ai-project-manager。
- ai-project-manager 调度 delivery-planner 同步主计划、任务看板与子计划，再运行 `node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S4 --json`。
- 未同步三方及Linear、未记录生产结果和用户业务接受边界前，不标记已完成。
