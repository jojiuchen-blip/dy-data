# 开发日志 — 2026-07-23

> 主题：DYDATA-45 腾讯云部署与独立 Agent UAT 收口
> 操作人：Keith Chen
> 关联计划：docs/plans/execution-plan.md

---

## 一、执行概要

| # | 任务 | 关联 | 状态 |
|---|------|------|------|
| 1 | DYDATA-45 腾讯云部署与独立 Agent UAT 收口 | 本轮推进 | ✅ |
| 2 | DYDATA-47 SPACE AI Native 署名与明暗主题交付 | S2 | ✅ |

**本日关键结论**：部署 workflow 29934737788 成功；CLI/MCP 重试 PASS，测试账号仅见 3 家授权门店，统计不变量、整单越权拒绝与跨通道脱敏聚合一致；DYDATA-45 转 In Review，DYDATA-46 继续承接 production 切换

---

## 二、操作详情

### 任务 1：DYDATA-45 腾讯云部署与独立 Agent UAT 收口
- **目标**：完成测试环境 CLI + MCP 发布、真实授权与跨通道黑盒验收，并保持未来企业内网 production 隔离
- **操作**：将 cab6aec 推送并部署到腾讯云；执行公开端点与 DCR 安全 smoke；由人类 Owner 完成 CLI 0.3 与 MCP 官方网页授权；两轮独立子代理分别记录授权缺失失败和授权后重试
- **结果**：部署 workflow 29934737788 成功；CLI/MCP 重试 PASS，测试账号仅见 3 家授权门店，统计不变量、整单越权拒绝与跨通道脱敏聚合一致；DYDATA-45 转 In Review，DYDATA-46 继续承接 production 切换
- **涉及文件**：`docs/plans/execution-plan.md`、`docs/plans/delivery-plans/main-delivery-plan-dydata-45-test-agent-connect.md`、`docs/plans/delivery-plans/task-kanban-dydata-45-test-agent-connect.md`、`docs/plans/delivery-plans/sub-delivery-plan-dydata-45-test-agent-connect-T3.1-deploy-agent-uat.md`

---

## 三、变更总览

### 文件变更清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `docs/plans/execution-plan.md` | 回写部署、公开 smoke、独立 UAT 与 In Review 状态 |
| 修改 | `docs/plans/delivery-plans/main-delivery-plan-dydata-45-test-agent-connect.md` | 完成 Phase 3 发布闸门与风险状态 |
| 修改 | `docs/plans/delivery-plans/task-kanban-dydata-45-test-agent-connect.md` | 将 T3.1 同步为已完成 |
| 修改 | `docs/plans/delivery-plans/sub-delivery-plan-dydata-45-test-agent-connect-T3.1-deploy-agent-uat.md` | 记录部署、CLI/MCP 黑盒与安全负例证据 |
| 新建 | `docs/devlog/20260723_refactor_log_Keith_Chen.md` | 记录本轮交付收口与后续边界 |

### Git 提交记录

| 时间 | Commit | 内容 |
|------|--------|------|
| 2026-07-22 | `5a7d995` | 新增测试环境 Agent CLI 与 MCP 接入 |
| 2026-07-22 | `7b97e36` | 加固 OAuth redirect、DCR 限额与 MCP 契约 |
| 2026-07-22 | `cab6aec` | 将畸形 MCP 注册稳定为通用 400；本次腾讯云部署运行时代码 |

---

## 四、发现的问题 / 缺陷

1. 本机遗留 `dydata-cli==0.2.0` 的授权不能代表 manifest 要求的 0.3.0 授权；首轮独立 UAT 因 `AUTH_REQUIRED` 失败，重新按 0.3.0 官方浏览器流程授权后才进入重试。
2. CLI 0.3.0 顶层 `--help` / `--version` 返回 `INVALID_ARGUMENT`；正式机器入口 `commands --json` / `version --json` 可用，当前不阻断 Agent 发现。
3. 官方 Python `mcp` 包在隔离 UAT 环境安装超时；限定一次切换官方 Node SDK 后完成完整 MCP OAuth 与工具调用，不使用自造客户端。

---

## 五、复盘

### 做得好的
- 首轮失败未被覆盖或解释成成功，保留失败报告后另起全新子代理重试。
- CLI 与 MCP 只对比计数、公式不变量和脱敏聚合，不让真实门店、经营指标或凭据进入 Agent 上下文。
- 运行时代码 SHA、CI/部署 run、公开安全 smoke 与 UAT 证据相互独立，可按层定位问题。

### 遇到的问题
- **现象**：用户此前完成过 CLI 授权，但独立 0.3.0 UAT 仍返回 `AUTH_REQUIRED`。
- **根因**：本机预装版本为 0.2.0，旧客户端、启动器与新 manifest/环境凭据槽位发生版本漂移。
- **经验**：真实 Agent 验收必须先用 manifest 指定版本执行 `version --json`、`doctor --json` 和 `auth status --json`，不能把任意旧 CLI 的“授权成功”当作当前合同证据。
- **🔧 是否提炼为规则**：⬜ 仅记录；后续若在 DYDATA-46 生产切换再次出现，再升级到 Agent 接入专项规则。

### 今日经验总结
1. 授权证据必须绑定 CLI 版本、命名环境与 server identity，而不是只看本机存在凭据 → 仅记录。
2. 跨通道等价验收优先比较完整脱敏聚合与公式不变量，既能证明口径一致，也能避免业务数据泄漏 → 仅记录。

---

## 五·附、方法论沉淀（可选）

对“Agent 自助接入”做黑盒验收时，顺序固定为：公开发现 → 指定版本安装 → doctor/auth → 权限范围与负例 → 官方协议 SDK → CLI/MCP 脱敏等价。任何旧版本、旧授权或自造协议客户端都不能替代当前公开合同。

---

## 六、待跟进事项

- [ ] 人类 Owner 审核 `DYDATA-45`，确认后再由 In Review 转 Done。
- [ ] `DYDATA-46` 在企业内网生产服务器上线后，一次性切换 CLI 默认环境、MCP、OAuth issuer/resource、keyring、文档、示例与 smoke；不得迁移测试凭据。
- [ ] 评估是否另建低优先级兼容性改进，支持 CLI 顶层 `--help` / `--version`。
---

## 补充更新 1（03:36 · 窗口 1）

### 任务 2：DYDATA-47 SPACE AI Native 署名与明暗主题交付
- **目标**：完成 DYDATA-47 视觉规范、运行时主题和品牌署名的全站接入，并进入提交部署验证
- **操作**：新增 light/dark/system 主题运行时、SPACE AI Native 署名组件与资源，更新设计 token、规范 HTML、全站入口和视觉回归；运行完整测试、构建与治理门禁
- **结果**：991 项测试通过、2 项跳过；前端生产构建通过；当前继续执行提交、main 推送和腾讯轻量云部署
- **涉及文件**：apps/web/src/components/SpaceAiSignature.tsx、apps/web/src/theme/ThemeProvider.tsx、apps/web/src/design-tokens.css、docs/design-system/index.html、docs/design-system/tokens.json、tests/test_frontend_theme_brand.py、tests/test_visual_smoke.py
