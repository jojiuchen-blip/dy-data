# 安全扫描报告：安全终端 CLI 登录

## 1. 扫描范围

- 扫描模式：`full`
- 覆盖域：应用代码安全、敏感信息与密钥、依赖与供应链、API 输入/输出校验；鉴于本次属于认证功能，额外覆盖 TTY、Cookie 隔离、device grant 时序、凭据 compare-and-swap 与 Agent 人工交接契约。
- 代码范围：`main...feat/cli-terminal-login` 的 CLI 实现、测试、运行时注册表、文档和 T1.4 收尾修正。
- 未覆盖域：生产部署暴露面、真实生产账号登录、真实浏览器授权和真实门店数据查询。用户未授权本轮部署，这些项目保留为部署后人工 UAT，不属于本次代码安全闸门的默认扫描域。

## 2. 输入证据

- 执行计划：`docs/plans/delivery-plans/main-delivery-plan-dydata-40-secure-terminal-login.md`、T1.1-T1.4 子计划、`docs/superpowers/specs/2026-07-22-secure-terminal-cli-login-design.md`。
- 代码 / 配置 / 依赖变更：CLI 认证会话、命令流程、注册表、CLI 包版本、文档和测试；前端依赖清单未由本功能修改。
- 测试与验收材料：修复后的目标测试 137 passed；全量 pytest 817 passed；Web production build 通过；独立安全复核最终 `APPROVE`；独立 Agent CLI 契约验收 `PASS`，61 项相关测试通过。
- 依赖证据：`pip check` 无损坏依赖；`pip-audit 2.10.1` 对根 `requirements.txt` 和 `apps/cli` 项目扫描均为 0 个已知漏洞；`npm audit` 为 0 Critical、0 High、0 Moderate、1 Low。
- 静态与秘密扫描：Bandit 1.9.4 扫描整个 CLI 源码为 0 High、0 Medium、2 Low；高置信私钥、AWS key、GitHub token、JWT 和 URL 凭据模式均为 0。通用 secret literal 与 credential URL 命中只存在于负向测试哨兵，生产代码为 0。
- 部署与暴露面信息：本轮不部署、不推送、不合并；远端 URL 继续复用既有安全 URL 规则，远端只允许 HTTPS，显式 loopback 开发地址除外。
- 证据缺口：真实共享 TTY、系统 keyring、生产账号门店范围和生产线索统计只能在部署后由用户本人完成；验收步骤见 `docs/cli-agent-acceptance.md`。

## 3. 发现项

### SEC-CLI-001（已修复）

- 风险摘要：`_best_effort_revoke` 原先只捕获 `CliError`，非预期撤销异常可能掩盖本地保存/CAS 的原始结果。
- 影响面：CAS=false 本应返回 `AUTH_FAILED` 时可能变为 `INTERNAL_ERROR`；不会覆盖既有凭据，但违反清理失败不得改变主结果的契约。
- 证据：新增两条 non-`CliError` 撤销失败回归，RED 为 2 failed；实现改为捕获 `Exception`、不捕获 `BaseException` 后 GREEN 为 2 passed，完整终端登录测试 14 passed。
- 状态：已修复，无剩余风险。

### SEC-CLI-L01（Low，既有依赖）

- 风险摘要：`npm audit` 报告传递依赖 `esbuild 0.27.3-0.28.0` 的 Windows 本地开发服务器任意文件读取低危问题（GHSA-g7r4-m6w7-qqqr）。
- 影响面：前端本地开发服务器；本功能没有修改前端 lockfile，CLI 运行时不加载该依赖，生产构建已成功。
- 证据：`npm audit --json` 为 1 Low；0 Moderate/High/Critical。
- 处置：不阻断本次 CLI 功能；前端依赖维护时升级到包含修复的兼容版本，并重新执行 build 与 audit。

### SEC-CLI-L02（Low，既有静态观察）

- 风险摘要：Bandit 报告两个既有低危项：协议常量 `token_type: "Bearer"` 被 B105 误判为硬编码密码；已验证分支中的类型收窄 `assert` 被 B101 标记。
- 影响面：均不参与凭据取值、认证授权或终端输出，本次 diff 未修改对应文件。
- 证据：Bandit 为 0 High、0 Medium、2 Low；新认证模块 `interactive_auth.py` 为 0 finding。
- 处置：记录为非阻断既有观察；后续代码清理可消除静态噪声。

## 4. 风险分级

- Critical：0
- High：0
- Medium：0（SEC-CLI-001 已在闸门内修复）
- Low：2 个非阻断既有项

## 5. 阻断项

- 阻断编号：无
- 阻断原因：无 Critical、High、密钥泄漏、认证绕过或未解决的 Medium 风险。
- 未满足的放行条件：无。真实生产 TTY 验收属于部署后业务验收，不伪装为本轮已执行。

## 6. 放行结论

- 最终结论：`PASS`
- 结论理由：默认 full 扫描域已有新鲜证据；发现的认证清理 P2 已通过 TDD 修复；目标测试、全量测试、Web 构建、Python 依赖审计、静态扫描、秘密扫描和两轮独立复核均无阻断项。现存两个 Low 为本功能未引入的依赖/静态观察。

## 7. 整改建议

- 立即整改：无。
- 完工前补齐：将本报告、Agent CLI 验收说明、T1.4 Evidence 和开发日志纳入最终提交。
- 完工后跟踪：升级受影响的 `esbuild` 传递依赖；部署时把 Python user Scripts 目录加入 PATH 或提供稳定包装入口；由用户本人执行真实 TTY 登录与指定测试账号门店范围/线索统计 UAT。

## 8. Waiver 记录（如有）

- 无。本次结论不是豁免。
