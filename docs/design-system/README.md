# UI 设计规范工程化说明

这个目录是 dy-data 当前 UI 设计规范的工程入口。它不是口头约定，也不是一次性的视觉稿，而是后续页面和组件改造时必须同步维护的依据。

## 事实来源

- `tokens.json`：机器可读的 token、组件规则、页面模板和当前守门范围。
- `index.html`：所见即所得的人工决策预览，用来判断颜色、排版、控件、图标、表格冻结和移动端卡片是否合适。
- `tests/test_design_system_docs.py`：验证规范文档、核心 token 与当前前端实现的绑定关系。
- `tests/test_design_system_enforcement.py`：验证协作者不会绕过规范入口，例如图标必须从 `SolarIcon.tsx` 集中接入。

## 当前生效范围

- V0.1 只承诺浅色模式，设计规范预览不跟随系统暗色模式。
- 当前已约束核心颜色、字体、间距、圆角、控件高度、层级、阴影、图标来源、表格冻结间距和移动端线索卡片结构。
- 当前已通过静态测试绑定部分 CSS 变量、规范 HTML 必备区块、图标入口和文档说明。
- 当前还不是完整组件库，也不会自动把所有 token 生成到业务 CSS。

## UI 改动流程

1. 如果要新增或调整颜色、圆角、控件高度、表格冻结间距、图标风格，先改 `tokens.json`。
2. 同步更新 `index.html`，让人能直接看到改动后的实际效果。
3. 再改业务 UI 的 CSS 或组件实现，避免页面先产生一套临时样式。
4. 同步补充或调整测试，保证新规则能被 CI 拦住。
5. 本地至少运行：

```powershell
python -m pytest tests/test_design_system_docs.py tests/test_design_system_enforcement.py tests/test_frontend_clue_center.py tests/test_frontend_app_icon.py
npm --prefix apps/web run build
```

## 协作者规则

- 不直接在业务页面里新增一次性颜色、圆角、控件高度或状态色；确实需要新增时，先进入 `tokens.json` 和 `index.html` 决策。
- 不在业务代码里直接导入 `@iconify/react` 或 `@iconify-icons/solar/*`；新增图标必须先注册到 `apps/web/src/components/SolarIcon.tsx`。
- 不把浏览器系统暗色模式适配写进 V0.1 规范预览；暗色模式需要单独设计、预览、测试和迁移计划。
- 不把普通信息区块伪装成指标卡；指标卡只用于看板上的关键监控值。
- 不用文字字符临时模拟图标、下拉箭头或状态符号；需要图标时使用统一图标入口。

## 下一阶段

- 把 app 根 CSS 变量迁移成由 `tokens.json` 生成或共享的 token 文件。
- 为核心组件和关键页面增加截图回归。
- 在 PR 模板中加入 UI 设计规范检查项。
- 在颜色稳定后增加更严格的业务 CSS 颜色扫描，减少散落 hex 值。
