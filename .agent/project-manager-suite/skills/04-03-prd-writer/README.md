# prd-writer

面向 AI 编程的 PRD 撰写 Skill。基于已确认的页面代码和技术地基（术语表、Schema、API），产出功能列表、mainprd 和按区块拆分的 subprd。

本 skill 适用于 ai-project-manager / prd-chief 已判定进入 S2 PRD 环节，且 foundation-builder 已完成之后。上游不全时中止，不写空壳 PRD。

## 在流水线中的位置

```
BRD → page-designer → foundation-builder → prd-writer → ...
```

## 上游依赖

| 来源 Skill | 产物 |
|-----------|------|
| brd-writer | BRD 文件 |
| page-designer | 页面交付清单 + 页面代码（Vue 3） |
| page-explainer | 用户流程 + locked 交互语义 + 交付清单 |
| foundation-builder | 术语表 + Schema + API + 交付清单 |

## 产物

| 产物 | 说明 |
|------|------|
| 功能列表 | 产品背景 + 页面全景 + 区块业务逻辑 |
| mainprd | 全局索引枢纽，引用所有上游产物，索引所有 subprd |
| subprd(N份) | 按区块拆分，字段级可追溯，与 mainprd 双向引用 |

## 下游消费

| 下游 | 消费内容 |
|------|----------|
| delivery-planner | 先读 mainprd 和功能列表建立全局地图，再按任务读取相关 subprd |
| coding-standards | 通过开发计划中的 PRD 双链读取 subprd，作为实装依据 |
| prd-acceptance-reviewer | 读取每个功能子区域的 X.6 验收表，生成验收文档树 |
| test-case-writer / reviewer | 间接消费验收文档树，PRD 只作上下文 |

## 脚本校验

`scripts/prd-check.mjs` 是本 skill 的结构化反馈入口：

```bash
node <suite-path>/skills/04-03-prd-writer/scripts/prd-check.mjs structure --file docs/prd/prd-feature-list-<slug>.md --json
node <suite-path>/skills/04-03-prd-writer/scripts/prd-check.mjs crosscheck --host-dir <host> --slug <slug> --json
node <suite-path>/skills/04-03-prd-writer/scripts/prd-check.mjs progress --host-dir <host> --slug <slug> --json
node <suite-path>/skills/04-03-prd-writer/scripts/prd-check.mjs set-status --host-dir <host> --slug <slug> --block 1 --status 已确认 --json
node <suite-path>/skills/04-03-prd-writer/scripts/prd-check.mjs sync-index --host-dir <host> --slug <slug> --json
```

> `<suite-path>` 指套件根目录：源码仓库联调时为 `project-manager-suite/`，安装到宿主后为 `.agent/project-manager-suite/`；命令默认在宿主项目根目录执行。

脚本输出 `ruleId / severity / file / section / expected / actual / fixHint / nextCommand`，用于让工具协作型模型按反馈修复，而不是靠记忆模板注释。

## 核心原则

- PRD 是 AI 编程的规格说明书，不是给人看的传统文档
- 术语/Schema/API 只引用 foundation-builder 产物，不重新定义
- subprd 边界严格，字段/接口/管理页不越界
- 每个 Phase 产物落盘后先跑 `structure`，DONE 前跑 `crosscheck`
