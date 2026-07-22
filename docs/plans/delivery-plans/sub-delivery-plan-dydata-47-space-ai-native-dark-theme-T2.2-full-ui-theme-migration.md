# DYDATA-47 T2.2 全站双主题 UI 迁移

#### T2.2 迁移所有页面、共享组件、数据表与图表到双主题 token

**PRD 双链·读**：`docs/superpowers/specs/2026-07-23-dydata-47-space-ai-native-dark-theme-design.md` §4、§8。  
**核心逻辑**：按共享组件、壳层、业务页面顺序审计；消除隐含白底、浅边线和固定图表色；状态色保持语义；不改数据获取、权限和业务操作。  
**核心文件**：`apps/web/src/components/**`、`apps/web/src/pages/**`、`apps/web/src/styles.css`、`apps/web/src/design-tokens.css`、页面契约测试。  
**完成标准**：全部可路由页面在浅色/深色下文本、表面、边界、弹层、表格、图表、导航和状态反馈可读；无新增业务硬编码色值；移动端固定元素不遮挡署名或操作。  
**完成收尾：状态同步**：记录全页面清单、目标测试、构建和 diff check；同步三处状态，再进入 T3.1。  
**Owner**：AI 执行 -> 人审。  
**前置**：T2.1。  
**状态**：已完成（2026-07-23）。

## Verification Method

- 页面契约与设计系统 enforcement pytest。
- `npm --prefix apps/web run build`
- `git diff --check`

## Evidence Log

- 运行时颜色、表面、边线、阴影、图表和原生控件统一消费双主题语义 token；业务页面未增加局部主题开关。
- 18 个有效业务页面在 390 / 768 / 1440 深色组合下共 `54 passed`，主题解析、页面背景、唯一 H1、水平溢出和运行时错误均受检。
