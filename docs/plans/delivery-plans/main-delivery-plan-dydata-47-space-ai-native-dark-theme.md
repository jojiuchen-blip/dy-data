# DYDATA-47 SPACE AI Native 品牌署名与全站双主题主交付计划

> **版本**：v1  
> **发布日期**：2026-07-23  
> **适用范围**：`apps/web` 全部前端页面、`docs/design-system` 正式视觉规范与相关自动化测试  
> **需求基线**：Linear `DYDATA-47`；用户已确认候选视觉，并授权直接进入全站开发  
> **上游发现**：`canProceed=true`，`mode=fallback`，权威规格为 `docs/superpowers/specs/2026-07-23-dydata-47-space-ai-native-dark-theme-design.md`  
> **执行边界**：只改前端视觉与交互基础设施，不改后端 API、数据库和业务数据流，不执行 Railway 部署

## 0. 本计划使用指南

1. 同一时刻仅允许一个 Task 处于“进行中”，状态须在主计划、任务看板和子计划中一致。
2. 每个 Task 按子计划的核心文件、完成标准和验证方法执行，不从候选预览文件反向覆盖正式规范。
3. 主题、品牌署名和页面迁移必须使用语义 token 与共享组件，不在页面中新增临时色值或重复主题判断。
4. 用户已明确授权进入开发，因此 T1.1 初始状态为“进行中”；其余任务按前置依赖顺序推进。

### 0.1 PRD 加载约束

- 必读：`docs/superpowers/specs/2026-07-23-dydata-47-space-ai-native-dark-theme-design.md` 全文。
- 只读参考：`docs/design-system/index.html`、`docs/design-system/tokens.json`、`docs/design-system/README.md`。
- 历史候选文件 `candidate-v0.2.html` 与 `tokens.v0.2-candidate.json` 只保留决策证据，不作为运行时事实源。
- “全站”指当前 `apps/web/src/pages` 下所有可路由页面和其共享组件；新增路由必须继承同一主题根节点。

### 0.2 读前门禁 / AI 自检清单

- 当前 worktree 为 `feat/dydata-47-brand-dark-mode`，不得覆盖主工作区未提交改动。
- 运行时主题只允许 `system | light | dark`，解析结果只允许 `light | dark`。
- `Powered by SPACE AI Native` 及 Ethnocentric 字体仅用于 dy-data，不写回通用资产目录。
- 成功、警告、错误、信息色保持独立语义，不被品牌橙替代。
- 任何页面级暗色修补都应先判断能否落入 token 或共享组件。

### 0.3 完成前验证门禁

- `docs/design-system`、运行时 CSS 与主题契约测试一致。
- 390、768、1440 三档视口均覆盖浅色与深色；页面无非预期水平溢出或文本遮挡。
- 主题切换支持系统偏好、手动覆盖、持久化及首次渲染无明显闪烁。
- 署名在桌面侧栏、移动端“我的”、登录/激活/重置、CLI/MCP 授权和首页按规格出现。
- `npm --prefix apps/web run build`、目标 pytest、完整 pytest 与 `git diff --check` 全部通过。

## 1. 环境依赖声明

| 依赖项 | 要求 | 检测命令 |
|---|---|---|
| Node.js | >= 18 | `node --version` |
| npm | 可安装并构建 `apps/web` | `npm --version` |
| Python | >= 3.12 | `python --version` |
| Playwright Chromium | 视觉回归可用 | `python -m playwright --version` |

## 2. 差距基线

| 差距 | 优先级 | 影响 | 对应 Task | 状态 |
|---|---|---|---|---|
| 正式规范仍声明 light-only，候选橙色未进入事实源 | P1 | 规范与已确认决策不一致 | T1.1 | 已解决 |
| 运行时只有登录页局部系统暗色，没有全局主题状态 | P1 | 页面切换与持久化缺失 | T1.2 | 已解决 |
| SPACE AI Native 署名尚未进入组件与指定页面 | P1 | 品牌归属无法一致表达 | T2.1 | 已解决 |
| 页面和共享组件仍隐含浅色背景、边线、图表色 | P1 | 深色主题不完整或对比不足 | T2.2 | 已解决 |
| 缺少双主题全路由视觉 smoke 与静态防退化 | P1 | 后续协作容易重新漂移 | T3.1 | 已解决 |

## 3. 分工与边界

| 角色 | 职责 |
|---|---|
| 主 Agent | 规格、实现、测试、视觉审计、状态同步 |
| 独立审查 Agent | 按子计划检查契约、代码质量和遗漏页面，不直接扩大范围 |
| 人类 Owner | 审核最终浅色/深色视觉与品牌署名观感，决定后续合并 |

高冲突文件由主 Agent 串行维护：`design-tokens.css`、`styles.css`、`Shell.tsx`、正式设计规范和计划状态文件。通用 SPACE 资产目录保持只读。

## 4. 执行阶段

### Phase 1：规范与运行时主题基础

**Entry Criteria**：权威规格与正式计划存在，用户已批准开发。  
**Exit Criteria**：正式 token/HTML 和运行时主题根契约一致，系统/浅色/深色切换可自动化验证。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T1.1 | [正式设计系统与主题契约](sub-delivery-plan-dydata-47-space-ai-native-dark-theme-T1.1-design-system-theme-contract.md) | 已完成（2026-07-23） |
| T1.2 | [运行时主题基础设施](sub-delivery-plan-dydata-47-space-ai-native-dark-theme-T1.2-runtime-theme-foundation.md) | 已完成（2026-07-23） |

### Phase 2：品牌署名与全页面迁移

**Entry Criteria**：Phase 1 通过目标测试和前端构建。  
**Exit Criteria**：署名覆盖矩阵完成，全部路由和共享组件在浅色/深色下使用统一 token。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T2.1 | [品牌资产与署名接入](sub-delivery-plan-dydata-47-space-ai-native-dark-theme-T2.1-signature-integration.md) | 已完成（2026-07-23） |
| T2.2 | [全站双主题 UI 迁移](sub-delivery-plan-dydata-47-space-ai-native-dark-theme-T2.2-full-ui-theme-migration.md) | 已完成（2026-07-23） |

### Phase 3：防退化与验收

**Entry Criteria**：Phase 2 代码完成且目标页面可本地访问。  
**Exit Criteria**：静态门禁、完整测试、双主题多视口视觉 smoke 和人工抽查证据齐备。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T3.1 | [自动化与视觉验收](sub-delivery-plan-dydata-47-space-ai-native-dark-theme-T3.1-verification.md) | 已完成（2026-07-23） |

## 5. 任务看板

- 看板入口：[task-kanban-dydata-47-space-ai-native-dark-theme.md](task-kanban-dydata-47-space-ai-native-dark-theme.md)

## 6. 发布闸门

- [x] 正式设计系统展示浅色与深色 token、组件和署名规范。
- [x] 主题首屏脚本、Provider、选择器和持久化契约通过测试。
- [x] 所有指定入口展示正确署名，字体和 SVG 均为项目本地资产。
- [x] 全部路由完成深色审计，语义状态色与品牌橙职责分离。
- [x] 390 / 768 / 1440 浅色与深色视觉 smoke 通过。
- [x] 前端构建、完整 pytest、设计系统静态门禁和 diff check 通过。
- [x] 不执行 Railway 部署；合并和发布由人类 Owner 后续决定。

## 7. 风险与应对

| 风险 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| 大量旧 CSS 使用层叠覆盖 | 深色下出现漏网浅色块 | 先补语义 token，再按共享组件到页面顺序审计 | 主 Agent | 已控制 |
| 系统主题与手动选择竞争 | 切换结果不可预测 | 固定 preference/resolved 两层状态并测试 matchMedia 变化 | 主 Agent | 已控制 |
| 品牌字体授权或加载失败 | 署名字形退化 | 项目内托管用户提供的字体文件，限定 dy-data 使用并保留回退字体 | 人类 Owner / 主 Agent | 已控制 |
| 图表第三方默认色不响应 CSS | 深色图表不可读 | 从 token 读取颜色并覆盖网格、轴、tooltip、series | 主 Agent | 已控制 |
| 视觉回归矩阵过大 | 测试时间增加 | 使用结构与溢出 smoke，避免像素级脆弱 diff | 主 Agent | 已控制 |

## 8. AI 执行示例

开始 T1.2 时，先同步 T1.1 三处状态为已完成、T1.2 为进行中；新增主题契约失败测试，再实现首屏脚本和 Provider。若单个页面需要硬编码暗色值，应回退检查 token 设计，而不是在页面继续增加例外。

## 9. PRD → 任务反向索引

| 需求依据 | Task | 子开发计划 |
|---|---|---|
| 规格 §2-§4 | T1.1 | [设计系统与主题契约](sub-delivery-plan-dydata-47-space-ai-native-dark-theme-T1.1-design-system-theme-contract.md) |
| 规格 §3、§7 | T1.2 | [运行时主题基础](sub-delivery-plan-dydata-47-space-ai-native-dark-theme-T1.2-runtime-theme-foundation.md) |
| 规格 §5-§6 | T2.1 | [署名接入](sub-delivery-plan-dydata-47-space-ai-native-dark-theme-T2.1-signature-integration.md) |
| 规格 §4、§8 | T2.2 | [全站迁移](sub-delivery-plan-dydata-47-space-ai-native-dark-theme-T2.2-full-ui-theme-migration.md) |
| 规格 §9 | T3.1 | [验证与验收](sub-delivery-plan-dydata-47-space-ai-native-dark-theme-T3.1-verification.md) |
