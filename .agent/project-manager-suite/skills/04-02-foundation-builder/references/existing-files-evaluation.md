# 外部已有文件评估与融合

> 本文件在 Phase 1 中用户提供已有数据库/接口文件时由 SKILL.md 指令加载。
> 影响 Phase 2/3/4 的执行逻辑。

## 触发条件

Phase 1 询问用户是否有已有数据库/接口文件，用户回答"有"时加载。

## 评估流程

```
读取用户提供的已有文件
  ↓
与上游需求（页面代码 + BRD）对比，判定覆盖度：
  ↓
  ┌─ 完全涵盖：已有文件覆盖当前所有页面的数据需求
  │   → 以已有为基础，按 coding-standards 规范重新整理格式
  │   → 保留已有的表结构/字段，统一命名到术语表
  │
  ├─ 部分涵盖：已有文件覆盖了部分需求
  │   → 已有部分：按规范重新整理
  │   → 缺失部分：从页面代码新推导补充
  │   → 合并为完整产物
  │
  └─ 不涵盖：已有文件与当前需求基本无关
      → 从零设计，已有文件仅作参考
```

## 覆盖度判定标准

| 维度 | 判定方法 |
|------|---------|
| 表/接口数量覆盖 | 已有文件的表/接口数 vs 页面代码推导出的需求数 |
| 字段覆盖 | 已有表的字段 vs 页面渲染/提交的字段集合 |
| 命名规范符合度 | 已有命名 vs coding-standards 规范 |

**判定阈值**：
- 完全涵盖：表/接口数量覆盖 ≥ 90% 且字段覆盖 ≥ 90%
- 部分涵盖：表/接口数量覆盖 30%~90% 或字段覆盖 30%~90%
- 不涵盖：表/接口数量覆盖 < 30% 且字段覆盖 < 30%

## 各覆盖度的处理方式

### 完全涵盖

1. 以已有文件为基础
2. 按 coding-standards 规范重新整理格式（表名、字段名、索引命名等）
3. 补充缺失的规范强制字段（id/gmt_create/gmt_modified）
4. 将已有的命名纳入术语表统一管理
5. 产出新的 `docs/prd/foundation/foundation-{schema,api}-<slug>.md`

### 部分涵盖

1. 已有覆盖的部分：按规范重新整理
2. 缺失的部分：从页面代码新推导，按正常 Phase 3/4 逻辑设计
3. 合并为完整产物
4. 产出新的 `docs/prd/foundation/foundation-{schema,api}-<slug>.md`

### 不涵盖

1. 按正常流程从零设计
2. 已有文件仅作为背景参考（了解用户原有的命名习惯等）
3. 产出新的 `docs/prd/foundation/foundation-{schema,api}-<slug>.md`

## 融合后的两个动作

### 动作 1: 产出新文件

产出 `docs/prd/foundation/foundation-schema-<slug>.md` 和/或 `docs/prd/foundation/foundation-api-<slug>.md`，是融合后的完整产物。格式遵循 Phase 3/4 的产物模板。

### 动作 2: 标注原始文件废弃

在用户提供的原始文件头部插入三层废弃标注：

```markdown
---
⛔ DEPRECATED — 本文件已停止维护
superseded_by: docs/prd/foundation/foundation-schema-<slug>.md
deprecated_at: YYYY-MM-DD HH:MM
deprecated_by: foundation-builder
---

> **⛔ 请勿使用本文件**
> 本文件内容已融合至 [foundation-schema-<slug>.md](docs/prd/foundation/foundation-schema-<slug>.md)，以该文件为准。
> 本文件仅作历史留档，不再更新。

（以下为原始内容，不再维护）

---
```

**三层保障**：
1. **frontmatter**：机器可读，下游 skill 可自动检测 `DEPRECATED` 标记
2. **告警块**：人眼/AI 扫描文件时第一时间看到
3. **分隔线**：视觉隔离原始内容，明确标注不再维护

## 向用户呈现评估结果

评估完成后，向用户呈现：

```
已有文件评估结果：

文件: <用户提供的文件名>
覆盖度: 完全涵盖 / 部分涵盖 / 不涵盖
  - 表/接口数量覆盖: X/Y (Z%)
  - 字段覆盖: X/Y (Z%)
  - 命名规范符合度: 高/中/低

处理方式: <对应的处理方式描述>

注意: 融合完成后，原始文件将被标注为废弃（DEPRECATED），以防下游误用。

是否继续？
```
