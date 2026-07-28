# UI 设计规范工程化说明

本目录是 dy-data 当前 UI 设计规范的工程入口。V0.2.1 是 V0.2 系列当前正式生效的浅色与深色设计系统，服务于高频筛选、比对、跟进和审核等运营后台任务。

## 正式来源

- `tokens.json`：机器可读的 V0.2 token、组件规则、页面模板和运行时契约。它是唯一的规范源文件。
- `components.json`：机器可读组件 Manifest，登记组件家族、状态、使用边界、可访问性、响应式规则、运行时实现与预览锚点。
- `index.html`：V0.2 完整可视化规范，展示浅色/深色颜色、排版、控件状态、图标、图表、表格、弹层、品牌署名与页面模板。
- `runtime-catalog.html`：真实组件 Catalog 入口；预览由 `apps/web/src/design-system` 直接导入业务 React 组件生成，不使用静态 HTML 仿制运行时组件。
- `chart-gallery/`：业务图表唯一的视觉候选库。经授权的图表实现保留几何、交互与动画，只由 `dydata-gallery-tokens.css` 映射 dy-data 品牌与语义色。
- `apps/web/src/design-tokens.css`：当前运行时 CSS token 来源，由 `apps/web/src/styles.css` 导入。
- `tests/test_design_system_docs.py`：验证正式 V0.2 元数据、核心 token、HTML 规范与运行时 CSS 绑定。
- `tests/test_design_system_enforcement.py`：验证业务代码不会绕过规范入口，例如图标必须从 `SolarIcon.tsx` 集中接入。
- `tests/test_frontend_user_facing_contracts.py`：阻止内部生产值、错误导航层级和旧版浏览器图标重新进入用户界面。

## V0.2 生效范围

- 版本为 `0.2.1`，状态为 `active`，阶段为 `runtime-active`，关联工作项为 `DYDATA-47`。
- 支持 `system | light | dark`。默认跟随系统主题，用户可以手动覆盖；偏好使用 `dydata.theme.preference` 持久化。
- 解析后的主题写入根节点 `data-theme="light|dark"`，偏好写入 `data-theme-preference`；首屏脚本必须在 React 挂载前应用主题，避免闪烁。
- 已正式记录品牌深橙、品牌橙、浅橙、黑白灰中性色、既有语义色、排版、阴影、组件状态、Solar 图标规则、ChartFigure 图表规则、二级/三级导航、浏览器标签图标和桌面明细工作台规则。
- `Powered by SPACE AI Native` 是仅用于 dy-data 的项目署名。`SPACE` 只使用确认的 SVG 图形字，`POWERED BY` 与 `AI NATIVE` 使用 Ethnocentric Regular；字体职责、三种锁定形式、明暗主题、落位矩阵和开发约束统一维护在 `index.html#brand-signature`，不得回写或改动通用品牌资产源。
- `tokens.json` 与 `apps/web/src/design-tokens.css` 的受测核心变量必须保持一致。新增或调整运行时 UI 值时，不能只修改业务页面。

## DYDATA-5 边界

移动端一级信息架构、移动端明细页面、移动端线索详情与移动端卡片样例在 V0.2 规范中仅作为 `DYDATA-5` 的未来实现记录。它们不新增现有运行时路由，也不代表当前产品已实现相应移动端行为。

## 历史候选工件

- `tokens.v0.2-candidate.json` 与 `candidate-v0.2.html` 是 DYDATA-3 的历史评审工件。
- 通用设计资产目录中的 SPACE AI Native 独立预览只保留为早期决策辅助；dy-data 后续开发以本目录 `tokens.json` 与 `index.html#brand-signature` 为准。
- 两个候选文件保持不可变，不作为当前运行时规范或后续改动入口。
- `tokens.json` 的 `promotionHistory` 和 `promotionRecord` 保留其来源、评审确认和提升结果；这些字段是历史记录，不是新的审批门禁。

## V0.2 维护流程

1. 先更新 `tokens.json`，明确 token、组件或页面模板规则。
2. 同步更新 `index.html`，使正式规范能完整展示该决策。
3. 新增或调整共享组件时，同步更新 `components.json`，并在真实 Catalog 中使用统一结构记录用途、预览、适用、避免、状态、可访问性、响应式与运行时来源。
4. 需要改变已绑定运行时变量时，同步更新 `apps/web/src/design-tokens.css` 和业务 UI；DYDATA-4 已完成首次全站运行时迁移。
5. 更新 `tests/test_design_system_docs.py`，让 V0.2 正式版、组件 Manifest、双主题契约和不可变候选历史分别受到验证。
6. 本地至少运行：

```powershell
python -m pytest tests/test_design_system_docs.py -q
npm --prefix apps/web run build:design-system
```

涉及运行时 CSS、页面或图标契约时，还应运行：

```powershell
python -m pytest tests/test_design_system_docs.py tests/test_design_system_enforcement.py tests/test_frontend_user_facing_contracts.py tests/test_frontend_clue_center.py tests/test_frontend_app_icon.py
python -m pytest tests/test_visual_smoke.py
npm --prefix apps/web run build
```

视觉 smoke 固定覆盖正式规范页和全部有效业务页面的 390、768、1440 三档宽度，检查页面可达、唯一 H1、主区域非空、无明显水平溢出和运行时错误。严格像素基线比对仍属于后续增强项。

## 协作者规则

- 不直接在业务页面新增一次性颜色、圆角、控件高度或状态色；先进入 `tokens.json` 和 `index.html`。
- 不绕过 `apps/web/src/design-tokens.css` 新增运行时颜色、阴影或控件尺寸。
- 不在业务代码里直接导入 `@iconify/react` 或 `@iconify-icons/solar/*`；新增图标先注册到 `apps/web/src/components/SolarIcon.tsx`。浏览器 favicon 是版本化静态品牌资产，不作为业务 UI 图标入口。
- 主题切换只通过共享 ThemeProvider/ThemePicker，业务页面不得自行读取 `prefers-color-scheme`、`localStorage` 或拼接页面级暗色覆盖。
- 浅色和深色必须使用同一组件结构和语义 token。成功、警告、错误、信息色保持业务语义，不纳入品牌橙替换。
- 浏览器标签图标继续使用版本化橙色资产：浅色浏览器使用 `#d63b00`，深色浏览器使用 `#fe5205`，且不增加外层色块。
- `Powered by SPACE AI Native` 通过共享组件渲染，仅用于 dy-data；组件固定输出 `POWERED BY + SPACE SVG + AI NATIVE`，桌面侧栏、移动端“我的”、登录/激活/重置、CLI/MCP 授权和首页按 placement 规则使用，不把 Ethnocentric Regular 用到普通 UI 文案。
- 内部生产值不得直接展示。订单状态、时效状态、同步任务、分配策略、事件类型和角色通过 `apps/web/src/utils/userFacingLabels.ts` 转为用户文案；API 后端错误与运行时异常通过 `apps/web/src/utils/userFacingError.ts` 转为通用失败提示。未知值显示“未知状态 / 未知类型 / 未知原因”或通用失败提示，原值和异常详情只允许进入开发日志。
- 业务页面不得直接写原生 `input`、`textarea`、`button`、私有 `tablist` 或分段按钮组。输入字段使用 `FormControls.tsx`，命令使用 `Button` / `IconButton`，视图切换和汇总筛选使用 `SelectionControls.tsx`；原生元素只保留在这些共享组件内部。
- 新增公共共享组件必须登记到 `components.json`；能够独立展示的组件必须在真实组件展厅直接导入运行时实现，不用静态 HTML 仿制。
- 必须保留的缩写在首次出现时补充中文含义，例如“门店位置编号（POI ID）”和“商品规格（SKU）”；一般用户页面不展示 MVP、Worker、数据库字段名等工程词。
- 二级导航不使用图标，统一为透明底、文字链接和 2px 品牌橙当前页下划线；父子路径同时命中时，只允许最长路径对应的导航项进入当前页状态；一级导航和明确操作可使用 Solar 图标。
- 稳定子页面必须使用 `TertiaryNav` 和独立 URL，不使用本地按钮状态模拟页面导航，也不新增第四级导航。
- 收起筛选只在筛选面板确实可折叠的窄屏布局中显示；桌面常驻筛选栏始终展开，不显示无效的收起操作。
- 不把普通信息区块伪装成指标卡；指标卡只用于看板关键监控值。
- 关键指标卡统一使用白底圆角矩形，不使用彩色顶线、彩色背景或语义色区分普通指标；信息层级依靠排列顺序、标签、数值字号和说明文字。成功、警告、错误、信息色只用于真实状态、反馈和图表语义。
- 图表先按业务问题和数据形状选型，再实现视觉；ChartFigure 的结论式标题、范围副标题、候选图形、固定解释条与来源口径属于同一组件，不拆成嵌套卡片。运行时图表颜色必须走 `--chart-*` 语义 token，默认使用品牌橙与中性色，绿/蓝/黄/红仅承担真实业务语义。
- `index.html#chart-gallery` 是业务图表唯一的视觉来源，只保留 Lupi 系（细读）、基础图表和 Glance 系（快读）三组候选规范。业务实现必须记录候选族与候选名称；Gallery 直接运行 `chart-gallery/` 中已授权参考文件，不重新绘制其几何和交互，dy-data 只通过 token 桥接颜色和明暗主题。
- 图库中没有合适候选时，先在图表库补充候选规范、适用边界和可访问性说明，再进入业务页面；不得在业务页面直接创建无法回溯到候选库的私有图形样式。
- 当前月度趋势选用 Glance 系的 `G8 Rainfall Dual Area`，核销周期分布选用同一候选库的 `G15 Jitter Strip`；运行时只替换业务数据、中文文案和 dy-data 的 `--chart-*` 配色，并统一由 `apps/web/src/components/charts/EChartsFigure.tsx` 承接 ECharts 6 SVG 渲染、主题切换、缩放和 reduced-motion。
- 业务页面不得直接导入 ECharts，也不得私有绘制 `svg` 或 `canvas` 图表。新图表先在 `chartFigure.currentRuntimeSelections` 登记候选族、候选编号、来源文件、业务映射和允许调整项，再通过 `apps/web/src/components/charts` 暴露。
- 图表必须同时支持鼠标和键盘。方向键切换数据点，Enter 或空格锁定详情，Esc 清除锁定；图形容器使用简洁的中文可读名称，稳定详情区使用 `aria-live`，不得把订单号、坐标数组或调试文本批量暴露给读屏。
- 图表标签字号不低于 `--chart-meta-font-size` 11px，主要刻度和标签使用 `--chart-label-font-size` 12px；坐标文字达到 WCAG AA 文本对比度，关键数据标记达到 3:1 非文本对比度。颜色、提示框尺寸和紧凑断点只从 `--chart-*` token 读取。
- 上述模板代码受 PolyForm Noncommercial 1.0.0 约束。必须保留 `docs/design-system/THIRD_PARTY_NOTICES.md` 中的来源、许可链接和商业使用限制；如项目用于商业目的，进入生产环境前必须取得许可方的单独授权。
- 图表悬浮与键盘焦点必须提供同等信息；点击或 Enter 可锁定选择，固定解释条使用 `aria-live`，动效遵循 `prefers-reduced-motion`。
- 不用文字字符临时模拟图标、下拉箭头或状态符号。
- 不把桌面明细长表做成页面整体滚动；使用明细工作台模板，外层视口固定、结果表格内部滚动、分页保持可见。
