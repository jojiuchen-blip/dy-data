# DYDATA-3 完整 V0.2 设计规范

## 目标

把 `docs/design-system/candidate-v0.2.html` 从品牌色试验页升级为可独立阅读、可独立决策的完整设计规范。V0.2 必须覆盖 V0.1 的 token、组件、图标、数据表格、响应式页面模板、决策记录和协作约束，同时保持候选状态，不进入业务运行时。

## 信息架构

V0.2 直接继承 V0.1 的完整章节顺序：规范生效方式、颜色、排版、间距与圆角、组件家族、图标体系、冻结表头、移动卡片、线索详情工作台、移动端详情、页面骨架、决策记录和协作约束。

候选品牌色说明放在颜色章节内，不再让单个业务样板承担整份规范。绿色与橙色比较保留为辅助决策工具；页面默认展示候选橙色，切换不会写入存储，也不会改变运行时文件。

## Token 模型

`tokens.v0.2-candidate.json` 继承 `tokens.json` 的完整 schema，包括 `principles`、`tokens`、`components`、`pageTemplates` 和 `enforcement`。只调整候选品牌角色和相关 focus/selected token：

- Deep Orange：`#D63B00`
- Orange：`#FE5205`
- Soft Orange：`#FFF4EF`
- Black：`#181818`
- Gray：`#686A66`
- Soft Gray：`#F2F2EE`
- White：`#FFFFFF`
- Hover：`#C73700`
- Active：`#AD3000`
- Disabled：`#DADBD6` / `#8A8C87`

成功、警告、错误和信息色继续沿用 V0.1 语义，不被品牌橙覆盖。

## 组件覆盖

按钮、IconButton、Field、Select/Combobox、Chip 家族、MetricCard、Dialog/ConfirmDialog、DataTable、分页、空/加载/错误状态、导航和移动卡片均使用候选 token 展示完整状态。品牌动作使用深橙；品牌识别、focus 和选中标记使用 `#FE5205`；选中背景使用浅橙；结构背景使用极浅灰。

## 阶段门禁

- 不修改 `apps/web/src/design-tokens.css`。
- 不修改 `apps/web/src` 下业务页面和组件。
- V0.2 HTML 和 JSON 均明确标注 `pending-human-approval` 与 `runtimeApplied: false`。
- 只有 Linear 明确记录“确认进入阶段 2”后，才允许执行 DYDATA-4。

## 验收

- V0.2 与 V0.1 具有相同的核心章节、组件组和页面模板覆盖。
- 390、768、1440 三档无全局横向溢出、重叠或裁切。
- 候选页只有一个 H1，控制台无错误。
- 候选 JSON 可解析，业务运行时不引用候选文件。
- 文档测试、设计系统门禁、完整 pytest 和前端 build 通过。
