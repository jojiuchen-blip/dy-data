# delivery-planner / source-loading-order

这份文档定义执行计划写作时应该优先读取哪些真实资料，以及每类资料的用途。

> **v1.1 变更说明**：Step 0.5 脚本（`collect-upstream-context.mjs`）会程序化输出一份「路径清单 JSON」，本文档的第四节〜第五节（PRD 导航源、任务相关 PRD 源）现在由脚本清单驱动，不再需要 AI 自行 glob 搜索。

## 一、总顺序

按以下顺序读取，不要颠倒：

0. **仓库角色判断**（先确认当前是宿主项目，还是套件 / 框架 / skill 源码仓库）
0.5. **脚本化上游产物发现**（Step 0.5 强制前置，见 SKILL.md）
1. 仓库规则源
2. 当前正式计划文件组
3. PRD 导航源（来自脚本输出 `mainprd`）
4. 任务相关 PRD（来自脚本输出 `subprd`，按任务选读）
5. 真实代码与 SQL
6. 测试与验证资产

核心原则：**先判断仓库角色，后脚本发现，后规则；先目标态，后现状；先 mainprd，后局部细节。**

## 二、仓库规则源

| 资料类型 | 用途 | 示例 |
|---|---|---|
| 仓库入口规则 | 确认任务入口、协作边界、项目约束 | `<仓库入口规则文件>` |
| AI 规则总入口 | 确认 PRD 加载、验证门禁、术语边界 | `<AI 规则总入口>` |
| 计划 / 文档专项规则 | 确认计划回写、交叉引用、验收口径升级规则 | `<计划 / 文档专项规则目录>` |

没有读完这些规则前，不要开始写正式计划。

## 三、当前计划文件组

| 资料类型 | 用途 | 读取方式 |
|---|---|---|
| 主开发计划 | 当前骨架、阶段索引、发布闸门、风险与反向索引 | 默认优先 |
| 任务看板 | 当前 Task 状态、依赖和子开发计划入口 | 按当前任务定位 |
| 子开发计划 | 当前 Task 的 PRD、核心逻辑、核心文件和验证方法 | 按 Task 读取 |
| 用户点名的计划文件 | 当前任务的直接依据 | 必读 |

如果是"更新计划"，必须读正式计划文件组，而不是只看聊天摘要。

## 四、PRD 导航源（由脚本清单驱动）

Step 0.5 脚本输出的 `mainprd` 字段即为 mainprd 的绝对路径。

| 资料类型 | 用途 | 来源 |
|---|---|---|
| mainprd (`mainprd-<slug>.md`) | 建立全局地图，确定功能边界和章节入口 | 脚本 `mainprd.path` |
| PRD 功能列表 (`prd-feature-list-<slug>.md`) | 页面全景 + 区块业务逻辑总览 | 脚本 `prdFeatureList.path` |

PRD 导航文档是第一层入口。先建立地图，再按任务进入 subprd。

> 如果 `mainprd` 为 `null`，进入失败分支，不要继续读取其他资料。

## 五、任务相关 PRD 源（由脚本清单驱动）

脚本输出的 `subprd` 数组列举了所有 subprd 路径。按任务类型补读相关块，不整包读取。

| 任务类型 | 优先补读 |
|---|---|
| 接口 / 聚合服务 / DTO 契约 | API 总览 + 对应业务区块 PRD |
| 数据库 / 配置表 / 枚举口径 | 数据库结构文档 + 对应业务区块 PRD |
| 菜单 / 路由 / 页面配置 | 菜单或路由总览 + 对应配置 PRD |
| 术语统一 / 文案口径 | 术语表 |
| 某业务域的完整任务拆解 | 对应业务域 PRD |

读取原则：
- 只读与当前任务有关的章节
- 大文件（脚本输出 `isLarge: true`）按章节号定位
- 章节信息最终要回写到 Task 的 `PRD 双链·读`

## 六、Foundation 文档源（由脚本清单驱动）

脚本输出的 `foundations` 数组按 type 分类（glossary / schema / api / delivery），是确定完成标准的核心依据。

| 类型 | 用途 | 脚本 type 值 |
|---|---|---|
| 术语表 | 确认统一命名口径 | `glossary` |
| 数据库 Schema | 确认字段、表名、枚举值 | `schema` |
| API 接口设计 | 确认接口路径、请求/响应结构 | `api` |
| 交付清单 | 产物索引 + 一致性自查结果 | `delivery` |

如果 schema / api 均缺失，则代码类任务的 `核心文件` 和 `完成标准` 无法写实，须进入失败分支。

## 七、真实代码与 SQL 源

计划不能停留在 PRD 层，必须读真实落点。

| 来源 | 用途 |
|---|---|
| Controller / Service / Mapper / DTO | 确认服务端现状、接口结构、数据口径 |
| 页面 / 组件 / store / composables / api | 确认前端现状与页面落点 |
| schema / migration / seed SQL | 确认数据库现状、关键表、关键种子 |
| 路由 / 菜单 / 配置 API 封装 | 确认配置面入口与能力 |

如果没有读到这些真实文件，就不能把 `核心文件` 和 `完成标准` 写实。

## 八、测试与验证资产

| 来源 | 用途 |
|---|---|
| 测试用例与报告 | 补齐完成标准与回归路径 |
| 计划 / handoff / smoke / integration 文档 | 补齐联调口径、发布闸门、已知风险 |
| 真实接口样例、查询脚本、联调命令 | 写入验证门禁或任务完成标准 |

如果任务需要"完成前验证"，但没有读任何验证资产，计划大概率会空泛。

## 九、三种常见场景的最小读取集

### 场景 A：新建一份完整计划

必须先运行 Step 0.5 脚本，再至少读取：
- **`<suite-path>/skills/00-01-ai-project-manager/references/defaults/tech-stack.md`（套包内置技术栈参考，必读）**
- 脚本清单：`mainprd` + `foundations` 全部 + `prdFeatureList`
- 仓库规则源
- 当前正式计划或成熟样本计划
- `subprd` 中与任务相关的条目（非全部）
- 至少一组真实代码 / SQL / 验证资产

前置条件：
- 当前仓库已经确认为**宿主项目**
- 本次产物确实要作为后续开发执行的正式计划文件组，而不是套件内部维护文档

### 场景 B：更新已有计划

必须先运行 Step 0.5 脚本（确认上游文档无重大变更），再至少读取：
- 仓库规则源
- 主开发计划、任务看板和本次涉及的子开发计划
- 原计划中涉及的 PRD 双链条目
- 本次变更涉及的真实文件或验证资产

### 场景 C：只补一个 Phase

Step 0.5 脚本可以跳过整包读取，但至少读取：
- 仓库规则源
- 主开发计划中该 Phase 前后的上下文
- 该 Phase 关联的 PRD 章节（从脚本输出路径定位，不整包读）
- 受影响的任务看板、子开发计划、风险、闸门、索引章节

## 十、文件命名约定与自动发现

以下命名约定来自 `PIPELINE.md`，`collect-upstream-context.mjs` 脚本基于这些 glob 模式进行自动匹配。

| 文件类型 | 命名模式 | 优先级 | 脚本字段 |
|---------|----------|--------|---------|
| mainprd | `docs/prd/mainprd-<slug>.md` | 最高，必读 | `mainprd` |
| PRD 功能列表 | `docs/prd/prd-feature-list-<slug>.md` | 高 | `prdFeatureList` |
| subprd | `docs/prd/subprd/0X-subprd-<区块英文短名>.md` | 按任务需要 | `subprd[]` |
| Schema | `docs/prd/foundation/foundation-schema-<slug>.md`（或 `-part<N>.md`）| 高，必需 | `foundations[type=schema]` |
| API | `docs/prd/foundation/foundation-api-<slug>.md`（或 `-part<N>.md`） | 高，必需 | `foundations[type=api]` |
| 术语表 | `docs/prd/foundation/foundation-glossary-<slug>.md` | 中 | `foundations[type=glossary]` |
| 交付清单 | `docs/prd/foundation/foundation-delivery-<slug>.md` | 中 | `foundations[type=delivery]` |
| 用户流程 | `src/frontend/page-preview/explainer-flow-<slug>.md` | 中 | `explainers[type=flow]` |
| 交互描述 | `src/frontend/page-preview/explainer-b-interaction-<slug>.md` | 中 | `explainers[type=b-interaction]` |
| 交互差异 | `src/frontend/page-preview/explainer-b-gap-<slug>.md` | 低 | `explainers[type=b-gap]` |
| 页面解释交付清单 | `src/frontend/page-preview/explainer-delivery-<slug>.md` | 中 | `explainers[type=delivery]` |

> **slug** 由 `brd-writer` 在 Phase A 确定（英文短语、全小写、连字符分隔），流水线中所有下游 skill 的产物文件必须使用同一个 slug。

## 十一、禁止行为

- 禁止把套件 / 框架 / skill 源码仓库误当成 `<host>` 生成正式开发计划文件组
- 禁止在 Step 0.5 脚本运行完成前开始任何读取步骤
- 禁止一次性读取整个 PRD 目录
- 禁止只靠聊天摘要写任务
- 禁止只读 PRD 不读代码就写 `核心文件`
- 禁止只读代码不回到 PRD 就写 `完成标准`
- 禁止补计划状态时只改一处，不同步回写任务看板、子开发计划和关联章节
- 禁止对 `isLarge: true` 的文件整包拉入上下文
