# 开发日志 - 2026-07-22

> 主题：DYDATA-41 线索中心 FOUNDATION Phase 4 API
> 操作人：Keith Chen
> 关联计划：docs/plans/execution-plan.md

---

## 一、执行概要

| # | 任务 | 关联 | 状态 |
|---|------|------|------|
| 1 | 确认 Phase 3 Schema | DYDATA-41 | 完成 |
| 2 | 建立 Phase 4 API 契约 | DYDATA-41 | 待业务确认 |
| 3 | 回填 23 张目标表的使用接口 | DYDATA-41 | 完成 |
| 4 | DYDATA-40 安全终端 CLI 登录完成 | S7 | ✅ |
| 5 | DYDATA-45 T2.1 MCP OAuth 完成 | S4 | ✅ |

**本日关键结论**：线索中心 FOUNDATION API 已按宿主项目现有协议拆分落盘，Schema 与接口映射已闭合。当前停在 Phase 4 用户确认门禁，未生成 DDL、未修改业务代码，也未进入 Phase 5。

---

## 二、操作详情

### 任务 1：DYDATA-41 FOUNDATION Phase 4 API

- **目标**：把已确认的 BRD、术语与 Schema 转换为可实现、可测试、可审计的接口契约。
- **操作**：核对现有 `/api/v1` 路由、snake_case JSON、`data/meta` 响应、权限编号和页面交互；建立 API 总索引及公共契约、线索查询与联系方式、跟进与轮次、规则与门店组、正式分配与总部池、任务安全与迁移 6 份拆分文档；为 23 张目标表回填具体使用接口。
- **结果**：查询、自然日筛选、分页、明文手机号访问、明文导出、跟进动作、规则发布、试运行、正式分配、总部池、任务幂等与一次性迁移均有明确入口和边界。
- **安全边界**：全局数据可见不自动授予完整手机号权限；查看、复制和导出明文分别鉴权并审计；正式分配只允许内部任务触发；试运行不写正式轮次；已发布规则版本不可变。
- **验证**：23/23 张目标表均已映射接口，38 个 Foundation 文档链接无断链，全部 API/Schema 文档低于 400 行，未发现 Phase 4 占位符；`git diff --check` 通过；项目治理与设计系统文档测试 33 项通过；全量测试 516 项通过，仅有现有 Alembic/SQLite 弃用警告。
- **涉及文件**：`docs/prd/foundation/foundation-api-clue-center.md`、`docs/prd/foundation/foundation-api-clue-center/*.md`、`docs/prd/foundation/foundation-schema-clue-center.md`、`docs/prd/foundation/foundation-schema-clue-center/*.md`、`project-profile.md`、`docs/plans/execution-plan.md`。

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

### Git 提交记录

| 时间 | Commit | 内容 |
|------|--------|------|

---

## 四、发现的问题 / 缺陷

- 通用套件示例协议与宿主项目现有协议不同；本次以宿主项目 `/api/v1`、snake_case 和 `data/meta` 为准，并在公共契约中显式登记覆写，避免实施时形成双协议。
- 门店组 Schema 没有持久化 `state_version`；API 不虚构数据库字段，门店组元数据更新使用行锁，成员全量替换使用 `expected_member_hash` 作为传输层并发令牌。
- S2 路由检查识别出项目画像中的 `当前页面主要给谁用`、`当前页面主要用途`、`页面定位标签` 仍为待确认。当前阶段仍推荐 S2，Foundation 文档本身无校验错误；这三个页面任务字段需在进入后续页面/PRD 门禁前补齐。

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

- [ ] 用户确认 FOUNDATION Phase 4 API。
- [ ] 确认后进入 Phase 5，补齐状态迁移、定时任务、权限安全、迁移和运行方案。
- [ ] 完成 DYDATA-42 PRD 与 DYDATA-43 正式交付计划。
- [ ] S4 门禁通过后执行 DYDATA-34，全面删除旧线索分配引擎。
---

## 补充更新 1（04:27 · 窗口 1）

### 任务 2：DYDATA-40 安全终端 CLI 登录完成
- **目标**：完成 Agent 可启动、用户本人在安全 TTY 输入账号和隐藏密码的 CLI 登录，并保留浏览器回退
- **操作**：在隔离 worktree 以 TDD 实现独立 Web Cookie 会话、身份/范围白名单、默认 TTY 交接、CAS 保存与异常撤销；更新运行时命令目录、Agent 指南和验收说明；执行全量测试、构建、依赖/秘密/静态扫描和双代理复核
- **结果**：CLI 0.2.0 完成；目标测试 137 passed，全量 817 passed，Web build 通过，安全扫描 PASS，独立安全审查 APPROVE，Agent 契约验收 PASS；未部署、未推送、未合并，真实 TTY 与生产门店数据 UAT 留待部署后由用户执行
- **涉及文件**：apps/cli/src/dydata_cli/interactive_auth.py、apps/cli/src/dydata_cli/commands.py、apps/cli/src/dydata_cli/registry.py、tests/cli/test_interactive_auth.py、tests/cli/test_terminal_login.py、docs/cli-agent-guide.md、docs/cli-agent-acceptance.md、docs/security/2026-07-22-secure-terminal-cli-login-security-scan.md、docs/plans/delivery-plans/main-delivery-plan-dydata-40-secure-terminal-login.md
---

## 补充更新 2（15:22 · 窗口 2）

### 任务 3：DYDATA-45 T2.1 MCP OAuth 完成
- **目标**：建立测试环境标准远程 MCP 与持久化 OAuth 2.1 安全边界
- **操作**：以 TDD 实现 public-client DCR、PKCE S256、固定 resource/scope、四张独立凭据表、单次授权码、刷新轮换重放撤销、协议发现及 Streamable HTTP lifespan
- **结果**：T2.1 完成；16 项 OAuth 测试、完整 Alembic 往返和 256 项组合回归通过；状态已切换到 T2.2
- **涉及文件**：apps/api/dy_api/mcp_oauth.py、apps/api/dy_api/mcp_server.py、apps/api/dy_api/models.py、alembic/versions/20260722_0021_mcp_oauth.py、tests/test_api_mcp_oauth.py、docs/plans/delivery-plans/main-delivery-plan-dydata-45-test-agent-connect.md
