# Phase 3: 数据库 Schema 设计

> 本文件在进入 Phase 3 时由 SKILL.md 指令加载。
> 同时加载：`coding-standards/references/05-mysql-table.md`

## 触发条件

Phase 2 术语表已获用户确认后进入。

## 输入

- 已确认的术语表（`docs/prd/foundation/foundation-glossary-<slug>.md`）
- 页面代码文件（Vue 3 组件）
- BRD 文件
- `coding-standards/references/05-mysql-table.md`（外部规范，运行时读取）

## 页面 → 表映射逻辑

```
页面代码分析
  ↓
提取页面渲染的数据字段
  - <template> 中绑定的变量（v-for 循环项的字段、{{ }} 插值）
  - API 调用的响应消费（axios/fetch 的 .then/.data 取值路径）
  - 表单提交字段（v-model 绑定的字段、提交 payload 结构）
  ↓
按业务实体聚合字段
  - 同一实体的字段可能分布在多个页面
  - 实体边界判断：共享同一主键引用的字段归属同一实体
  ↓
一个业务实体 → 一张主表
  ↓
特殊字段处理：
  - 富媒体字段（image[]、file[]）→ 少量（≤3）用 JSON 列，大量或需独立查询则拆子表
  - 枚举字段（状态、类型）→ tinyint/smallint + 注释定义枚举值
  - 排序字段（拖拽排序、手动排序）→ 增加 sort_order int unsigned 列
  - 布尔字段 → is_xxx tinyint unsigned（0/1）
  - 金额字段 → decimal(M,N)，禁止 float/double
  ↓
补充 coding-standards/05 强制字段：
  - id bigint unsigned NOT NULL AUTO_INCREMENT
  - gmt_create datetime NOT NULL DEFAULT CURRENT_TIMESTAMP
  - gmt_modified datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
  ↓
按业务域分组，设计索引
  - 主键：pk_<table>
  - 唯一索引：uk_<table>_<column(s)>
  - 普通索引：idx_<table>_<column(s)>
```

## 字段来源映射

直接从 BRD 业务模型 + 页面字段推导。每个页面渲染/编辑的字段都映射到具体表.列。

| 来源 | 字段类型 | 对表结构的影响 |
|------|---------|--------------|
| 页面读取类字段（列表展示、详情展示） | 决定表需要哪些列 |
| 页面写入类字段（表单编辑、配置开关） | 决定哪些列可编辑、数据类型约束 |

同一字段在多处出现时，以写入端的类型约束为准（写入端是数据来源方）。

## coding-standards/05 规范要点（提醒）

加载 `coding-standards/references/05-mysql-table.md` 后，重点关注：

- 表名：小写 + 下划线，不用复数
- varchar 不超过 5000，超过用 text
- 禁止外键与级联，外键逻辑在应用层解决
- 每张表必须有注释说明用途
- 索引命名规范：pk_/uk_/idx_

## 产物模板

文件名：`docs/prd/foundation/foundation-schema-<slug>.md`

```markdown
# Database Schema - <项目名称>

> 生成时间: YYYY-MM-DD HH:MM
> 来源: foundation-builder Phase 3
> 关联: [术语表](foundation-glossary-<slug>.md) · [API](foundation-api-<slug>.md)

---

## §1 全表总览

| # | 表名 | 所属业务域 | 来源 | 作用 | 定义于 |
|---|------|----------|------|------|--------|
| 1 | xxx | xxx | 自建 | xxx | §2.1 |
| 2 | xxx | xxx | 外部·纯引用 | xxx | §2.2 |
| 3 | xxx | xxx | 外部·需改动 | xxx | §2.3 |

---

## §2 <业务域 A>

### 2.1 `table_name` — 表说明

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 主键 |
| ... | ... | ... | ... | ... | ... |
| gmt_create | datetime | NO | | CURRENT_TIMESTAMP | 创建时间 |
| gmt_modified | datetime | NO | | CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- `pk_table_name` (id)
- `idx_table_name_xxx` (xxx)

**使用接口**（Phase 4 完成后回填）：
- `GET /api/xxx` — 用途
- `PUT /api/admin/xxx` — 用途

> 若来源为"外部引用"，表详情格式改为：
>
> ### N.M `external_table` — 表说明（外部引用）
>
> - **对接方**：<系统名称>
> - **文档地址**：<链接>
> - **本项目使用方式**：只读 / 读写 / 同步
> - **是否需改动**：是（说明需要加哪些字段/改哪些结构）/ 否（纯引用）
> - **关键字段**：列出本项目实际消费的字段
>
> 外部引用的表不设计索引、不补充强制字段，只记录本项目消费的字段和对接信息。需改动的外部表须明确列出改动项。
```

## 拆分规则

当产物超过 400 行时，拆为索引文件 + 子文件目录：

```
docs/prd/foundation/foundation-schema-<slug>.md          ← 索引文件
  内容：全表总览表格 + 每张表的一行摘要 + 指向子文件的链接

docs/prd/foundation/foundation-schema-<slug>/
  ├── <table_name_1>.md              ← 单表完整定义（字段表格 + 索引 + 使用接口）
  ├── <table_name_2>.md
  └── ...
```

索引文件中每张表的格式：

```markdown
### 2.1 `table_name` — 表说明

> 字段数: N | 索引数: M
> 详见: [table_name.md](foundation-schema-<slug>/table_name.md)
```

## 增量模式

若已有前次 `docs/prd/foundation/foundation-schema-<slug>.md`：

1. 对比当前页面字段需求与已有表结构
2. **新增**：新页面引入的新实体 → 新增表
3. **变更**：已有表的字段增减 → 更新字段表格
4. **可疑**：前次存在但当前页面不再消费的表 → 标记为 `⚠️ 待确认`
5. 变更表格中增加 `变更` 列标记

## 表名/字段名命名

必须使用术语表（`docs/prd/foundation/foundation-glossary-<slug>.md`）中的统一术语作为表名和字段名的来源。术语的中文名对应英文翻译作为实际命名。

## 用户确认要点

向用户确认时，提示关注：

1. 表结构是否覆盖了所有页面的数据需求
2. 字段类型是否合理
3. 索引设计是否满足查询场景
4. 是否遗漏关联关系（虽然禁止外键，但表间关系需在说明中体现）

确认后方可进入 Phase 4。
