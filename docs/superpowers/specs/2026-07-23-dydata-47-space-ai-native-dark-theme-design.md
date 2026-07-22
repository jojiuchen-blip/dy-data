# DYDATA-47 SPACE AI Native 署名与明暗主题设计

## 1. 状态与范围

- 需求来源：Linear `DYDATA-47`。
- 适用范围：仅限 dy-data Web 前端及 dy-data 的正式 UI 设计规范。
- 人类决策：2026-07-23 已确认 SPACE AI Native Kit，可直接进入运行时开发；同轮新增深色模式要求。
- 非目标：不改后端 API、数据库、业务数据流或业务权限；不把本署名方案扩展为其他项目的通用品牌规范。

## 2. 目标结果

1. 正式设计系统同时定义浅色和深色 token，并在规范 HTML 中可切换预览。
2. 应用默认跟随操作系统主题，用户可选择“跟随系统 / 浅色 / 深色”，选择持久化且切换无需刷新。
3. 全部业务页面、共享组件、表格、图表、弹层、认证和授权流程使用同一套明暗主题 token。
4. “Powered by SPACE AI Native” 形成 dy-data 专用组件，并只出现在约定的产品级落位。
5. 390、768、1440 三档视口在浅色和深色下均无明显溢出、重叠、空白页面或不可读控件。

## 3. 主题契约

### 3.1 主题状态

- 用户偏好枚举：`system | light | dark`。
- 本地存储键：`dydata.theme.preference`。
- 解析后的主题只允许 `light | dark`，写入 `document.documentElement.dataset.theme`。
- 用户偏好写入 `document.documentElement.dataset.themePreference`，便于测试与调试。
- `system` 通过 `matchMedia("(prefers-color-scheme: dark)")` 解析，并监听系统主题变化。
- `light` / `dark` 为显式覆盖，不受后续系统主题变化影响。
- `apps/web/index.html` 在 React 加载前执行无依赖初始化脚本，避免首屏主题闪烁；异常值回退 `system`。
- `<meta name="theme-color">` 随解析主题更新；浅色为 `#f6f6f3`，深色为 `#10110f`。

### 3.2 浅色基线

浅色保持 V0.2 已确认值：

| 角色 | 值 |
|---|---|
| 页面背景 | `#f6f6f3` |
| 卡片/弹层 | `#ffffff` |
| 次级表面 | `#f2f2ee` |
| 主文本 | `#181818` |
| 辅助文本 | `#686a66` |
| 默认边线 | `#e3e3df` |
| 强边线 | `#c9cbc6` |
| 主按钮 | `#d63b00` |
| 品牌重点 | `#fe5205` |
| 浅橙背景 | `#fff4ef` |

### 3.3 深色基线

深色通过表面明度建立层级，不依赖重阴影，也不做简单反色：

| 角色 | 值 |
|---|---|
| 页面背景 | `#10110f` |
| 卡片/弹层 | `#181a17` |
| 次级表面 | `#22241f` |
| 微弱表面 | `#141613` |
| 主文本 | `#f3f4ef` |
| 辅助文本 | `#b7b9b1` |
| 默认边线 | `#32352f` |
| 强边线 | `#4a4e45` |
| 主按钮 | `#d63b00` |
| 主按钮 Hover | `#c73700` |
| 主按钮 Active | `#ad3000` |
| 品牌重点 | `#fe5205` |
| 浅橙深色表面 | `#3b2118` |
| 浅橙文字 | `#ffb08d` |

深色状态语义保持独立：成功 `#74cdb0 / #173a30`，信息 `#8fbae8 / #1d344c`，警告 `#e9b66d / #3f2f1b`，错误 `#f49a91 / #452320`。这些颜色不纳入品牌橙替换。

### 3.4 阴影与原生控件

- 浅色沿用 V0.2 阴影层级。
- 深色卡片主要使用边线和表面明度；Popover、Dialog 仅保留低透明黑色环境阴影。
- `color-scheme` 必须随主题设置，使日期输入、滚动条和浏览器原生控件与当前主题一致。
- 所有 focus-visible 使用品牌橙 ring；文字、边线、状态和操作达到 WCAG AA。

## 4. 主题控制组件

- 组件：`ThemeProvider`、`useTheme`、`ThemePicker`。
- `ThemePicker` 使用三段式选项：跟随系统、浅色、深色；每项使用 Solar 图标与中文标签。
- 已登录桌面和移动端：放在“个人设置 / 我的”弹层内。
- 登录、激活、重置密码、CLI 授权和 MCP 授权：认证面板底部提供紧凑主题选择。
- 不在主导航、表格工具栏或业务操作区放置主题切换。

## 5. SPACE AI Native 署名

### 5.1 资产与字体

- 图形来源：`space-mark-parametric-orbit-accent.svg`，几何路径保持不变。
- 浅色 SVG：橙色轨道 `#fe5205`，SPACE 字标 `#70747a`。
- 深色 SVG：橙色轨道 `#fe5205`，SPACE 字标 `#d8dad4`。
- SPACE 只使用上述 SVG 图形字，不额外渲染 SPACE 文本或第二个 SPACE 图形。
- “POWERED BY / AI NATIVE” 使用 Ethnocentric Regular，并与 SPACE 字标使用同一主题中性色；普通 UI 字体不变。
- 字体仅在 `.space-ai-signature` 组件内引用，禁止扩展到页面标题、导航、按钮和正文。

### 5.2 组件变体

- `horizontal`：`POWERED BY [SPACE SVG] AI NATIVE`，用于认证/授权面板、首页页脚和移动端“我的”。
- `stacked`：紧凑三段堆叠，用于桌面 108px 左侧 Rail 底部。
- `mark`：只显示 SPACE 图形，仅允许 favicon / 启动识别；不得替代 Powered by 署名。
- 署名透明背景，不创建独立卡片，不抢占主操作层级。

### 5.3 运行时落位

| 场景 | 变体 | 位置 |
|---|---|---|
| 桌面已登录工作区 | `stacked` | 左侧 Rail 底部、建议入口下方 |
| 移动端已登录工作区 | `horizontal` | “我的”弹层底部 |
| 登录 / 激活 / 重置密码 | `horizontal` | 认证面板底部 |
| CLI / MCP 授权 | `horizontal` | 授权面板底部 |
| 已登录首页 | `horizontal` | 页面底部 |

不放入顶部栏、移动端底部一级导航、业务表格、业务弹层正文或每个内容区块。

## 6. 全站迁移范围

- 共享：`App`、`Shell`、按钮、图标按钮、表单、Select/Combobox、Chip、MetricCard、Dialog、DataTable、分页、ResourceState、Tooltip、二/三级导航。
- 业务页：Home、Auth、ClueCenter、StoreRanking、StoreSettlement、OrderDetails、SalesDashboard、AdminHome、AdminAccounts、AdminSkuRules、AdminProductTypeVisibility、AdminClueAllocation、AdminFeedback、AdminSync、CLI Authorize、MCP Authorize。
- 静态入口：浏览器 favicon 与 `theme-color` 保持橙色品牌识别并适配明暗浏览器 chrome。
- 运行时禁止页面级主题分叉；页面只消费语义 token。

## 7. 防退化与验证

- `tokens.json`、`index.html`、`design-tokens.css` 三者明暗核心值受测试绑定。
- 业务 TSX/CSS 不新增未授权色值；图标仍只通过 `SolarIcon`。
- 静态测试校验主题枚举、存储键、首屏脚本、署名落位和字体作用域。
- Playwright 覆盖全部有效业务路由的 390 / 768 / 1440，分别验证 light / dark。
- 每个主题检查唯一 H1、无明显水平溢出、主区域非空、无 console/page error、关键控件存在。
- 人工复核至少覆盖：设计规范、首页、线索明细、订单明细、核销表现、后台首页、登录、CLI 授权、MCP 授权。

## 8. 风险与失败处理

- 字体文件不可用：保留可读系统无衬线 fallback，并在构建/网络错误验证中阻断交付，不静默宣称品牌字体生效。
- 第三方/原生控件无法消费主题：先使用 `color-scheme` 与语义 token 修正；仍不可控时记录浏览器差异，不以 CSS filter 全局反色。
- 深色对比不足：以实际计算样式与 WCAG 对比度为准，调整 token，不在页面局部补颜色。
- 页面迁移出现布局回归：保持既有路由、数据流和组件尺寸，只修主题语义；通过既有视觉 smoke 和业务契约测试定位。
