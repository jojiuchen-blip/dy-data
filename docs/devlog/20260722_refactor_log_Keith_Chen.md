# 开发日志 - 2026-07-22

> 主题：DYDATA-41 线索中心 FOUNDATION Phase 4 API、Phase 5 一致性自查与 Phase 6 正式交付
> 操作人：Keith Chen
> 关联计划：docs/plans/execution-plan.md

---

## 一、执行概要

| # | 任务 | 关联 | 状态 |
|---|------|------|------|
| 1 | 确认 Phase 3 Schema | DYDATA-41 | 完成 |
| 2 | 建立并确认 Phase 4 API 契约 | DYDATA-41 | 完成 |
| 3 | 回填 23 张目标表的使用接口 | DYDATA-41 | 完成 |
| 4 | 执行 Phase 5 C2-C7 一致性自查 | DYDATA-41 | 完成，已确认 |
| 5 | DYDATA-40 安全终端 CLI 登录完成 | S7 | ✅ |
| 6 | DYDATA-45 T2.1 MCP OAuth 完成 | S4 | ✅ |
| 7 | DYDATA-44：完成 AI Coding 案例汇报 HTML | 补充更新 | ✅ |
| 8 | 生成 Phase 6 Foundation 交付清单并通过 S2 门禁 | DYDATA-41 | 完成 |
| 9 | AI Coding 案例汇报改为全视口网页式翻页 | S5 设计迭代 | ✅ |

**本日关键结论**：线索中心 FOUNDATION 术语表、Schema、API 和正式交付清单均已完成；Phase 5 C2-C7 自查获用户确认，Phase 6 的 S2 路由检查返回 `foundationReadyForPrd.pass=true`。本轮未生成 DDL、未修改业务代码，下一阶段进入 DYDATA-42 PRD。

---

## 二、操作详情

### 任务 1：DYDATA-41 FOUNDATION Phase 4 API

- **目标**：把已确认的 BRD、术语与 Schema 转换为可实现、可测试、可审计的接口契约。
- **操作**：核对现有 `/api/v1` 路由、snake_case JSON、`data/meta` 响应、权限编号和页面交互；建立 API 总索引及公共契约、线索查询与联系方式、跟进与轮次、规则与门店组、正式分配与总部池、任务安全与迁移 6 份拆分文档；为 23 张目标表回填具体使用接口。
- **结果**：查询、自然日筛选、分页、明文手机号访问、明文导出、跟进动作、规则发布、试运行、正式分配、总部池、任务幂等与一次性迁移均有明确入口和边界。
- **安全边界**：全局数据可见不自动授予完整手机号权限；查看、复制和导出明文分别鉴权并审计；正式分配只允许内部任务触发；试运行不写正式轮次；已发布规则版本不可变。
- **验证**：23/23 张目标表均已映射接口，38 个 Foundation 文档链接无断链，全部 API/Schema 文档低于 400 行，未发现 Phase 4 占位符；`git diff --check` 通过；项目治理与设计系统文档测试 33 项通过；全量测试 516 项通过，仅有现有 Alembic/SQLite 弃用警告。
- **涉及文件**：`docs/prd/foundation/foundation-api-clue-center.md`、`docs/prd/foundation/foundation-api-clue-center/*.md`、`docs/prd/foundation/foundation-schema-clue-center.md`、`docs/prd/foundation/foundation-schema-clue-center/*.md`、`project-profile.md`、`docs/plans/execution-plan.md`。

### 任务 2：DYDATA-41 FOUNDATION Phase 5 一致性自查

- **C2 页面字段**：保留的 21 个线索业务可写字段全部可追溯到目标 API 和 Schema；同步页 9 个通用采集字段属于宿主共享契约，单独映射到 `/admin/sync`，不计入线索 23 表分母。
- **C3 API/Schema**：6 份 API 专题共检查 318 条结构化字段/控制项；170 条直接命中 Schema 字段，148 条为请求控制、派生指标、权限能力、分页或枚举，均有明确来源或计算规则；41 个显式 `table.field` 引用全部存在。
- **C4 术语**：线索生成时间/下单时间、策略步骤/分配轮次、线索状态/轮次状态、跟进门店、线索跟进率、总部池和三类固定策略命名一致。
- **C5 孤立检测**：23/23 张目标表均有公开、管理或内部接口消费者；513 个字段均属于业务事实、关系/幂等、运行证据、审计/版本或必要时间元数据，未发现无用途表或字段。
- **C6 交互覆盖**：20/20 个线索相关 locked 交互完成追溯，其中 14 个由 Foundation API 支撑、3 个由宿主同步共享 API 支撑、3 个为纯前端导航/相邻切换且无需新增接口。
- **C7 校验覆盖**：17/17 个含 validation 的 locked 交互均有约束；持久化校验由 Schema 和事务约束承载，查询/权限校验由公共 API 契约承载，移动端滑动阈值为纯客户端约束。

#### C2 页面可写字段追溯

| 页面/字段组 | 字段数 | 写入 API | API 请求字段 | 目标表.列 | 结果 |
|-------------|--------|----------|--------------|-----------|------|
| 跟进详情 | 2 | F01 | `follow_action`、`note` | `clue_follow_up_record.follow_action/note` | 通过 |
| 规则身份 | 5 | R03/R05 | 名称、范围类型及三类条件范围键 | `clue_allocation_rule` 对应字段 | 通过 |
| 规则版本与策略 | 12 | R06/R07 | SLA、保护期、评分、样本、三策略启停及两类半径 | `clue_allocation_rule_version` + `clue_allocation_strategy_config` | 通过 |
| 试运行范围 | 2 | A02-A04 | `lead_keys[]`、`source_cycle_id` | `clue_allocation_cycle_item.lead_key`、`clue_allocation_cycle.source_cycle_id` | 通过 |

同步配置与手动补拉的 9 个页面字段分别由宿主 `PUT /api/v1/admin/sync/config` 和 `POST /api/v1/admin/sync/run` 负责，不写线索业务目标表；它们已完成接口追溯，但不计入上述 21 个线索字段分母。

#### C6 locked 交互追溯

| 交互范围 | 数量 | 支撑接口/行为 | 结果 |
|----------|------|---------------|------|
| 筛选、导出、详情、手机号、跟进、删除 | 7 | Q01/Q02/Q05-Q08、F01/F02 | 通过 |
| 线索维护 | 1 | J07 预览 + J08 确认执行 | 通过 |
| 规则选择与版本管理 | 2 | R01-R10 | 通过 |
| 试运行预览、启动与重建 | 2 | A01-A04 | 通过 |
| 分配记录与总部池 | 2 | A05-A13、H01 | 通过 |
| 同步状态、配置、手动补拉 | 3 | 宿主共享 `GET /admin/sync`、`PUT /admin/sync/config`、`POST /admin/sync/run` | 通过 |
| 页签、后台子视图、相邻线索切换 | 3 | 纯客户端导航；相邻详情复用 Q06 | 通过 |

#### C3-C5 契约追溯

| 专题 | 结构化字段/控制项 | Schema 或派生来源 | 结果 |
|------|------------------|-------------------|------|
| 公共契约 | 4 | 宿主响应元数据与请求链路 | 通过 |
| 查询、指标、导出与联系方式 | 113 | 主线索、订单投影、轮次、联系人、指标事实及授权计算 | 通过 |
| 跟进与轮次 | 46 | 跟进流水、真实轮次、主线索版本及状态迁移结果 | 通过 |
| 规则与门店组 | 68 | 规则、版本、策略、门店组/成员及活动成员摘要派生 | 通过 |
| 分配运行与总部池 | 65 | 批次、明细、决策、候选、评分、总部池及审计 | 通过 |
| 任务、安全与迁移 | 22 | 原始证据、目标事实表、内部命令和受控重建请求 | 通过 |

| C5 范围 | 总数 | 处理结论 |
|---------|------|----------|
| Schema 表 | 23 | 23/23 均至少被一个公开、管理或内部接口消费 |
| Schema 字段 | 513 | 全部归入业务事实、关系/幂等、运行证据、审计/版本或必要时间元数据；无待删除孤立字段 |
| 显式 `table.field` API 引用 | 41 | 41/41 在目标 Schema 中存在 |

#### C7 validation 追溯

| 校验类别 | 对应交互 | 约束位置 | 结果 |
|----------|----------|----------|------|
| 五类跟进、备注长度、当前有效轮次 | 保存跟进 | 跟进流水枚举/长度、活动轮唯一约束、F01 事务校验 | 通过 |
| 软删除角色、版本和审计原因 | 删除跟进记录 | 软删除非空组合约束、F02 版本与最高管理员校验 | 通过 |
| 规则范围、SLA、保护期、权重、样本和半径 | 管理规则版本 | 规则/版本/策略 Schema 约束 + R03/R06-R10 发布校验 | 通过 |
| 试运行选择、预览绑定和只写试运行数据集 | 预览/启动/重建 | A02-A04 请求上限、令牌和数据集隔离约束 | 通过 |
| 日期、分页、数据范围和敏感权限 | 筛选、导出、详情、总部池、同步 | 公共契约、共享同步 API 与服务端授权 | 通过 |
| 水平滑动阈值、首尾禁用 | 相邻线索切换 | PAGE_EXPLAINER + 客户端交互约束，不持久化 | 通过 |

#### Phase 5 修正项

1. Q06 增加主线索版本、当前轮次 ID、轮次 ID/序号/版本和轮次级能力，闭合 Q08、F01、F02 的乐观锁输入。
2. Q08 同时校验主线索和当前轮次版本，避免状态变化后仍读取完整手机号。
3. R13 返回活动成员集合哈希，闭合 R15 的 `expected_member_hash` 并发校验。
4. Q07/F02 保持页面一键操作，不强加自由文本输入；省略原因时由服务端写固定审计原因。
5. 规则名称/说明、跟进备注/删除原因和规则数值范围与 Schema 约束对齐。
6. 明确宿主同步状态、配置和手动补拉是共享接口；旧无预览重建接口在目标契约中删除并由 J07/J08 替代。

#### 已识别的后续实现差异

- 现有前端 `assigned_date_*`、`follow_result`、`nearby_city_optimization` 仍是旧命名，目标实现需分别切换为线索生成日期、`follow_action` 和 `city_radius_best`。
- 现有试运行重建的“允许覆盖已有跟进记录”与试运行不得改正式数据冲突，目标页面应删除该控件；若需要比较规则版本，只使用 `rebind_rule_version` 预览参数。
- 现有同步页直接调用 `/admin/sync/clue-center/rebuild`，目标实现必须改为 J07 预览后再由 J08 确认执行。
- 现有详情写操作尚未传递 Foundation 版本号；实现时以 Q06 返回值驱动 Q08/F01/F02，不从前端自行推断。

### 任务 3：DYDATA-41 FOUNDATION Phase 6 正式交付

- **交付清单**：新增 `docs/prd/foundation/foundation-delivery-clue-center.md`，按固定表头声明术语表、Schema 索引及 23 个子文件、API 索引及 6 个子文件。
- **交付摘要**：119 个术语、23 张目标表、55 个 HTTP 契约、5 个外部依赖；Phase 5 页面字段、API/Schema、术语、孤立项、交互和校验结果全部写入交付证据。
- **门禁验证**：执行 `node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S2 --json`，得到 `foundationDeliveryExists=true`、`artifactsReady=true`、`foundationReadyForPrd.pass=true`，0 errors、0 warnings；治理专项测试 59 项、最新 `main` 全量测试 818 项全部通过。
- **下游边界**：下一路由为 `prd-chief` / `prd-writer`，由 DYDATA-42 读取本清单及全部 Foundation 产物；业务代码、DDL、迁移和页面实现继续保持未修改。

---

## 三、变更总览

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `docs/prd/foundation/foundation-api-clue-center.md` | API 总索引、宿主协议覆写与端点总览 |
| 新建 | `docs/prd/foundation/foundation-api-clue-center/*.md` | 6 份领域接口契约 |
| 修改 | `docs/prd/foundation/foundation-schema-clue-center.md` | 登记 Phase 4 回填结果 |
| 修改 | `docs/prd/foundation/foundation-schema-clue-center/*.md` | 23 张表回填使用接口 |
| 修改 | `project-profile.md` | 当前阶段切换到 FOUNDATION Phase 4 |
| 修改 | `docs/plans/execution-plan.md` | 更新执行驾驶舱和验证证据 |
| 新建 | `docs/prd/foundation/foundation-delivery-clue-center.md` | Foundation Phase 6 正式交付清单与 S2 门禁证据 |

### Git 提交记录

| 时间 | Commit | 内容 |
|------|--------|------|

---

## 四、发现的问题 / 缺陷

- 通用套件示例协议与宿主项目现有协议不同；本次以宿主项目 `/api/v1`、snake_case 和 `data/meta` 为准，并在公共契约中显式登记覆写，避免实施时形成双协议。
- 门店组 Schema 没有持久化 `state_version`；API 不虚构数据库字段，门店组元数据更新使用行锁，成员全量替换使用 `expected_member_hash` 作为传输层并发令牌。
- Phase 6 路由检查已通过；自动项目链接索引此前误扫 `.worktrees` 并产生大范围非本阶段变更，该生成结果不纳入 DYDATA-41 交付，也未在本轮覆盖或回滚。

---

## 五、复盘

### 做得好的

- API 先绑定 Schema，再定义页面调用，避免接口字段与目标数据模型分叉。
- 将联系方式、明文导出、正式分配和试运行按风险拆成独立命令，便于权限和审计验收。

### 遇到的问题

- **现象**：现有接口包含部分 GET 副作用和历史混合模型，不能直接作为目标契约沿用。
- **根因**：旧实现先于统一 BRD、Schema 和权限边界形成。
- **经验**：目标 API 应保留稳定宿主协议，但不能保留会破坏幂等、安全审计或新事实模型的历史副作用。
- **是否提炼为规则**：仅记录。

---

## 六、待跟进事项

- [x] 用户确认 FOUNDATION Phase 4 API。
- [x] 用户确认 Phase 5 C2-C7 一致性结果。
- [x] Phase 6 生成 FOUNDATION 交付清单并通过 S2 路由门禁。
- [ ] 完成 DYDATA-42 PRD 与 DYDATA-43 正式交付计划。
- [ ] S4 门禁通过后执行 DYDATA-34，全面删除旧线索分配引擎。
---

## 补充更新 1（03:13 · 窗口 1）

### 任务 2：DYDATA-44：完成 AI Coding 案例汇报 HTML
- **目标**：将已确认的19页领导汇报内容制作成JCYC品牌翻页式HTML，并提供可离线运行的Web与CLI演示备份
- **操作**：完成19页HTML、演讲者备注、总览与键盘控制；实现Web三分钟分镜和CLI/Agent备用分镜；补齐品牌资产、本地字体、移动端退化和交付说明；导出单文件版并进行浏览器验收
- **结果**：普通版和1.88MB单文件版均已生成；JCYC校验均为0错误0警告；19页与19份讲稿齐全；桌面端无内容溢出，移动端可滚动；交互、字体、品牌图形和单文件内联资源均正常，浏览器控制台0错误
- **涉及文件**：docs/ai-coding-case-report/index.html、docs/ai-coding-case-report/index.single.html、docs/ai-coding-case-report/deck.css、docs/ai-coding-case-report/README.md、docs/ai-coding-case-report-draft.md、project-profile.md

---

## 补充更新 2（04:27 · 窗口 1）

### 任务 2：DYDATA-40 安全终端 CLI 登录完成
- **目标**：完成 Agent 可启动、用户本人在安全 TTY 输入账号和隐藏密码的 CLI 登录，并保留浏览器回退
- **操作**：在隔离 worktree 以 TDD 实现独立 Web Cookie 会话、身份/范围白名单、默认 TTY 交接、CAS 保存与异常撤销；更新运行时命令目录、Agent 指南和验收说明；执行全量测试、构建、依赖/秘密/静态扫描和双代理复核
- **结果**：CLI 0.2.0 完成；目标测试 137 passed，全量 817 passed，Web build 通过，安全扫描 PASS，独立安全审查 APPROVE，Agent 契约验收 PASS；未部署、未推送、未合并，真实 TTY 与生产门店数据 UAT 留待部署后由用户执行
- **涉及文件**：apps/cli/src/dydata_cli/interactive_auth.py、apps/cli/src/dydata_cli/commands.py、apps/cli/src/dydata_cli/registry.py、tests/cli/test_interactive_auth.py、tests/cli/test_terminal_login.py、docs/cli-agent-guide.md、docs/cli-agent-acceptance.md、docs/security/2026-07-22-secure-terminal-cli-login-security-scan.md、docs/plans/delivery-plans/main-delivery-plan-dydata-40-secure-terminal-login.md
---

## 补充更新 3（15:22 · 窗口 2）

### 任务 3：DYDATA-45 T2.1 MCP OAuth 完成
- **目标**：建立测试环境标准远程 MCP 与持久化 OAuth 2.1 安全边界
- **操作**：以 TDD 实现 public-client DCR、PKCE S256、固定 resource/scope、四张独立凭据表、单次授权码、刷新轮换重放撤销、协议发现及 Streamable HTTP lifespan
- **结果**：T2.1 完成；16 项 OAuth 测试、完整 Alembic 往返和 256 项组合回归通过；状态已切换到 T2.2
- **涉及文件**：apps/api/dy_api/mcp_oauth.py、apps/api/dy_api/mcp_server.py、apps/api/dy_api/models.py、alembic/versions/20260722_0021_mcp_oauth.py、tests/test_api_mcp_oauth.py、docs/plans/delivery-plans/main-delivery-plan-dydata-45-test-agent-connect.md

---

## 补充更新 4（14:25 · 窗口 3）

### 任务 4：AI Coding 案例汇报改为全视口网页式翻页
- **目标**：根据领导汇报场景反馈，弱化 PPT 播放器感，保留网页式分页体验与左右切换能力。
- **操作**：移除深色外舞台、16:9 中央画布、边框投影和底部控制台；将每页改为全视口布局；把桌面翻页入口改为悬停显现的左右边缘按钮，移动端收拢至底部；重新导出单文件版并执行桌面、移动端及键盘切换检查。
- **结果**：常规版与 1.88 MB 单文件版已更新；JCYC 校验均为 0 warning；Playwright 2 项检查通过，19 页桌面无裁切，移动端无横向溢出，左右键与点击切换正常。
- **涉及文件**：docs/ai-coding-case-report/index.html、docs/ai-coding-case-report/deck.css、docs/ai-coding-case-report/index.single.html、docs/ai-coding-case-report/README.md
- **当前结论**：展示框架已从 PPT 模拟器调整为浏览器全视口网页分页，内容和页序保持不变。
- **下一步**：继续按页确认具体内容与视觉密度；正式汇报前补齐封面人员与日期信息。
- **复盘**：🔧 不建议提炼为项目全局规则；这是本次领导汇报媒介形态的专项取舍。
