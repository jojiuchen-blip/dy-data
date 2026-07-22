# DYDATA-47 T1.2 运行时主题基础设施

#### T1.2 建立 system/light/dark 状态、首屏解析和主题选择器

**PRD 双链·读**：`docs/superpowers/specs/2026-07-23-dydata-47-space-ai-native-dark-theme-design.md` §3、§7。  
**核心逻辑**：偏好与解析主题分层；首屏脚本在 React 前设置 `data-theme`；Provider 响应存储与系统主题变化；主题选择器在设置及未登录入口复用。  
**核心文件**：`apps/web/index.html`、`apps/web/src/main.tsx`、`apps/web/src/theme/`、`apps/web/src/design-tokens.css`、`apps/web/src/components/SolarIcon.tsx`、主题单元测试。  
**完成标准**：三种偏好可切换、刷新后保留、system 随媒体查询变化；`html[data-theme]` 和 `meta[name=theme-color]` 同步；无局部 `prefers-color-scheme` 冲突；键盘和读屏可识别主题控件。  
**完成收尾：状态同步**：记录主题测试、构建和 diff check；同步三处状态，再进入 T2.1。  
**Owner**：AI 执行 -> 人审。  
**前置**：T1.1。  
**状态**：已完成（2026-07-23）。

## Verification Method

- 主题状态目标测试。
- `npm --prefix apps/web run build`
- `git diff --check`

## Evidence Log

- `ThemeProvider`、首屏脚本和三态 `ThemePicker` 已接入；显式偏好与解析主题分层，主题色同步浏览器 chrome。
- 主题与设计系统静态门禁包含在最终 `48 passed` 目标测试中；Web production build 通过。
