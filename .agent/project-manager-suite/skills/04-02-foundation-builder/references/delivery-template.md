# Phase 6: 交付清单落盘

> 本文件在进入 Phase 6 时由 SKILL.md 指令加载。

## 触发条件

Phase 5 一致性自查全部通过并获用户确认后进入。

## 交付清单模板

文件名：`docs/prd/foundation/foundation-delivery-<slug>.md`

> **主入口协议**：下方“交付产物”表不是展示用自由表格。主入口会按表头 `产物 / 文件路径` 抽取声明文件并校验是否真实存在。表头必须写作 `文件路径`，不得替换为 `主文件`、`路径`、`文件` 等同义词。

```markdown
# Foundation 交付清单 - <项目名称>

> 生成时间: YYYY-MM-DD HH:MM
> Skill: foundation-builder
> 模式: 首次 / 增量更新

## 上游依赖

| 上游 Skill | 产物文件 |
|-----------|---------|
| brd-writer | <BRD 文件路径> |
| page-designer | <page-delivery 文件路径> |

## 交付产物

| 产物 | 文件路径 | 行数 | 拆分子文件 |
|------|--------|------|----------|
| 术语表 | docs/prd/foundation/foundation-glossary-<slug>.md | N | — |
| 数据库 Schema | docs/prd/foundation/foundation-schema-<slug>.md | N | — 或 `<br>` 分隔的子文件路径清单 |
| API 接口设计 | docs/prd/foundation/foundation-api-<slug>.md | N | — 或 `<br>` 分隔的子文件路径清单 |

**"拆分子文件"列填写规则：**
- 单文件模式：填 `—`
- 拆分模式：在单元格内枚举全部子文件完整路径，一条一个路径，路径之间用 `<br>`（HTML 换行标签，Markdown 表格单元格内不能直接换行，用它表示换行）分隔。示例（单元格内容）：
  ```
  docs/prd/foundation/foundation-schema-<slug>/users.md<br>docs/prd/foundation/foundation-schema-<slug>/orders.md<br>docs/prd/foundation/foundation-schema-<slug>/products.md
  ```
- 下游消费协议见 PIPELINE.md §"产物拆分约定"；delivery 清单必须枚举全部子文件路径，不允许遗漏。下游（如 prd-writer）按 `<br>` 拆开该单元格逐条读取路径。

## 产物摘要

| 指标 | 数值 |
|------|------|
| 术语总数 | N |
| 数据表总数 | N |
| API 接口数 | N |

## 一致性自查结果

- 检查时间: YYYY-MM-DD HH:MM
- 页面字段覆盖率: x/x (100%)
- API ↔ Schema 覆盖率: x/x (100%)
- 术语一致性: 全部通过
- 孤立项: 无 / 列表

## 外部已有文件处理（若有）

| 原始文件 | 覆盖度 | 处理方式 | 废弃标注 |
|----------|--------|---------|---------|
| <文件名> | 完全/部分/不涵盖 | 融合/参考 | 已标注 |

## 下游可消费信息

| 下游 Skill | 应读取 | 用途 |
|-----------|--------|------|
| prd-writer | 本清单 + glossary + schema + api | 补充技术细节到 PRD，术语表统一全局命名 |
```

## 填写说明

| 字段 | 要求 |
|------|------|
| 文件路径 | 必须是真实存在的路径（绝对路径或相对于项目根目录的路径）；拆分模式下指向索引文件；表头必须写作 `文件路径`，供主入口路由检查识别 |
| 行数 | `wc -l` 的实际结果 |
| 拆分子文件 | 单文件模式填 `—`；拆分模式在单元格内枚举子目录下全部 `*.md` 真实路径，路径之间用 `<br>` 分隔（一条一个路径），缺一条即视为 delivery 不合格 |
| 一致性自查结果 | 直接从 Phase 5 检查结果摘要复制 |
| 外部已有文件处理 | 仅在 Phase 1 有外部已有文件时填写此节，否则删除此节 |

## 落盘后

交付清单落盘成功后，输出状态标记：

1. 执行主入口路由检查（route-check，套件的阶段门禁脚本）：

   ```bash
   node <suite-path>/tools/route-check.mjs <host-root> --target-stage S2 --json
   ```

   > `<suite-path>` 指套件根目录：源码仓库联调时为 `project-manager-suite/`，安装到宿主后为 `.agent/project-manager-suite/`；命令默认在宿主项目根目录执行。`<host-root>` 是宿主项目根目录（在宿主根执行时写 `.`）。

   在 JSON 输出的 `gateChecks.foundationReadyForPrd` 里确认 `pass = true` 即通过。`--target-stage S2` 必须带上：该检查项只在 S2 门禁下生成，漏加时输出里没有这一项。
2. 若 `foundationDeliveryExists = true` 但 `artifactsReady = false`，优先检查“交付产物”表头是否为 `文件路径`，以及该列中的路径是否真实存在
3. 检查通过后再输出完成状态：

```
【Skill状态】foundation-builder | DONE
```
