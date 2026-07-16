# T1.2 双 ID 同记录后端核验

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-22-dual-id-activation.md](main-delivery-plan-dydata-22-dual-id-activation.md)
- 任务看板：[task-kanban-dydata-22-dual-id-activation.md](task-kanban-dydata-22-dual-id-activation.md)

#### T1.2 实现激活状态核验与最终激活的同记录双 ID 校验

**Requirement ID**：DYDATA-22-BE

**PRD 双链·读**：
- Linear `DYDATA-22` 的“后端校验规则”“兼容边界”和“验收标准”章节
- `docs/brd/BRD-dy-data-20260716-1255.md` 的账号与门店权限背景

**核心逻辑**：
- 新增激活状态核验接口，接收 `external_account_id`（账户所属 ID）和 `poi_id`（所属账户关联 POI ID），返回受控状态 `invalid`、`activated` 或 `ready`。
- 状态核验只查询 `raw_aweme_bindings` 中账号类型为子机构账号、`binding_status` 为“认证成功”、且 `account_id + poi_id` 在同一记录精确匹配的数据；不能只判断两个 ID 分别存在。
- 精确匹配后，以对应 `User.password_hash` 是否存在作为“已经激活”的主要判断，并与现有 `is_initialized` 状态保持一致；无密码时返回 `ready`。
- 最终激活 API 接收两个 ID、账号名、密码和确认密码，不再接收认证主体全称或显示名称；显示名称默认使用门店名称。
- 最终激活时必须重新执行相同的子机构账号、认证成功和同记录双 ID 核验，并再次检查未激活状态，不能信任第一屏结果。
- 用户名仅接受 `^[A-Za-z0-9]+$`，前后端使用同一规则；继续执行现有唯一性检查。
- 跨记录组合、缺任一 ID、无有效门店映射或最终提交时状态改变均返回受控错误，不返回账号、门店或认证主体的额外信息。
- 忘记密码改为独立请求模型，只接收两个 ID、密码和确认密码；服务端重新执行“子机构账号 + 认证成功 + 同记录双 ID”核验，并要求目标用户已经设置密码，不修改账号名或显示名称。
- 登录别名继续保持现有行为。

**核心文件**：
- `apps/api/dy_api/routes/auth.py`
- `apps/api/dy_api/schemas.py`
- `apps/api/dy_api/models.py`
- `tests/test_api_auth.py`
- `apps/worker/browser_exports/backend_aweme_parser.py`
- `apps/worker/browser_exports/backend_aweme.py`

**完成标准**：
- 新增测试证明只有“子机构账号 + 认证成功 + 同一记录双 ID”会返回 `ready`。
- 新增测试证明把 A 记录账户 ID 与 B 记录 POI ID 组合时返回 `invalid`。
- 新增测试证明匹配记录存在且 `password_hash` 已设置时返回 `activated`。
- 新增测试证明非子机构账号或非“认证成功”记录不能进入第二屏。
- 请求缺少任一双 ID 字段时返回 422 或项目既有的结构校验错误。
- 最终激活接口会重复校验两个 ID；直接跳过状态核验、伪造前端状态或核验后被其他请求激活均不能绕过。
- 账号名包含中文、空格、下划线或连字符时返回明确的字段校验错误。
- 激活成功后仍可按账号名、账户所属 ID 和 POI ID 登录。
- 忘记密码测试证明：正确双 ID 且已激活时可修改密码；跨记录、未激活、非认证成功或非子机构记录均不能重置。
- 重置成功后原账号名和显示名称保持不变，新密码可登录且旧密码失效。
- 无需新增数据库迁移；若真实模型无法表达同记录关系，必须阻塞并先提交数据模型决策。

**Verification Method**：
- 先在 `tests/test_api_auth.py` 添加 `invalid / activated / ready`、资格过滤和最终重复校验用例，运行目标测试并确认因接口尚未存在或仍使用旧逻辑而失败。
- 实装后运行 `pytest tests/test_api_auth.py -q`。
- 运行与账号授权相关的现有 API 回归测试。

**Evidence**：
- 红灯：`python -m pytest tests/test_api_auth.py -q` 返回 5 failed、9 passed，失败原因是状态接口不存在且旧请求模型仍要求认证主体。
- 绿灯：同命令返回 14 passed（2026-07-16）。
- 账号回归：认证、管理员账号、权限和前端账号测试合计 24 passed（2026-07-16）。
- Foundation 漂移：新增认证 API 契约缺少 foundation 文档，已登记 `S4-FCR-001`，不阻断本任务。

**Failure Handling**：
- 同记录核验以保存两个导出字段和原始账号类型的 `raw_aweme_bindings` 为准；若真实数据中的账号类型字段或“认证成功”取值与导出不一致，先用真实导出样本确认允许值，不自行扩大匹配范围。
- 若现有数据存在重复或一对多映射，返回统一失败，不自动选择任意门店。
- 若旧登录测试回归或重置成功后账号名发生变化，禁止进入 T1.3，先修复兼容性。

**完成收尾：状态同步**：
- 本 Task 完成实现、验证和 foundation 漂移判断后，必须把 Task 完成事实、验证证据、完成日期、foundation 漂移结论和建议下一 Task 提交给 `ai-project-manager`。
- 由 `ai-project-manager` 调度 `delivery-planner` 同步主开发计划、任务看板和本子开发计划状态。
- 同步后重新运行 `node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S4 --json`；未完成状态同步前不得标记本 Task 已完成。

**Owner**：AI 执行 -> 人审核

**前置**：T1.1

**状态**：已完成（2026-07-16）
