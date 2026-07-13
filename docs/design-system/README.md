# UI 设计规范工程化说明

本目录是 dy-data 当前 UI 设计规范的工程入口。V0.2 是正式生效的浅色设计系统，服务于高频筛选、比对、跟进和审核等运营后台任务。

## 正式来源

- `tokens.json`：机器可读的 V0.2 token、组件规则、页面模板和运行时契约。它是唯一的规范源文件。
- `index.html`：V0.2 完整可视化规范，展示颜色、排版、控件状态、图标、表格、弹层与桌面页面模板。
- `apps/web/src/design-tokens.css`：当前运行时 CSS token 来源，由 `apps/web/src/styles.css` 导入。
- `tests/test_design_system_docs.py`：验证正式 V0.2 元数据、核心 token、HTML 规范与运行时 CSS 绑定。
- `tests/test_design_system_enforcement.py`：验证业务代码不会绕过规范入口，例如图标必须从 `SolarIcon.tsx` 集中接入。

## V0.2 生效范围

- 版本为 `0.2.0`，状态为 `active`，阶段为 `runtime-active`，关联工作项为 `DYDATA-4`。
- 只支持 `light-only`；暗色模式不属于 V0.2。
- 已正式记录品牌深橙、品牌橙、浅橙、黑白灰中性色、既有语义色、排版、阴影、组件状态、Solar 图标规则、三级导航和桌面明细工作台规则。
- `tokens.json` 与 `apps/web/src/design-tokens.css` 的受测核心变量必须保持一致。新增或调整运行时 UI 值时，不能只修改业务页面。

## DYDATA-5 边界

移动端一级信息架构、移动端明细页面、移动端线索详情与移动端卡片样例在 V0.2 规范中仅作为 `DYDATA-5` 的未来实现记录。它们不新增现有运行时路由，也不代表当前产品已实现相应移动端行为。

## 历史候选工件

- `tokens.v0.2-candidate.json` 与 `candidate-v0.2.html` 是 DYDATA-3 的历史评审工件。
- 两个候选文件保持不可变，不作为当前运行时规范或后续改动入口。
- `tokens.json` 的 `promotionHistory` 和 `promotionRecord` 保留其来源、评审确认和提升结果；这些字段是历史记录，不是新的审批门禁。

## V0.2 维护流程

1. 先更新 `tokens.json`，明确 token、组件或页面模板规则。
2. 同步更新 `index.html`，使正式规范能完整展示该决策。
3. 需要改变已绑定运行时变量时，同步更新 `apps/web/src/design-tokens.css` 和业务 UI；DYDATA-4 已完成首次全站运行时迁移。
4. 更新 `tests/test_design_system_docs.py`，让 V0.2 正式版和不可变候选历史分别受到验证。
5. 本地至少运行：

```powershell
python -m pytest tests/test_design_system_docs.py -q
```

涉及运行时 CSS、页面或图标契约时，还应运行：

```powershell
python -m pytest tests/test_design_system_docs.py tests/test_design_system_enforcement.py tests/test_frontend_clue_center.py tests/test_frontend_app_icon.py
python -m pytest tests/test_visual_smoke.py
npm --prefix apps/web run build
```

视觉 smoke 固定覆盖正式规范页和全部有效业务页面的 390、768、1440 三档宽度，检查页面可达、唯一 H1、主区域非空、无明显水平溢出和运行时错误。严格像素基线比对仍属于后续增强项。

## 协作者规则

- 不直接在业务页面新增一次性颜色、圆角、控件高度或状态色；先进入 `tokens.json` 和 `index.html`。
- 不绕过 `apps/web/src/design-tokens.css` 新增运行时颜色、阴影或控件尺寸。
- 不在业务代码里直接导入 `@iconify/react` 或 `@iconify-icons/solar/*`；新增图标先注册到 `apps/web/src/components/SolarIcon.tsx`。
- 不把浏览器系统暗色模式适配写入 V0.2；暗色模式需要独立设计、预览、测试和迁移计划。
- 不把普通信息区块伪装成指标卡；指标卡只用于看板关键监控值。
- 不用文字字符临时模拟图标、下拉箭头或状态符号。
- 不把桌面明细长表做成页面整体滚动；使用明细工作台模板，外层视口固定、结果表格内部滚动、分页保持可见。
