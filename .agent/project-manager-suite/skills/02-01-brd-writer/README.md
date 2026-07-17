# brd-writer

用非常苛刻的评审+选项式提问逐轮收敛需求，产出可执行的 S1 阶段 BRD 文件。支持创新型、改造型、扩展型、集成型、运营型、合规型六种项目类型，根据类型动态裁剪字段和追问路径。

## 做什么

- 通过单题选项追问逐轮收敛需求
- 根据项目类型动态确定 P0 必填字段
- 产出结构化 BRD 文件，含下游交接清单

## 上游（硬依赖）

| 上游 Skill | 消费的产物 | 依赖级别 |
|-----------|-----------|---------|
| ai-project-manager | `project-profile.md` | **硬依赖** — 文件不存在或核心字段为空则拒绝开工 |
| ai-project-manager | `execution-plan.md`、已有 BRD 草稿 | 可选 — 有则参考 |

## 下游

| 下游 Skill | 提供的产物 | 用途 |
|-----------|-----------|------|
| page-designer | `BRD-<slug>-<YYYYMMDD-HHMM>.md` | 读取页面定位、使用者画像、业务模型，据此设计可交互页面 |
| page-explainer | `BRD-<slug>-<YYYYMMDD-HHMM>.md` | 读取角色诉求、各端定位，作为流程与交互语义的业务依据 |
| foundation-builder | `BRD-<slug>-<YYYYMMDD-HHMM>.md` | 读取业务模型与范围边界，反推术语表、Schema、API 时对齐业务口径 |
| prd-writer | `BRD-<slug>-<YYYYMMDD-HHMM>.md` | 读取业务目标与范围取舍，作为 PRD 的业务背景权威源 |

> 下游依赖的字段级清单以 `scripts/ledger-io.mjs` 的 `APPENDIX_DEPENDENCIES` 注册表为准（BRD 终稿的"下游交接清单"附录即按它生成）。

## 产物

| 文件 | 类型 | 说明 |
|------|------|------|
| `ledger-state-<slug>.json` | 过程产物（权威数据源） | BRD 决策台账数据，所有读写经 `scripts/` 下脚本执行 |
| `brd-ledger-<slug>.md` | 过程产物（只读展示层） | BRD 决策台账：P0 字段确认状态（locked/open）、冲突记录、轮次变更日志、充分性门槛快照。支撑跨会话恢复、回滚和终稿前确认摘要 |
| `BRD-<slug>-<YYYYMMDD-HHMM>.md` | 最终交付物 | BRD 终稿 + 下游交接清单附录。章节从 11 个候选章节（模板骨架编号跳过 §5 §7）按项目类型裁剪，保留章节由 `chapters finalize` 从 1 开始连续重编号 |

## 维护自检

改动 `scripts/ledger-io.mjs` 里的字段/章节/附录注册表，或改动 `references/p0-fields.md`、`references/brd-template.md` 后，运行对齐检查（校验脚本注册表与文档的字段数、章节数、附录行数是否一致）：

> `<suite-path>` 指套件根目录：源码仓库联调时为 `project-manager-suite/`，安装到宿主后为 `.agent/project-manager-suite/`；命令默认在宿主项目根目录执行。

```bash
node <suite-path>/skills/02-01-brd-writer/scripts/ledger-query.mjs alignment-check \
  --refs-dir <suite-path>/skills/02-01-brd-writer/references
```

输出 JSON：`aligned: true` 且 `diffs` 为空数组即通过；`diffs` 列出每处"脚本注册表 vs 文档计数"的不一致，按提示改到两侧一致为止。
