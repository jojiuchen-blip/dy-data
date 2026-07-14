---
name: project-link-indexer
description: Use when a host project needs file-level reference indexing, broken-link diagnosis, LLM wiki style navigation, impact lookup, or cross-skill artifact relationship checks across existing project-profile, BRD, page, foundation, PRD, plan, test, and code files.
---

# Project Link Indexer

本 skill 是 `project-manager-suite` 的全局伴随能力。它把宿主项目里的文件关系编译成可重建的文件级索引，方便人和 LLM 快速理解“哪个文件引用了哪个文件、哪个文件缺回链、哪个文件孤立”。

核心原则：索引是编译产物，不是业务权威源。BRD、页面说明、foundation、PRD、计划、验收、测试用例和代码仍由各自 skill 或宿主项目文件负责。

索引文件只保存宿主根目录下的相对路径；`hostRoot` 固定为 `.`，不得把开发机或 worktree 的绝对路径写入可提交产物。

## 什么时候使用

- `ai-project-manager` 的 `route-check.mjs` 在 `companionActions` 中要求调起本 skill
- 已有代码或已有文档接入后，需要建立 LLM wiki 风格的项目导航
- 用户问“这些文件之间怎么关联”“改这个文件影响哪些文件”“有没有坏链/孤立文件”
- `project-baseline-auditor` 完成后，需要给后续补档建立文件级引用图
- BRD / 页面说明 / foundation / PRD / 计划等阶段产物新增或拆分后，需要刷新索引

## 不做什么

- 不替代 `project-baseline-auditor` 诊断关键文件缺口
- 不替代 `delivery-planner` 拆任务
- 不替代任何 `test-case-*` skill 编写、审查或执行测试
- 不要求其他 skill 直接写同一个索引文件
- 不索引第三方依赖、构建产物、缓存目录、AI 工具运行目录或套件自身源码；这些目录不是宿主项目知识资产

## 输出文件

默认写入宿主项目：

```text
<host>/docs/index/project-link-graph.json
<host>/docs/index/project-link-graph.md
<host>/docs/index/project-wiki-schema.json
```

`project-link-graph.json` 给工具和主入口读取；`project-link-graph.md` 给人阅读；`project-wiki-schema.json` 固定节点、边和诊断问题的含义。

## 标准流程

1. 读取宿主根目录，确认本轮是建索引、刷新索引，还是诊断引用问题。
2. 若由主入口调度，优先运行调度入口；它会自行判断 build / refresh / noop / validate-only：

```bash
node <suite-path>/skills/00-03-project-link-indexer/scripts/run-project-link-indexer.mjs <hostRoot> --trigger <trigger> --json
```

> `<suite-path>` 指套件根目录：源码仓库联调时为 `project-manager-suite/`，安装到宿主后为 `.agent/project-manager-suite/`；命令默认在宿主项目根目录执行。

3. 若明确要强制重建索引，运行收集脚本：

```bash
node <suite-path>/skills/00-03-project-link-indexer/scripts/collect-project-links.mjs <hostRoot> --json
```

4. 若只需要检查，不写文件，运行：

```bash
node <suite-path>/skills/00-03-project-link-indexer/scripts/validate-project-links.mjs <hostRoot> --json
```

5. 把诊断结果按文件级问题反馈给用户：坏链、缺回链、孤立交付物、缺必需关系。
6. 如果用户要求刷新索引，保留原始业务文件，只重写 `docs/index/*`。

## `--trigger` 合法取值

`--trigger` 告诉调度入口本次为什么被调起，并决定"只检查"还是"允许写索引文件"：

| 取值 | 类别 | 行为 |
|---|---|---|
| `after_existing_project_baseline_audit` | 刷新类 | S0.5 baseline 诊断完成后调起；按需 build / refresh / noop，会写 `docs/index/*` |
| `artifact_files_added_or_split` | 刷新类 | BRD / 页面 / foundation / PRD / 计划 / 测试等阶段产物新增或拆分后调起；按需 build / refresh / noop，会写 `docs/index/*` |
| `need_broken_link_or_reverse_link_check` | 诊断类 | 只检查坏链 / 缺回链，返回 validate-only，不写任何文件 |
| `need_file_relationship_diagnosis` | 诊断类 | 只回答"文件之间怎么关联"，返回 validate-only，不写任何文件 |
| `need_impact_lookup` | 诊断类 | 只查"改这个文件影响哪些文件"，返回 validate-only，不写任何文件 |

传入表外取值时，脚本会在标准错误输出（stderr）打印警告，并按刷新类处理（可能重写 `docs/index/*`）。想"只诊断不写文件"，必须用上表的诊断类取值。

## 脚本清单

| 脚本 | 用途 |
|---|---|
| `scripts/run-project-link-indexer.mjs` | 调度入口，按 `--trigger` 自行判断 build / refresh / noop / validate-only；主入口调起时用它 |
| `scripts/collect-project-links.mjs` | 收集与重建脚本，扫描宿主并默认写出三个索引文件；`--dry-run` 只算不写 |
| `scripts/validate-project-links.mjs` | 只读检查脚本，输出坏链等诊断结果，不写文件 |
| `scripts/render-project-links.mjs` | `collect-project-links.mjs` 的兼容别名，行为与其完全一致（默认同样写出三个索引文件，并把人读索引打印到终端）；日常流程用上面三个脚本即可，无需单独调用它 |

## 关系来源

索引器按证据抽取关系：

- Markdown 链接：`[标题](path/to/file.md)`
- Wiki 链接：`[[path/to/file.md|标题]]`
- 计划中的 `PRD 双链·读`：反推 `delivery-plan -> PRD/foundation/page` 的 `depends_on`
- 套件命名约定：识别 `project-profile.md`、`BRD-*`、`explainer-*`、`foundation-*`、`mainprd-*`、`subprd/0X-subprd-*`、`delivery-plan-*` 等文件角色

每条边都必须保留证据位置：来源文件、行号、原文和抽取语法。

## 索引边界

索引器只扫描宿主项目的权威文档、阶段产物、业务源码、配置和测试资产。

默认排除：

- 依赖目录：`node_modules/`
- 构建产物：`dist/`、`build/`、`target/`
- 缓存和工具产物：`.vite/`、`.cache/`、`.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/`、`__pycache__/`、`.next/`、`.nuxt/`、`.turbo/`、`coverage/`
- 本地虚拟环境：`.venv/`、`venv/`
- AI 工具运行目录：`.claude/`、`.codex/`、`.cursor/`、`.playwright-mcp/`
- Git 与套件目录：`.git/`、`.agent/`、`project-manager-suite/`

该清单与 `project-baseline-auditor` 的忽略清单保持一致。

排除规则在任意目录层级生效。例如 `word-format-checker-web/node_modules/` 与根目录 `node_modules/` 都不进入索引。

## 诊断口径

常见 issue：

| code | 含义 | 处理方式 |
|---|---|---|
| `broken_link` | 文件引用的目标不存在 | 修正链接或补齐目标文件 |
| `missing_reverse_link` | 主索引指向子文件，但子文件没有回链 | 给子文件补回主文件链接 |
| `orphan_artifact` | 关键交付物没有发现任何入边或出边 | 判断是否应补引用，或确认它是独立材料 |

诊断只说明文件关系，不给阶段路由建议。

## LLM Wiki 写法

生成的人读索引可以同时保留两种链接：

- `[[docs/prd/mainprd-demo.md|mainprd]]`：方便支持 wiki link 的工具解析
- `[mainprd](../prd/mainprd-demo.md)`：普通 Markdown 可点击

不要强制改写所有原始文件为 wiki link。V1 只在生成的 `docs/index/*` 中使用这种双链接风格。
