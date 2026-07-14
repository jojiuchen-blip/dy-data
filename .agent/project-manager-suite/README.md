# Project Manager Suite

> **当前版本：2.0**（2026-07-10）。变更摘要见 [版本历史](#版本历史)。

## 快速概览

`project-manager-suite` 不是零散的 prompt 集合，也不是文档生成工具，而是一个面向业务到研发落地场景的 **AI 开发助手套件**。

它通过 `ai-project-manager` 作为内部唯一总入口，结合全局规则、项目画像、执行计划和状态回写，把模糊的业务想法持续推进成可执行、可回写、可验收的开发落地过程。

第一次使用时，建议先看 [安装与使用](#安装与使用)；想先理解它怎么运转，再看 [核心运行机制](#核心运行机制)。

## 按目的阅读

- 首次了解套件：看 [什么是 Project Manager Suite？](#什么是-project-manager-suite)
- 快速安装到宿主：看 [安装与使用](#安装与使用)
- 理解主入口和推进链路：看 [核心运行机制](#核心运行机制)
- 排查目录和文件职责：看 [套件目录结构](#套件目录结构)
- 查看 skill 职责边界：看 [能力分工](#能力分工)
- 查看补充资料：看 [延伸阅读](#延伸阅读)

## 什么是 Project Manager Suite？

`project-manager-suite` 的定位是 **宿主项目可挂载的通用开发助手套件**，而不是绑定某个单一业务项目的私有模板。仓库中的技术栈、接口、测试目录、PRD 结构等内容，默认都应理解为可替换的参考实现或示例约定，实际落地时由宿主项目按自身规则进行映射。

对外产品定位统一按“开发助手”理解；仓库内保留 `ai-project-manager` 这一内部主入口名，是为了延续既有协议、脚本和 skill 路由，不代表对外仍以“项目经理”作为产品名称。

本套件的核心价值：

- 给开发落地过程提供默认推进骨架
- 给 AI 提供稳定上下文载体，不再依赖聊天记录临时记忆
- 给用户提供当前轮的最小下一步建议
- 给宿主项目提供可持续回写和滚动推进机制
- 给不同 AI IDE 和不同宿主项目提供可迁移的协作协议

从产品能力抽象来看，`project-manager-suite` 可以概括为 5 个相互配合的层：

- **需求接入层**：由 `ai-project-manager` 接住模糊需求，完成最小访谈、项目画像建立和骨架补齐
- **既有项目接入层**：由 `project-baseline-auditor` 基于已有代码补齐项目画像线索，并诊断 BRD / 页面说明 / foundation / PRD 缺口
- **持续记忆底座**：由项目画像、全局规则、执行计划和状态回写共同构成，让 AI 能跨轮恢复上下文
- **工程化流程编排层**：按阶段判断、最小交付物控制、能力路由和人工确认节点推进开发落地，避免 AI 失控扩写
- **专业执行层**：由需求、UI/UX、PRD、计划、研发、测试、验收等子能力承接具体交付

这 5 层叠加后的产品价值，不是多几个 prompt 或多几份文档模板，而是把项目从启动到交付收口的过程做成可持续运行的 AI 开发助手系统。

## 安装与使用

由于套件各组件存在强关联，对外分发时必须作为 **整体标准交付单位**。如果要在新项目中使用本套件，请将完整 `project-manager-suite` 安装到目标项目的 `.agent/project-manager-suite` 目录中，不可单独抽取某个子能力，例如只复制 `ai-project-manager` 目录。

推荐安装方式有两种：

- 直接整体复制到宿主 `.agent/project-manager-suite`
- 在套件源码仓库或已安装套件中运行：

```bash
node project-manager-suite/tools/install-suite-into-host.mjs <host-project-root>
```

安装补充说明：

- 安装脚本会复用宿主已有 `.agent/` 目录；若宿主没有 `.agent/`，脚本会自动创建
- 安装脚本只管理 `.agent/project-manager-suite/`，不会覆盖宿主 `.agent/` 下其他插件或配置
- 推荐先通过 `bootstrap-host.mjs` 完成宿主骨架补齐，再安装或同步套件到宿主内路径
- 安装完成后，后续命令应优先使用宿主内套件路径，例如 `node .agent/project-manager-suite/tools/generate-host-rules.mjs <host-project-root>`

### 命令路径统一约定（`<suite-path>`）

套件内所有文档给出脚本命令时，统一写成 `node <suite-path>/skills/<skill 名>/scripts/<脚本名>.mjs` 或 `node <suite-path>/tools/<脚本名>.mjs` 的形式。`<suite-path>` 指套件根目录，按所处环境取值：

| 所处环境 | `<suite-path>` 取值 | 示例 |
|---------|--------------------|------|
| 在套件源码仓库内联调 | `project-manager-suite/` | `node project-manager-suite/tools/route-check.mjs <host-project-root>` |
| 套件已安装到宿主项目 | `.agent/project-manager-suite/` | `node .agent/project-manager-suite/tools/route-check.mjs <host-project-root>` |

命令默认在**宿主项目根目录**执行。若按替换后的路径找不到脚本，应先核对套件的实际安装位置并修正路径，而不是跳过脚本改为纯文字判断——脚本门禁是流水线质量的兜底。

### 会话启动自动注入（Claude Code hooks 注册）

套件自带一个 session-start hook（`hooks/session-start`，会话启动时运行的脚本），作用是在每次会话开始时自动把 `ai-project-manager` 主入口内容注入到上下文，让"项目启动 / 推进"类请求默认走主入口。**这是"已装套件场景由 hook 自动注入"真正生效的前提：不完成本节注册，自动注入不会发生**，需要手动 `Read` 主入口 SKILL.md。

注册方式（Claude Code）：在宿主项目的 `.claude/settings.json`（项目级配置文件）中加入以下片段：

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|clear|compact",
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR/.agent/project-manager-suite/hooks/session-start\""
          }
        ]
      }
    ]
  }
}
```

注意事项：

- `$CLAUDE_PROJECT_DIR` 是 Claude Code 在运行 hook 时提供的宿主项目根目录变量；command 整体用引号包裹，避免路径含空格时解析失败
- `hooks/session-start` 与 `hooks/run-hook.cmd`（Windows 下的转发入口）需要有可执行权限；仓库内已带执行位，若复制安装后丢失，执行 `chmod +x .agent/project-manager-suite/hooks/session-start .agent/project-manager-suite/hooks/run-hook.cmd` 补上
- Windows 下将 command 换成 `"%CLAUDE_PROJECT_DIR%\\.agent\\project-manager-suite\\hooks\\run-hook.cmd" session-start`，由它转发给 Git Bash 执行
- `hooks/hooks.json` 是套件作为 Claude Code 插件分发时的 hook 声明（依赖插件机制提供的 `${CLAUDE_PLUGIN_ROOT}` 变量），只在插件安装形态下自动生效；普通复制 / 脚本安装到 `.agent/` 的场景必须按上面的方式手动注册
- 验证方式：注册后重启会话，若启动时上下文里出现 ai-project-manager 主入口内容（或宿主终端运行 `bash .agent/project-manager-suite/hooks/session-start` 能输出一段 JSON），说明链路已通

接入宿主项目时，优先做的是 **角色映射**，不是强制重命名现有文档：

- 把宿主项目现有的规则入口映射为“全局规则文件”
- 把宿主项目现有的计划入口映射为“当前执行计划文件”
- 把宿主项目现有的日志或状态沉淀入口映射为“状态回写能力”
- 若缺失稳定的项目快照载体，再补齐“项目画像文件”

<details>
<summary>宿主专项规则生成</summary>

`ai-project-manager` 的专项规则默认源位于：

- `skills/00-01-ai-project-manager/references/rules/*.md`

宿主项目中的专项规则权威目录位于：

- `docs/rules/`

主入口在执行骨架补齐时，应负责创建宿主 `docs/rules/` 目录；当宿主缺少默认专项规则文件时，可调用以下工具脚本批量生成：

```bash
node .agent/project-manager-suite/tools/generate-host-rules.mjs <host-project-root>
```

补充说明：

- 默认策略是“只补缺失文件，不覆盖宿主已有同名规则文件”
- 若需要强制覆盖，可追加 `--force`
- 运行时读取顺序应始终保持“宿主 `docs/rules/` 优先，套件默认规则源兜底”
- 该脚本的参数与行为细节见 `tools/README.md`
- 若你当前就在套件源码仓库中联调，也可直接使用仓库路径：`node project-manager-suite/tools/generate-host-rules.mjs <host-project-root>`

</details>

## 核心运行机制

`ai-project-manager` 是全套件的 **唯一总入口**。它先建立统一上下文，再决定项目进入哪个阶段、由哪个能力承接，以及结果该写回哪里。

为了避免 AI 上下文漂移，项目状态不再依赖临时聊天记忆，而依赖于 **3 类全局文件 + 1 类状态回写能力**：

| 组成 | 作用 |
|------|------|
| 全局规则文件 | 定义项目怎么运行 |
| 项目画像文件 | 记录项目当前是什么 |
| 当前执行计划文件 | 指导现在该做什么 |
| `project-devlog` | 沉淀最近发生了什么变更 |

这组机制可以统一理解为一套 **项目持续记忆底座**：全局规则负责长期约束，项目画像负责项目快照，执行计划负责当前推进目标，`project-devlog` 负责最近状态沉淀。

在这套记忆底座之上，主入口再按阶段判断、最小交付物和人工确认节点进行推进，这部分可以统一理解为 **工程化流程编排**，其价值在于：

- 让 AI 知道当前项目处于哪个阶段
- 让每一轮都有明确的最小交付物
- 让关键节点保留人工确认，避免把未确认内容直接当成权威结论
- 让每轮结果都能回写，成为下一轮输入

默认推进链路为：

```text
项目画像
→（已有代码接入时）project-baseline-auditor 生成画像草稿与关键文件缺口清单
→ 需求清单
→ 业务需求文档
→ page-chief
→ 页面代码 / 页面交付清单
→ 人工确认页面
→ page-explainer 冻结流程与交互语义 / gap 收口
→ prd-chief
→ 术语表 / Schema / API / foundation 交付清单
→ 功能列表 / mainprd / subprd
→ 开发计划
→ 开发执行
→ 测试用例（S5，test-case-chief 调度）
→ 测试执行（S6，test-case-runner）
→ 安全扫描（S7，security-scan）
→ 验收收口（test-and-acceptance：S6 测试报告产出后由用户显式调用承接，不在主入口自动路由内）
```

其中 **S2 页面设计、技术地基与完整版 PRD** 阶段有一条硬约束：

- 先进入 `page-chief`，由其调度 `page-designer` 产出页面代码与页面交付清单
- 用户确认页面方向后，仍留在 `page-chief` 链路内，继续调用 `page-explainer` 冻结流程与交互语义并收口 gap
- 只有页面环节被 `page-chief` 判定 DONE 后，才允许切换到 `prd-chief`
- 进入 `prd-chief` 后，必须先调用 `foundation-builder` 产出术语表 / Schema / API
- 只有在 foundation 完成后，才允许调用 `prd-writer` 反推并沉淀完整 PRD
- 未经页面环节收口或未完成 foundation，不允许把 PRD 当作权威版本继续推进

## 适用场景

`project-manager-suite` 更适合作为以下场景中的开发助手：

- 业务方已经有明确目标，但需求仍然零散，缺少稳定推进机制
- 团队希望把“需求整理 -> 设计 -> PRD -> 开发 -> 测试 -> 验收”串成单一闭环
- 项目需要跨轮协作，不能每次都依赖聊天上下文重新解释一遍
- 希望同时支持开源版能力复用与增强版能力扩展，而不是把关键能力锁死在单一 IDE 或单一项目里

## 能力分工

从 skill 角色来看，当前主链路中的能力可以先分成 3 类：

- **流程调度型**：`ai-project-manager`、`page-chief`、`prd-chief`、`test-case-chief`，负责识别上下文、判断阶段、控制页面环节、PRD 环节与测试用例环节的正式接管顺序
- **阶段交付型**：`project-baseline-auditor`、`brd-writer`、`page-designer`、`page-explainer`、`foundation-builder`、`prd-writer`、`delivery-planner`、`prd-acceptance-reviewer`、`test-case-writer`、`test-case-reviewer`、`test-case-runner`、`security-scan`，负责承接某一阶段或接入旁路的正式交付物
- **专项执行型**：`coding-standards`、`project-devlog`、`project-link-indexer`、`doc-governance`、`test-and-acceptance`，负责研发执行规范、状态回写、文件级索引等专项工作，不承担主流程调度

为了让人一眼看懂调用顺序，每个 skill 目录名带一个「系列-序号」编号前缀（如 `skills/04-03-prd-writer/`），文件管理器和 IDE 里按目录名排序即是调用顺序：

- 主编号代表调用阶段顺序：`00` 为全局型（总入口与全阶段伴随能力，不属于单一阶段），`01`～`09` 按流水线从接入到安全扫描依次推进
- 同一系列的 skill 共享主编号，副编号表示系列内的先后（如 PRD 系列：`04-01` prd-chief 调度 → `04-02` foundation-builder 打地基 → `04-03` prd-writer 写 PRD）
- **编号是给人看的阅读辅助**：skill 的调用名（SKILL.md frontmatter 的 `name:`，如 `prd-writer`）不带编号，AI 按协议自行判断调用先后，与编号无关；文档中提到 skill 时也用不带编号的调用名

| 编号 | 能力 | 主要职责 | 默认介入阶段 |
|------|------|----------|--------------|
| 00-01 | `ai-project-manager` | 识别全局文件、判断阶段、路由能力、回写状态 | 全阶段入口 |
| 00-02 | `project-devlog` | 回写每轮推进状态和日志 | 全阶段伴随 |
| 00-03 | `project-link-indexer` | 编译宿主文件级引用关系图，诊断坏链、缺回链和孤立交付物 | 全阶段伴随 |
| 00-04 | `doc-governance` | 文档治理 advisory（不强制载入流水线） | 按需 |
| 01-01 | `project-baseline-auditor` | 基于已有代码生成或更新项目画像，并输出关键维护文件缺口清单 | S0.5 |
| 02-01 | `brd-writer` | 将业务想法收敛成可评审的业务需求文档 / BRD，并锁定关键决策 | S1 |
| 03-01 | `page-chief` | 观察页面环节文件状态，调度 `page-designer -> page-explainer` 并控制是否回环 | S2 页面环节 |
| 03-02 | `page-designer` | 基于 BRD 产出可交互前端页面（内置设计知识库），管理页面交付清单 | S2 首轮 |
| 03-03 | `page-explainer` | 基于页面代码沉淀流程、交互语义与 gap 文件，并完成页面环节收口 | S2 页面确认后 |
| 04-01 | `prd-chief` | 在页面环节收口后调度 `foundation-builder -> prd-writer`，控制 PRD 环节推进 | S2 PRD 环节 |
| 04-02 | `foundation-builder` | 基于已确认页面反推术语表、Schema、API 和 foundation 交付清单 | S2 页面环节收口后 |
| 04-03 | `prd-writer` | 基于页面与 foundation 产物沉淀 AI 可编码 PRD | S2 foundation 完成后 |
| 05-01 | `delivery-planner` | 把 PRD 拆成开发计划和任务清单 | S3 |
| 06-01 | `coding-standards` | 承接开发执行和规范化实现工作 | S4 / 代码开发伴随 |
| 07-01 | `test-case-chief` | 调度 `prd-acceptance-reviewer -> test-case-writer -> test-case-reviewer`，控制验收 + 测试用例环节推进 | S5 |
| 07-02 | `prd-acceptance-reviewer` | 把 subprd §X.6 验收条目拉齐为独立验收文档 | S5 验收文档 |
| 07-03 | `test-case-writer` | 基于验收文档产出按业务域组织的测试用例 + SQL 数据准备 | S5 测试用例 |
| 07-04 | `test-case-reviewer` | 核查 TC 质量，原地修正或写入待裁定问题清单 | S5 TC 核查 |
| 08-01 | `test-case-runner` | 按测试用例文档执行 API / UI 测试并生成报告 | S6 |
| 08-02 | `test-and-acceptance` | 人工点检准备与验收收口支撑（用户显式调用，不在主入口自动路由内） | S6 测试执行后按需 |
| 09-01 | `security-scan` | 在完工前执行固定安全闸门扫描并给出 PASS/BLOCK/WAIVER 结论 | S7 |

## 套件目录结构

在使用本套件前，了解各层分工有助于排查问题或进行自定义适配：

```text
project-manager-suite/
├── package.json                   # Node 运行入口与测试脚本定义
├── README.md                      # 套件使用指南
├── PIPELINE.md                    # 流水线与产物路径的权威定义
├── hooks/                         # 会话启动时的注入与平台 hook 入口
├── lib/                           # 协议结构化实现与 bootstrap 组装层
│   ├── ai-pm-protocol/            # 字段、阶段、路由、规则同步等协议层结构化配置
│   └── bootstrap/                 # 平台注入与 bootstrap 组装逻辑
├── skills/                            # 实际运行时的能力目录（目录名带 NN-NN 调用顺序前缀，按名排序即调用顺序；skill 调用名不含前缀）
│   ├── 00-01-ai-project-manager/      # [核心] 唯一总入口
│   │   ├── SKILL.md                   # 入口指令
│   │   ├── references/
│   │   │   ├── core/                  # 运行协议、全局文件协议、路由与骨架规则
│   │   │   ├── rules/                 # 前端/后端/数据库/调试等专项规则
│   │   │   └── defaults/              # 默认技术栈与其他默认参数
│   │   └── assets/global-files/       # 全局文件默认骨架（画像、计划等）
│   ├── 00-02-project-devlog/          # 日志与状态回写（全阶段伴随）
│   ├── 00-03-project-link-indexer/    # 文件级引用索引与 LLM wiki 导航（全阶段伴随）
│   ├── 00-04-doc-governance/          # 文档治理 advisory（按需）
│   ├── 01-01-project-baseline-auditor/ # 既有项目画像与关键文件缺口诊断（S0.5）
│   ├── 02-01-brd-writer/              # 业务需求文档 / BRD 收敛（S1）
│   ├── 03-01-page-chief/              # S2 页面环节调度
│   ├── 03-02-page-designer/           # 页面设计（内置设计知识库 + BM25 搜索）
│   ├── 03-03-page-explainer/          # 页面交互语义与 gap 收口
│   ├── 04-01-prd-chief/               # S2 PRD 环节调度
│   ├── 04-02-foundation-builder/      # 术语表 / Schema / API 技术地基设计
│   ├── 04-03-prd-writer/              # 基于页面与 foundation 的 PRD 反推
│   ├── 05-01-delivery-planner/        # 任务拆解与交付规划（S3）
│   ├── 06-01-coding-standards/        # 编码规范与研发执行（S4）
│   ├── 07-01-test-case-chief/         # S5 验收 + 测试用例环节调度
│   ├── 07-02-prd-acceptance-reviewer/ # 验收文档拉齐
│   ├── 07-03-test-case-writer/        # 测试用例编写
│   ├── 07-04-test-case-reviewer/      # 测试用例核查
│   ├── 08-01-test-case-runner/        # 测试用例执行（S6）
│   ├── 08-02-test-and-acceptance/     # 验收收口（S6 后人工，显式调用）
│   └── 09-01-security-scan/           # 完工前固定安全闸门扫描（S7）
├── tests/                         # 工具链与协议对齐测试
└── tools/                         # 宿主初始化、校验、规则同步、日志回写、安装套件等脚本
```

<details>
<summary>各目录的作用与使用场景</summary>

- `README.md`
  - 作用：对外说明套件是什么、怎么安装、怎么接到宿主项目里
  - 什么时候看：第一次接入、需要给别人解释套件结构、想确认标准使用方式时
- `package.json`
  - 作用：定义 Node 侧的最小工程入口，例如测试脚本和模块类型配置
  - 什么时候看：要运行 `npm run test:ai-pm`、补充新的工具脚本命令、调整 Node 模块行为时
- `PIPELINE.md`
  - 作用：定义 S0 → S7 各阶段 skill 的职责、依赖和产物落点，是路径约定的权威来源
  - 什么时候看：要确认某个产物该放哪、上下游怎么衔接、新增 skill 要登记落点时
- `hooks/`
  - 作用：提供平台侧会话启动注入入口，例如 session start hook
  - 什么时候看：要接 Claude/OpenCode/Codex 等平台、排查“为什么启动时自动注入 ai-project-manager”时
- `lib/`
  - 作用：把协议文档中的稳定规则收口成结构化实现，供脚本和平台 bootstrap 复用
  - 什么时候看：要新增字段、调整阶段、修改路由规则、修复 hook/bootstrap 注入逻辑时
- `lib/ai-pm-protocol/`
  - 作用：维护字段合同、阶段定义、路由规则、规则同步策略等协议层结构化配置
  - 什么时候看：你改的是规则本身，而不是某个单一脚本的临时判断时
- `lib/bootstrap/`
  - 作用：负责把 `ai-project-manager` 主入口能力组装成各平台可消费的 bootstrap 内容
  - 什么时候看：要改 session-start 注入内容、平台适配逻辑、统一启动文案时
- `skills/`
  - 作用：存放实际面向项目推进的能力单元，是套件的主体能力层
  - 什么时候看：要新增或修改某个 skill、调整能力边界、扩展某阶段交付流程时
- `skills/00-01-ai-project-manager/`
  - 作用：唯一总入口，负责识别全局文件、最小访谈、阶段判断、路由和回写
  - 什么时候看：任何“项目启动 / 继续推进 / 下一步做什么 / 当前处于哪个阶段”的问题都应先看这里
- `skills/*/references/`
  - 作用：存放该 skill 的协议、规则、模板引用和补充说明
  - 什么时候看：要修改某个 skill 的行为规则，但不一定要改脚本实现时
- `skills/*/assets/`
  - 作用：存放该 skill 会创建或复用的模板、默认文件骨架、静态素材
  - 什么时候看：要调整默认模板内容、生成文件外形或默认骨架时
- `tools/`
  - 作用：提供宿主初始化、校验、阶段判断、规则同步、日志回写、安装套件等脚本化能力
  - 什么时候看：需要一键执行稳定动作，而不是靠主入口纯文本推理时
- `tests/`
  - 作用：验证工具链主路径、协议实现和对齐关系是否被改坏
  - 什么时候看：改了协议、脚本、bootstrap、路由逻辑后，准备收口或怀疑回归时
- `.codex/`、`.opencode/`
  - 作用：存放不同运行平台的安装说明或插件接入文件
  - 什么时候看：你要把套件接进对应平台，或排查平台侧为什么没有正确识别套件时

其中 `skills/00-01-ai-project-manager/references/` 建议按以下三层组织：

- `core/`：主入口运行所依赖的核心协议层，存放运行流程、全局文件协议、路由与骨架规则等上位约束
- `rules/`：面向具体任务类型的专项执行规则，存放前端、后端、数据库、文档、调试、日志等下位规则包
- `defaults/`：默认参数与默认约定，存放默认技术栈、默认实现偏好、默认环境口径等可被引用和覆盖的参考输入

当前 `ai-project-manager` 中，这三层的典型职责分别是：

- `references/core/runtime.md`：定义主入口运行流程与访谈协议
- `references/core/global-files-protocol.md`：定义全局文件字段合同与读写职责
- `references/core/routing.md`：定义阶段路由与项目骨架补齐规则
- `references/rules/*.md`：定义前端、后端、数据库、调试、文档等专项规则
- `references/defaults/tech-stack.md`：定义默认技术栈参数，供主入口和子能力在未有宿主项目明确技术栈时按需引用

</details>

## 使用提醒

- `project-manager-suite` 应作为完整目录整体复制使用，不建议拆散单个 skill
- 主入口行为以 `skills/00-01-ai-project-manager/references/core/runtime.md` 为准
- 路由映射和骨架补齐规则以 `skills/00-01-ai-project-manager/references/core/routing.md` 为准
- 若修改了阶段流转、技能职责或默认交付链路，应该同步更新本 README，避免使用者读到过期说明
- 本套件默认**单项目宿主**假设：一个宿主项目只维护一套 slug 文件族（一份 BRD、一套页面台账、一套 PRD 等，slug 由 brd-writer 在 Phase A 固化）。若同一目录下出现多套 slug 产物，各 skill 的"按文件名找上游"逻辑会产生歧义；要并行推进多个项目，请为每个项目单独建目录、各自挂载套件走完整流水线
- 版本控制建议（宿主项目侧）：
  - `.agent/project-manager-suite/`（套件拷贝）建议提交进宿主仓库，团队成员拉取即得同版本套件；若选择不提交，则每位成员需自行安装同版本套件，并在 `.gitignore` 中忽略该目录
  - `.agent/project-manager-suite.lock.json` 应与套件拷贝一起提交；它记录 package 版本、相对安装路径和 SHA-256 内容哈希，不包含本机绝对路径
  - 安装或升级后运行 `node .agent/project-manager-suite/tools/verify-suite-lock.mjs .`，内容漂移时不得继续普通项目任务
  - `docs/`（BRD / PRD / 计划 / 测试用例 / 测试报告 / 安全报告）和 `logs/`（开发日志）下的流水线产物是项目资产，建议提交
  - `.gitignore` 参考片段（按团队选择保留或删除注释行）：

    ```gitignore
    # 若选择不提交套件拷贝，取消下一行注释
    # .agent/project-manager-suite/
    ```

## 版本历史

| 版本 | 日期 | 变更摘要 |
|------|------|---------|
| **2.0** | 2026-07-10 | 全套件审计修复版。基于 51 项经真实执行核实的审计发现做系统性修复：模板与校验器对齐（S4 一致性门禁、prd-check 拆分模式、feature-list 编号）、脚本命令统一 `<suite-path>` 路径约定、foundation 目录契约统一为 `docs/prd/foundation/`、brd-writer 生命周期护栏（init 重入保护、栈式回滚、DONE 态保护）、baseline 按行合并保留用户确认字段、PIPELINE 补齐 S6/S7 契约、hooks 注入链路修通、清理历史项目泄漏词。测试 112/112 通过，6 个沙箱场景真实复现验证全部通过。 |
| 1.x | 2026-04 ～ 2026-07 | 初始版本：S0–S5 主流水线、调度层（page-chief / prd-chief / test-case-chief）、协议脚本化（route-check / bootstrap / ledger 工具链）、既有项目接入旁路（S0.5 baseline）逐步成形。 |

## 延伸阅读

- 流水线各阶段职责、依赖与产物落点的权威定义，参阅 `PIPELINE.md`
- 协议层结构化实现（字段合同、阶段定义、路由规则）的维护说明，参阅 `lib/ai-pm-protocol/README.md`
- 工具脚本的使用与维护说明，参阅 `tools/README.md`
- 测试链路的覆盖范围与运行方式，参阅 `tests/README.md`

## 后续产品升级路径

`project-manager-suite` 后续还将补齐一项 **项目评测能力**，用于对项目说明、需求文档、PRD、页面原型、核心代码、测试与验收材料进行结构化评估，判断当前成果是否达到下一步推进标准，并输出缺口分析与整改建议。
