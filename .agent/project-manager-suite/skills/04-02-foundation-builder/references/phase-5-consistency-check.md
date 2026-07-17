# Phase 5: 一致性自查

> 本文件在进入 Phase 5 时由 SKILL.md 指令加载。

## 触发条件

Phase 4 API 已获用户确认、Schema 使用接口已回填后进入。

## 输入

- 已确认的术语表（`docs/prd/foundation/foundation-glossary-<slug>.md`）
- 已确认的 Schema（`docs/prd/foundation/foundation-schema-<slug>.md`）
- 已确认的 API（`docs/prd/foundation/foundation-api-<slug>.md`）
- 页面代码文件（Vue 3 组件）
- 已冻结的交互语义（`explainer-b-interaction-<slug>.md`，仅 locked 条目）

## 检查矩阵

| # | 检查维度 | 验证逻辑 |
|---|---------|---------|
| C2 | 页面字段可写性 | 每个页面可编辑字段，能追溯到 Schema 的哪个表.哪个列，通过哪个 API 写入 |
| C3 | API ↔ Schema 覆盖 | API 响应/请求中的每个业务字段，在 Schema 中有对应列（或可由多列计算得出） |
| C4 | 术语一致性 | glossary 中定义的术语，在 Schema 表名/字段名和 API 路径/字段名中一致使用 |
| C5 | 孤立检测 | Schema 中有表/字段未被任何 API 消费 → 标记为可疑 |
| C6 | 交互语义 ↔ API 覆盖 | explainer 交互语义中每个 locked 条目的 system_behavior（涉及数据读写的），在 API 中有对应接口支撑 |
| C7 | 交互语义 ↔ Schema 覆盖 | explainer 交互语义中 validation 字段定义的校验规则，在 Schema 字段约束中有对应体现 |

> 编号保留 C2-C7（与历史版本一致），C1 旧版端侧字段检查和 C8 旧版角色矩阵检查在 v2.0.0 删除。

## 追溯表格式

### 页面字段追溯（C2）

逐页面构建追溯表：

```markdown
#### <页面名称>

| 字段名 | 写入 API | API 请求字段 | 目标表.列 | ✓/✗ |
|--------|---------|-------------|----------|------|
| 商品名称 | PUT /api/admin/product/:id | name | product.name | ✓ |
| 排序 | PUT /api/admin/product/sort | sortOrder | product.sort_order | ✓ |
```

### API ↔ Schema 覆盖检查（C3）

```markdown
| API | 方向 | 字段 | Schema 表.列 | ✓/✗ |
|-----|------|------|-------------|------|
| GET /api/admin/product | 响应 | name | product.name | ✓ |
| POST /api/admin/product | 请求 | name | product.name | ✓ |
```

### 术语一致性检查（C4）

```markdown
| 术语（glossary） | Schema 使用 | API 使用 | 一致 |
|------------------|------------|---------|------|
| 商品 | product (表名) | /api/admin/product (路径) | ✓ |
| 分类 | category (表名) | /api/admin/category (路径) | ✓ |
```

### 孤立检测（C5）

```markdown
| 表名 | 字段名 | 被 API 消费 | 状态 |
|------|--------|-----------|------|
| product | sort_order | PUT /api/admin/product/sort | ✓ 正常 |
| product | internal_memo | 无 | ⚠️ 可疑 |
```

### 交互语义 ↔ API 覆盖检查（C6）

逐个 explainer 交互语义中 locked 条目，提取 system_behavior 涉及数据读写的条目，检查 API 中是否有对应接口支撑：

```markdown
| 语义 id | trigger | system_behavior | 需要的 API | API 中存在 |
|---------|---------|-----------------|-----------|-----------|
| order-list.filter.status-dropdown.1 | 选择 | 按状态筛选列表 | GET /api/admin/orders?status= | ✓ |
| order-detail.action.cancel-btn.1 | 点击 | 提交取消请求 | PUT /api/admin/orders/:id/cancel | ✗ |
```

### 交互语义 ↔ Schema 覆盖检查（C7）

逐个 explainer 交互语义中 locked 条目，提取 validation 字段非 `none` 的条目，检查 Schema 字段约束是否对应：

```markdown
| 语义 id | validation | 对应表.列 | Schema 约束 | 一致 |
|---------|-----------|----------|------------|------|
| product-form.basic.name-input.1 | 必填，最多50字 | product.name | VARCHAR(50) NOT NULL | ✓ |
| product-form.basic.price-input.1 | 金额>0 | product.price | DECIMAL(10,2) | ⚠️ 缺 >0 约束 |
```

## 修正流程

发现不一致时：

1. **列出所有不一致项** — 汇总所有 ✗ 和 ⚠️ 项
2. **逐项分析原因**：
   - 漏设计：Schema 缺列 或 API 缺接口/字段
   - 命名不统一：术语表的命名未在 Schema/API 中一致使用
   - 多余字段：Schema 有列但无页面消费（可能是预留字段，需确认）
   - 交互语义缺 API 支撑：explainer 定义了交互但 API 未提供对应接口
   - 校验规则不匹配：explainer validation 与 Schema 字段约束不对应
3. **修正对应产物**：
   - 缺列 → 回溯修改 Schema
   - 缺接口/字段 → 回溯修改 API
   - 命名不统一 → 回溯修改 Schema/API，以术语表为准
   - 多余字段 → 与用户确认后决定保留或删除
   - 交互语义缺 API → 回溯修改 API 补充接口
   - 校验不匹配 → 回溯修改 Schema 补充约束
4. **重新执行检查矩阵** — 直到全部通过（所有项为 ✓ 或经用户确认的 ⚠️）
5. **将检查结果写入交付清单** — 作为一致性自查结果附录

## 检查结果摘要格式

```markdown
## 一致性自查结果

- 检查时间: YYYY-MM-DD HH:MM
- 页面字段覆盖率: 22/22 (100%)
- API ↔ Schema 覆盖率: 30/30 (100%)
- 术语一致性: 全部通过
- 孤立项: 无（或：2 项经用户确认保留）
- 交互语义→API 覆盖率: x/x (100%)
- 交互语义→Schema 覆盖率: x/x (100%)
```

## 用户确认要点

向用户确认时，提示关注：

1. 所有 ✗ 项是否已修正
2. ⚠️ 可疑项是否确认保留或删除
3. 整体覆盖率是否达到 100%

确认后方可进入 Phase 6。
