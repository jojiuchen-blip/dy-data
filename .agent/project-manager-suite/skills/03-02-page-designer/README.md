# page-designer

基于 BRD 产出可交互的前端页面。内置设计知识库（BM25 搜索引擎 + CSV 数据），技术栈从 tech-stack.md 读取。单线 4-Phase 流程。

## 做什么

- 读 BRD → 选设计系统 → 出可交互页面 → 落交付清单
- 产物是可点击、可操作的前端页面，不是设计文档。

## 上游

| 上游 Skill | 消费的产物 | 读取的字段 |
|-----------|-----------|-----------|
| brd-writer | `BRD-<slug>-<YYYYMMDD-HHMM>.md` | 项目类型、利益相关角色与场景、核心价值模型、页面定位（操作/配置/查看） |

BRD 文件是强依赖，不存在则不启动。

## 下游

| 下游 Skill | 提供的产物 | 用途 |
|-----------|-----------|------|
| page-explainer | 交付清单 + 页面文件路径 | 沉淀交互语义、回环判断 |
| foundation-builder | 交付清单中的页面路由表 | 反推数据模型与 API |
| prd-writer | 交付清单 | 基于已确认页面反推 PRD |

下游只需读取交付清单（`page-delivery-<slug>.md`）即可索引到所有产物。

## 产物

| 文件 | 说明 |
|------|------|
| 前端页面代码 | 可交互，mock 数据 |
| `page-delivery-<slug>.md` | 交付清单，下游索引入口 |
| `page-ledger-<slug>.json` | 台账，跟踪 phase 推进与回环状态 |

## 内部结构

```
page-designer/
├── SKILL.md        # skill 定义
├── scripts/        # BM25 搜索引擎 + 台账操作
│   ├── core.py             # 搜索核心 + CSV 配置
│   ├── search.py           # CLI 入口
│   ├── design_system.py    # 设计系统生成器
│   ├── page-ledger-io.mjs       # 台账数据结构 + advance check
│   ├── page-ledger-mutate.mjs   # boot / mark-asked / advance / start-loop
│   └── page-ledger-query.mjs    # status / can-advance
├── design-db/      # 通用设计知识库 (CSV, BM25 可搜索；内容全英文，搜索用英文关键词)
│   ├── styles.csv, colors.csv, typography.csv, products.csv, charts.csv, ...
│   └── stacks/     # 13 个技术栈指南
└── docs/           # 预留目录，当前为空
```
