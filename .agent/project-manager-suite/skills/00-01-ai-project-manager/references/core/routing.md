# 路由条件与项目骨架

本文件定义主入口的路由决策条件、能力映射以及宿主项目骨架补齐规则。
主入口身份、适用边界与核心红线，统一以上位规则 [`SKILL.md`](../../SKILL.md) 为准；本文件不重复定义。

协作模式、身份识别字段和访谈口径以 [`global-files-protocol.md`](./global-files-protocol.md) 与 [`runtime.md`](./runtime.md) 为准，本文件不重复定义。
阶段判断、进入子能力的必要条件、S2 页面先行协议与运行自检，统一以 [`runtime.md`](./runtime.md) 为准，本文件不重复维护。
全阶段的上游产物目录、下游消费路径、skill → 文件夹映射与宿主项目物理目录约定，统一以 [`PIPELINE.md`](../../../../PIPELINE.md) 为准；本文件只负责“什么时候该补目录、什么时候该路由”。

## 按任务阅读

- 想看主入口什么时候停留、什么时候进入子能力：看 [1. 路由条件表](#1-路由条件表)
- 想看每个阶段默认路由到哪个 skill：看 [2. 能力声明与路由目标](#2-能力声明与路由目标)
- 想看项目根目录怎么判定、启动时补哪些骨架：看 [3. 宿主项目脚手架构建规则](#3-宿主项目脚手架构建规则)
- 想看阶段触发目录什么时候创建：看 [第二层：阶段触发目录（按需创建）](#第二层阶段触发目录按需创建)
- 想看进入真实开发后再补哪些目录：看 [第三层：实现触发目录（真实开发前建）](#第三层实现触发目录真实开发前建)
- 想看技术栈约束入口：看 [4. 技术栈约束](#4-技术栈约束)

## 目录索引

- 上位规则：[`../../SKILL.md`](../../SKILL.md)
- 运行协议：[`./runtime.md`](./runtime.md)
- 全局文件协议：[`./global-files-protocol.md`](./global-files-protocol.md)
- 设计流水线与宿主目录契约：[`../../../../PIPELINE.md`](../../../../PIPELINE.md)
- 套件总览：[`../../../../README.md`](../../../../README.md)

## 对应实现与执行入口

本文件是阶段路由、能力映射、目录骨架和宿主补齐策略的唯一权威源。

对应关系：

- 结构化实现：
  - `lib/ai-pm-protocol/stages.js`
  - `lib/ai-pm-protocol/routing.js`
  - `lib/ai-pm-protocol/rules-sync.js`
  - `lib/ai-pm-protocol/change-impact-map.js`
- 对应脚本：
  - `tools/route-check.mjs`
  - `tools/bootstrap-host.mjs`
  - `tools/generate-host-rules.mjs`

维护原则：

- 若路由目标、门禁规则、页面进入条件、骨架补齐规则发生变化，先改本文件
- 若规则没变，只是脚本没有正确执行这些规则，再改结构化实现或脚本
- 不要在单个脚本里临时堆叠一套独立路由规则

---

## 1. 路由条件表

主入口根据以下条件决定其动作。**核心原则：先补骨架再补内容；先做判断再做执行。**

若运行环境支持本地工具脚本，执行顺序统一以 `runtime.md` 为准；本文件只定义“该路由到哪里、该补哪些结构”，不重复维护主入口运行流程。

| 当前上下文状态 | 主入口动作 | 是否进入子能力 | 默认输出 |
|----------------|------------|----------------|----------|
| **缺项目画像文件（新项目首次启动）** | **停留在主入口，向用户发起首轮极简访谈** | 否 | 发送访谈问题 |
| **初始访谈结束，但宿主项目缺少目录骨架** | 优先调用 `bootstrap-host.mjs` 执行物理骨架构建。全局文件遵循“能映射则映射，真缺失才创建” | 否 | 已建骨架 + 暂缓创建项 |
| **缺全局规则文件，但可从现有文件推断** | 使用内存默认推断，不强行生成物理文件 | 否 | 仅在后台标记 |
| **已有代码接入，且用户目标是补齐维护知识底座** | 进入 `project-baseline-auditor`，先基于代码生成/更新 `project-profile.md`，再输出关键文件缺口清单 | **是** | `project-profile.md` + `docs/baseline/baseline-audit-<slug>.json` |
| **已存在 baseline-audit 清单，且仍有关键文件缺口** | 读取清单中的 `recommended_next_skill`，只在 BRD / 页面说明 / foundation / PRD 范围内路由 | **是** | 交由对应补档 skill |
| **已存在 baseline-audit 清单，且推荐缺口已被对应产物满足时，主入口先刷新 baseline** | 回到 `project-baseline-auditor` 刷新当前缺口状态，再按最新 baseline 路由；下游补档 skill 不感知 baseline | **是** | 更新后的 `baseline-audit-<slug>.json` |
| **画像存在，但用户意图/入口/阶段判断等有缺口** | 停留主入口澄清并补齐 | 否 | 更新后的项目画像 |
| **当前轮目标已收敛到页面 / 原型，但"页面任务必补字段包"未补齐** | 停留主入口主动补齐 `项目覆盖对象`、`当前页面主要给谁用`、`当前页面主要用途`，并回写 `页面定位标签` | 否 | 页面任务识别信息补齐结果 |
| **当前阶段已明确，且当前轮目标对应正式阶段交付物** | 交由该阶段默认目标 skill 独占执行；主入口只负责交接上下文与回写结果 | **是** | 当前阶段最小交付物 |
| **本轮结束，不需要子能力承接大单体任务** | 直接统一回写 | 否 | 更新后的全局文件 |

> **只补文件，不进子能力的条件（归纳）**：缺骨架、缺基础画像、缺入口信息、阶段无法判断、或本轮只为对齐信息不需直接执行。
> **进入子能力的必要条件**：阶段明确、上下文统一、目标已超出主入口判断职责、且能带来具体交付物；详细门禁以 `runtime.md` 为准。
> **独占执行规则**：一旦进入子能力，当前阶段正式交付物由目标 skill 独占产出；主入口不得继续代写该阶段正文。
> **页面前置规则**：凡是页面类任务，进入 S2 前必须先由主入口主动补齐“页面任务必补字段包”；S2 的详细运行规则以 `runtime.md` 为准。
> **S2 默认路由规则**：命中 S2 时，主入口默认先进入 `page-chief`；只有页面环节已由 `page-chief` 判定 DONE，才允许切换到 `prd-chief`。

---

## 2. 能力声明与路由目标

进入子能力前，优先匹配**稳定能力名**，再由底层映射为**具体路径**。若增强版有更好实现，只需修改默认路径。
阶段表中的“最小交付物”只定义交付目标；具体模板、references 和生成细节以目标 skill 内部定义为准，本文件不展开模板路径。

| 全局伴随能力（不决定阶段归属，命中条件后随主阶段一起加载） | 默认实现路径 |
|-----------------------------------------------|--------------|
| `coding-standards` (涉及代码/结构/SQL/测试时加载) | `skills/06-01-coding-standards/` |
| `project-devlog` (每轮有实质产出、阶段切换、需要收口时加载) | `skills/00-02-project-devlog/` |
| `project-link-indexer` (阶段产物形成/拆分后，或需要文件关系、坏链、回链、孤立文件、影响范围诊断时加载) | `skills/00-03-project-link-indexer/` |

| 阶段推进能力（随阶段变化而转移） | 所属阶段 | 默认实现路径 |
|----------------------------------|----------|--------------|
| `project-baseline-auditor` (既有项目画像与关键文件缺口诊断) | S0.5 | `skills/01-01-project-baseline-auditor/` |
| `brd-writer` (业务需求文档 / BRD) | S1 | `skills/02-01-brd-writer/` |
| `page-chief` (S2 页面环节调度：`page-designer` → `page-explainer`，必要时回环) | S2 | `skills/03-01-page-chief/` |
| `prd-chief` (S2 PRD 环节调度：`foundation-builder` → `prd-writer`) | S2 | `skills/04-01-prd-chief/` |
| `delivery-planner` (任务拆解与开发计划) | S3 | `skills/05-01-delivery-planner/` |
| `test-case-chief` (S5 测试用例生成环节调度：`prd-acceptance-reviewer` → `test-case-writer` → `test-case-reviewer`) | S5 | `skills/07-01-test-case-chief/` |
| `test-case-runner` (测试执行) | S6 | `skills/08-01-test-case-runner/` |
| `security-scan` (完工前固定安全闸门扫描与放行结论) | S7 | `skills/09-01-security-scan/` |

| S2 内部执行能力（由调度层接管，不作为主入口默认直连目标） | 所属阶段 | 默认实现路径 |
|--------------------------------------------------|----------|--------------|
| `page-designer` (页面代码与页面交付清单编排) | S2 | `skills/03-02-page-designer/` |
| `page-explainer` (页面交互语义与 gap 收口) | S2 | `skills/03-03-page-explainer/` |
| `foundation-builder` (术语表 / Schema / API 技术地基设计) | S2 | `skills/04-02-foundation-builder/` |
| `prd-writer` (消费页面与 foundation 产物，沉淀 AI 可编码 PRD) | S2 | `skills/04-03-prd-writer/` |

| S5 内部执行能力（由 test-case-chief 接管，不作为主入口默认直连目标） | 所属阶段 | 默认实现路径 |
|------------------------------------------------------------|----------|--------------|
| `prd-acceptance-reviewer` (验收文档主索引 + 区块子文件) | S5 | `skills/07-02-prd-acceptance-reviewer/` |
| `test-case-writer` (测试用例编写) | S5 | `skills/07-03-test-case-writer/` |
| `test-case-reviewer` (测试用例核查) | S5 | `skills/07-04-test-case-reviewer/` |

---

## 3. 宿主项目脚手架构建规则

### 3.0 根目录判定规则

在补骨架前，先判断当前工作目录究竟是“项目根目录”还是“项目容器目录”。

- 若当前目录已经存在与该项目强绑定的全局文件、源码、构建文件或长期资料，则将当前目录视为项目根目录，直接在当前目录补骨架。
- 若当前目录更像工作区容器、集合仓库或临时承载目录，且访谈中已明确 `项目名称`，则应先创建一个与 `项目名称` 同名的物理根目录，再把项目骨架构建到该目录下。
- 若当前目录虽然暂时还是空目录，但其目录名已经等于 `项目名称`，则直接把它视为项目根目录复用，不得再额外创建一层同名子目录。
- 若当前目录下已存在同名目录，则优先复用该目录，不重复创建第二份。
- 若用户明确指定了物理落点（例如“就在当前目录初始化”），以用户指定为准，不强制创建同名子目录。

典型应创建同名根目录的信号：
- 当前目录名称明显是工作台、合集、sandbox、临时目录或总仓库名称
- 当前目录下尚无项目级全局文件、源码目录、构建文件或业务资料
- 当前轮目标是“新启动一个独立项目”，而不是“在现有项目内新增模块”

默认行为：

```text
<当前工作区>/
└── <项目名称>/
    ├── project-profile.md
    ├── project-rules.md
    ├── docs/
    ├── logs/
    └── .agent/skills/
```

### 第一层：启动必建骨架（基础续航）
只要初始化即构建，但全局文件遵循“已有则映射、缺失才创建”。不应覆盖宿主已有对应层。

```text
<项目名称>/
├── project-profile.md     (仅在宿主缺少项目画像文件时创建；已有则映射到宿主权威文件)
├── project-rules.md       (仅在宿主缺少全局规则文件时创建；已有则映射到宿主权威文件)
├── docs/plans/
│   └── execution-plan.md  (启动期 AI 记忆骨架中的当前执行计划载体)
├── docs/rules/            (宿主专项规则权威目录；首次创建后应自动从套件默认规则源补齐默认文件)
├── logs/                  (`project-devlog` 默认状态回写与开发日志目录；不再创建 `project-status.md`)
└── .agent/skills/         (宿主项目本地 AI 配置和扩充能力挂载位)
```

补充规则：
- 若宿主项目已存在可承担同职责的全局文件，主入口应记录模板与宿主文件的指向关系，后续能力直接读写宿主文件。
- 若宿主项目不存在对应全局文件，且已完成首轮必要访谈，才按默认文件名创建最小载体。
- 若通过 `bootstrap-host.mjs` 创建 `project-profile.md`，必须同时满足“访谈已结束 + 已提供结构化访谈输入 + 启动最小必需字段包完整”这 3 个条件。
- `execution-plan.md` 属于启动必建骨架，是 AI 持续记忆系统中的当前执行计划载体；若宿主缺失，应在初始化时创建最小文件。
- 若宿主 `docs/rules/` 为空或缺少默认专项规则文件，主入口在完成骨架目录创建后，应从 `skills/00-01-ai-project-manager/references/rules/` 自动补齐同名规则文件；执行时可调用批量生成脚本：`node <suite-path>/tools/generate-host-rules.mjs`。
  `<suite-path>` 指套件根目录：源码仓库联调时为 `project-manager-suite/`，安装到宿主后为 `.agent/project-manager-suite/`；命令默认在宿主项目根目录执行。
- 已存在同名宿主规则文件时不得覆盖，除非显式执行强制刷新。
- `bootstrap-host.mjs` V1 负责安全补骨架，不负责自动迁移整个套件到宿主 `.agent/`。
- 若需要把当前套件固定到宿主内执行路径，应在骨架补齐后调用 `tools/install-suite-into-host.mjs` 安装到宿主 `.agent/project-manager-suite/`；该脚本应复用宿主已有 `.agent/`，若不存在则自动创建。
- 默认不删除原套件目录；仅在显式 `--move` 时，安装成功后才删除源套件目录。

### 第二层：阶段触发目录（按需创建）
只在进入对应阶段后补建对应层级；目录名与物理落点以 `PIPELINE.md` 为准，这里只记录触发时机：
- 进入 S1：补业务需求层目录
- 进入 S2 页面环节：补页面层目录
- 进入 S2 PRD 环节：补技术地基与 PRD 层目录
- 进入 S3：补 `docs/plans/delivery-plans/` 开发计划目录；其中 `main-delivery-plan-<slug>.md`、`task-kanban-<slug>.md`、`sub-delivery-plan-<slug>-<TaskID>-<short-name>.md` 三份正式开发计划文件由 `delivery-planner` 在 S3 产出，启动期不预建
- 发生方案选型：补决策记录目录
- S4 实装中首次发现需要回改 foundation 的漂移：补 `docs/plans/foundation-plans/`
- 进入测试设计：补测试用例目录
- 需要架构总览：补架构文档入口

### 第三层：实现触发目录（真实开发前建）

适用标准：

- 只有进入真实开发或工程化协作后才有必要创建
- 代码根目录的物理落点与默认值以 `PIPELINE.md` 为准；宿主已有明确代码根目录时，优先映射宿主现有目录

满足条件时补齐：

```text
<PIPELINE 约定的实现层代码根目录>
tools/    # 仅在出现脚本、自动化、迁移需求时补建
```

触发口径：

- 代码根目录：确认进入真实开发阶段时；若宿主已有代码根目录，则只做映射，不强行新建第二套目录
- `tools/`：出现脚本、自动化、迁移需求时

内部结构约束：
- `routing.md` 只约束“是否需要补一个代码根目录”，不再预设其内部结构
- 代码根目录下的真实文件组织以宿主既有工程结构、当前 `sub-delivery-plan-<slug>-<TaskID>-<short-name>.md` 中 Task 的 `核心文件` 字段，以及具体实现阶段读取到的编码规范为准
- 若 S4 门禁发现 `docs/plans/delivery-plans/` 下正式开发计划文件组缺失、结构校验失败或 main plan / kanban / sub plan 三者状态不一致，路由目标应回到 `delivery-planner`，先生成、修复或校正 `main-delivery-plan-<slug>.md`、`task-kanban-<slug>.md` 和 `sub-delivery-plan-<slug>-<TaskID>-<short-name>.md`，不得继续进入 `coding-standards`（该文件组是 S3 阶段由 `delivery-planner` 独占产出的交付物，不属于启动必建骨架）
- 主入口识别当前为 S4 时，必须先以 `s4_pre_coding_plan_consistency_check` 为目的触发 `delivery-planner/scripts/check-plan-consistency.mjs`；只有该校验通过后，才允许把当前 Task 交给 `coding-standards`
- 若宿主已经存在 `frontend/`、`backend/`、`server/`、`web/` 等既有工程目录，优先映射现有结构，不再按 `<项目名>-frontend/`、`<项目名>-admin/` 之类的固定命名模板另造一层平行目录

> **操作纪律**：先扫描，能映射的映射，识别到真缺失再补。若只是某个次要阶段还没到，其所属目录不要提前建立。在操作结束后，给出已建和延后建的总结单。
>
> **根目录纪律补充**：若已判定当前目录只是容器目录，则“先创建 `<项目名称>/`，再在其中补骨架”属于必做步骤；不能把项目画像和规则文件直接散落在容器目录根部。
> 若当前目录名本身已经是 `<项目名称>`，则视为“已处于目标项目根目录”，不得生成 `<项目名称>/<项目名称>/` 的重复嵌套结构。

---

## 4. 技术栈约束

若当前涉及具体的技术栈开发工作，请严格遵守独立维护的技术约束规范：

- 详细技术栈参考：[`../defaults/tech-stack.md`](../defaults/tech-stack.md)

主入口与各子能力在提出技术选型、组件建议或代码实现方案时，必须默认遵循该文件中定义的前后两端框架与部署约束。
