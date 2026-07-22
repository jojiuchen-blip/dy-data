# DYDATA-47 T2.1 品牌资产与署名接入

#### T2.1 建立 dy-data 专属 SPACE AI Native 署名组件并覆盖入口矩阵

**PRD 双链·读**：`docs/superpowers/specs/2026-07-23-dydata-47-space-ai-native-dark-theme-design.md` §5-§6。  
**核心逻辑**：复制原始轨道 SVG 与 Ethnocentric Regular 到项目资产；保持橙色，按主题切换中性灰；用共享组件输出 horizontal/stacked/mark 变体并按指定入口放置。  
**核心文件**：`apps/web/src/assets/brand/space-ai-native/`、`apps/web/src/components/SpaceAiSignature.tsx`、`Shell.tsx`、`HomePage.tsx`、`AuthPage.tsx`、`CliAuthorizePage.tsx`、`McpAuthorizePage.tsx`、相关 CSS 和测试。  
**完成标准**：桌面侧栏、移动端“我的”、登录/激活/重置、CLI/MCP 授权和首页均使用同一组件；SPACE 只使用确认的 SVG，POWERED BY 与 AI NATIVE 使用 Ethnocentric Regular；深色署名清晰；不修改通用资产源。  
**完成收尾：状态同步**：记录组件测试、入口契约、构建和 diff check；同步三处状态，再进入 T2.2。  
**Owner**：AI 执行 -> 人审。  
**前置**：T1.2。  
**状态**：已完成（2026-07-23）。

## Verification Method

- 品牌组件与入口契约 pytest。
- `npm --prefix apps/web run build`
- `git diff --check`

## Evidence Log

- 共享组件固定输出 `POWERED BY + SPACE SVG + AI NATIVE`，可访问名称为 `Powered by SPACE AI Native`，不再重复 SPACE。
- 横排 SPACE 宽度 84px，桌面 Rail 纵排宽度 70px；浅色与深色使用各自中性 SVG，橙色轨道保持一致。
- 5 类入口、3 档视口的深色署名契约共 `15 passed`；相关静态门禁包含在最终 `48 passed` 中。
