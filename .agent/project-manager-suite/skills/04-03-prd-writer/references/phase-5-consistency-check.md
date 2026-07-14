# Phase 5: 一致性自查

> 本文件在进入 Phase 5 时由 SKILL.md 指令加载。

## 触发条件

Phase 4 所有 subprd 完成并获用户确认后进入。

进入后先运行机械检查：

```bash
node <suite-path>/skills/04-03-prd-writer/scripts/prd-check.mjs crosscheck --host-dir <host> --slug <slug> --json
```

脚本会自动检查结构完整性、索引一致、状态闭合、Schema/API 引用、交互语义 id、页面覆盖和 Phase 5 落盘证据。`fail` 项必须先修复；`needs_ai_review` 项必须人工复核，并把结论写入 mainprd。

## 输入

- 所有已产出的 subprd 文件
- `explainer-flow-<slug>.md`（用户流程）
- `explainer-b-interaction-<slug>.md`（交互语义，仅 locked 条目）
- `docs/prd/foundation/foundation-glossary-<slug>.md`（术语表）
- `docs/prd/foundation/foundation-schema-<slug>.md`（数据库 Schema）
- `docs/prd/foundation/foundation-api-<slug>.md`（API 接口设计）
- `prd-feature-list-<slug>.md`（功能列表）
- `mainprd-<slug>.md`（mainprd）

## 检查矩阵

| # | 检查维度 | 验证逻辑 |
|---|---------|---------|
| P1 | subprd 数据链路 ↔ Schema | subprd 数据链路表中每个"来源表.列"在 foundation-schema 中存在 |
| P2 | subprd 接口引用 ↔ API | subprd 引用的每个接口在 foundation-api 中存在，字段名一致 |
| P3 | subprd 术语 ↔ 术语表 | subprd 中出现的业务术语在 foundation-glossary 中有定义 |
| P4 | subprd ↔ 功能列表 | 功能列表中的每个区块都有对应 subprd，无遗漏 |
| P5 | mainprd 索引 ↔ subprd | mainprd 的 subprd 索引表与实际产出的 subprd 一致 |
| P6 | subprd 交互 ↔ 交互语义 | subprd 中描述的交互行为与 explainer 交互语义中对应的 locked 条目一致，不自行重新定义 |
| P8 | 功能列表流程 ↔ 用户流程 | 功能列表中的页面覆盖范围与 explainer-flow 中定义的用户流程一致，无遗漏流程 |
| P9 | 功能子区域 ↔ 验收对应性 | 每个功能子区域 §X 都有 X.6 验收小节；X.6 里有且只有一张验收标准表，列固定为 `# / 类型 / 场景 / 触发条件 / 预期结果` |

> 编号保留 P1-P9（与历史版本一致），P7 旧版角色矩阵检查在 v2.0.0 删除。

## 检查方式

### P1: 数据链路 ↔ Schema

逐份 subprd，提取所有数据链路表中的"数据源（服务端读取）"和"配置源（服务端读取）"列：

```markdown
| 检查对象 | UI 元素 | 来源表.列 | 结论 |
|---------|---------|----------|------|
| 01-subprd-carousel.md | 轮播图片 | banner.image_url | ✓ |
| 02-subprd-product-recommendation.md | 分类名 | ❌ 无对应 | ✗ |
```

### P2: 接口引用 ↔ API

逐份 subprd，提取所有引用的接口路径：

```markdown
| 检查对象 | 引用接口 | foundation-api 中存在 | 字段一致 |
|---------|---------|---------------------|---------|
| 01-subprd-carousel.md | GET /api/admin/banner | ✓ | ✓ |
| 02-subprd-product-recommendation.md | GET /api/admin/product/recommend | ✗ | — |
```

### P3: 术语 ↔ 术语表

逐份 subprd，提取业务术语（非技术术语），与 foundation-glossary 对比：

```markdown
| 检查对象 | 使用术语 | glossary 中存在 |
|---------|---------|----------------|
| 01-subprd-carousel.md | 轮播 | ✓ |
| 02-subprd-product-recommendation.md | 推荐商品 | ✗ |
```

### P4: 功能列表 ↔ subprd

对比功能总表中的区块列表与实际产出的 subprd 文件：

```markdown
| 序号 | 功能区块 | 检查对象 | 结论 |
|------|----------|----------|------|
| 1 | 轮播区 | 01-subprd-carousel.md | ✓ |
| 2 | 商品推荐区 | 02-subprd-product-recommendation.md | ✓ |
| 3 | 底部导航 | — | ✗ 缺失 |
```

### P5: mainprd 索引 ↔ subprd

对比 mainprd 的 subprd 索引表与实际产出的 subprd 文件，确保双向引用完整。

### P6: subprd 交互 ↔ 交互语义

逐份 subprd，提取交互行为描述，与 explainer-b-interaction 中对应的 locked 语义条目对比：

```markdown
| 检查对象 | 交互描述 | 语义 id | explainer 定义 | 一致 |
|---------|---------|---------|---------------|------|
| 01-subprd-carousel.md | 点击轮播跳转详情 | banner.carousel.item.1 | trigger=点击, system_behavior=跳转商品详情 | ✓ |
| 02-subprd-product-recommendation.md | 下拉刷新加载更多 | — | 无对应 locked 条目 | ✗ 自行定义 |
```

subprd 不得自行定义交互行为，必须在 X.1 的 `**交互语义引用**：` 槽位引用 explainer 已 locked 的语义条目。若发现缺失，标记为「需回溯 page-explainer 补充」。

### P8: 功能列表流程 ↔ 用户流程

对比 explainer-flow 中定义的用户流程与功能列表中的页面覆盖范围：

```markdown
| 流程 | 涉及页面 | 功能列表中覆盖 | 一致 |
|------|---------|-------------|------|
| 下单流程 | 商品详情→购物车→结算→支付 | 4/4 页面均有区块 | ✓ |
| 退款流程 | 订单详情→退款申请→退款进度 | 2/3 页面有区块 | ✗ 退款进度页缺失 |
```

### P9: 功能子区域 ↔ 验收对应性

逐份 subprd，检查每个功能子区域 §X 的 X.6 验收小节：

```markdown
| 检查对象 | 功能子区域 | X.6 存在 | 验收表列正确 | 一致 |
|---------|-----------|---------|-----------|------|
| 01-subprd-carousel.md | §4 轮播展示 | ✓ | ✓ | ✓ |
| 02-subprd-product-recommendation.md | §5 分类筛选 | ❌ 缺 | — | ✗ |
```

X.6 里的验收表列必须严格为 `# / 类型 / 场景 / 触发条件 / 预期结果`。"类型"取值限于 `业务规则 / UX 交互 / 异常兜底`（按该子区域实际涉及的维度写）。

## 不一致时的处理

| 不一致类型 | 处理方式 |
|-----------|---------|
| subprd 写错（引用了不存在的表/接口/术语） | 修正 subprd |
| foundation 产物漏了（确实需要新增字段/接口） | 标记为"需回溯 foundation-builder 补充" |
| 功能列表有区块但缺 subprd | 补写缺失的 subprd |
| mainprd 索引不完整 | 回填 mainprd 索引表 |
| subprd 自行定义了交互行为（无对应 locked 语义） | 标记为"需回溯 page-explainer 补充" |
| 用户流程涉及的页面在功能列表中缺失 | 补充功能列表中的缺失区块 |
| 功能子区域 §X 缺 X.6 / X.6 验收表列不符合规范 | 修正 subprd，补齐 X.6 或调整验收表结构 |

**回溯 foundation-builder**：如果检查发现 foundation 产物确实缺少了 subprd 需要的表/字段/接口，不在 prd-writer 中自行定义，而是：
1. 列出所有需要 foundation-builder 补充的项
2. 向用户报告，由用户决定是否触发 foundation-builder 增量更新
3. foundation-builder 更新完成后，重新执行 Phase 5 检查

## 检查结果摘要

检查结果必须写入 `mainprd-<slug>.md` 的 `## 一致性自查结果`。使用 bullet 摘要，不要写 `| # | 区块 | subprd 文件 | 存在 |` 这类表头；该表头会污染 route-check 的 PRD 索引解析。

```markdown
## 一致性自查结果

- 检查时间: YYYY-MM-DD HH:MM
- P1 数据链路覆盖: x/x (100%)
- P2 接口引用覆盖: x/x (100%)
- P3 术语覆盖: 已人工复核
- P4 功能列表→subprd: x/x (100%)
- P5 mainprd 索引完整: ✓
- P6 交互语义一致: x/x (100%)
- P8 流程覆盖: 已人工复核
- P9 功能子区域 ↔ 验收对应性: x/x (100%)
- 需回溯 foundation-builder: 无 / 列表

## 待回溯缺口

| 缺口 | 类型 | 回溯目标 | 状态 |
|---|---|---|---|
| 无 | — | — | resolved |
```

摘要值口径（与 main-prd 模板一致）：P3 / P8 是语义比对维度，填人工复核结论 `已人工复核` 或 `待复核`，不写 x/x 计数；其余可机械计数的维度写 `x/x (percent%)`。
