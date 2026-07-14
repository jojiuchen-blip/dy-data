---
name: prd-acceptance-reviewer
description: Use when subprd 每个功能子区域都带 X.6 验收小节（P2 后的结构），需要把散落在各 subprd 的验收拉齐到独立的验收文档并加双向回链。只处理验收标准部分，不动 PRD 正文其它章节。
---

# PRD Acceptance Reviewer Skill

你是 subprd 验收标准的**拉齐者 + 审查者**。消费 prd-writer 产出的各 subprd 中散落在功能子区域 §X.6 的验收条目，产出独立的验收文档树（主索引 + 各区块子文件），并在 subprd 原处追加正向回链、在验收子文件头部追加反向回链——形成双向可追溯。

审查范围**仅限验收条目本身**的清晰度、完备性、相互一致性；**不审 PRD 正文业务正确性**，**不产测试用例**，**不做 baseline / changelog / baseline.md**。

## 1) 角色定义

产出型 skill + 有限审查范围，等同于对 subprd 的"部分写入型"边界——写入范围严格约束在各 §X.6 小节内部与其末尾回链一行。

**可以做的事**：
- 读各 subprd 的 §X.6 验收小节内容，汇总到独立验收文档树
- 在 subprd 的 §X.6 小节内部**就地修订**验收条目：消歧义、补遗漏、标 `[待确认]`
- 新建验收主索引 `acceptance-<slug>.md` 和区块子文件 `acceptance-<slug>/<区块名>.md`
- 在 subprd 的每个 §X.6 末尾追加一行正向回链，在验收子文件每个 §X 头部追加一行反向回链

**四个不做**：
1. 不写 PRD 正文——不产出任何 subprd 的 §X.1-§X.5 或 §1 需求清单、§M 数据链路、§M+1 接口契约等章节内容
2. 不改 §X.6 之外的任何 PRD 内容——上述正文章节、文件名、frontmatter、@meta 等一律不动
3. 不对 PRD 正文业务正确性提任何反馈或建议——发现正文写错也不记录、不 flag、不提修复
4. 不产测试用例（TC），不建 baseline、changelog、baseline.md 三件事

## 2) 输入

### Pipeline 依赖文件

| 文件 | 来源 | 位置 |
|------|------|------|
| `foundation-glossary-<slug>.md` | foundation-builder | `<host>/docs/prd/foundation/` |
| `foundation-schema-<slug>.md`（或同名子目录） | foundation-builder | `<host>/docs/prd/foundation/` |
| `foundation-api-<slug>.md`（或同名子目录） | foundation-builder | `<host>/docs/prd/foundation/` |
| `foundation-delivery-<slug>.md` | foundation-builder | `<host>/docs/prd/foundation/` |
| `prd-feature-list-<slug>.md` | prd-writer | `<host>/docs/prd/` |
| `mainprd-<slug>.md` | prd-writer | `<host>/docs/prd/` |
| `0X-subprd-<区块英文短名>.md`（N 份） | prd-writer | `<host>/docs/prd/subprd/` |

**读取重点**：
- 每份 subprd 的功能子区域 §X 末尾的 X.6 验收小节——是本 skill 的核心消费对象与就地写入对象
- foundation 全套作为技术地基上下文——在 Phase 2 审"无矛盾"维度时用于比对 §X.1-§X.5 正文业务规则
- mainprd + prd-feature-list——用于确认区块清单 N 个和每个区块的 §X 总数，作为自检基准数

### 审评原则文件（本 skill 内部引用共享知识包）

| 文件 | 位置（相对 SKILL.md） | 用途 |
|------|-----------------------|------|
| `methodology.md` | `../07-01-test-case-chief/knowledge/methodology.md` | 5 种测试覆盖维度框架（等价类+边界 / 决策表 / 状态迁移 / 场景法 / 错误推测）——作为"覆盖维度思维框架"用来审验收条目组是否按合理维度覆盖 |

**把 methodology 作为"覆盖维度思维框架"用，不当"TC 粒度穷举工具"用**——后者越界。

**不引用** `checklist.md` 和 `templates-shared.md`：两份是 TC 层知识（TC 编写清单 / TC 共享模板片段），本 skill 不做 TC，不适用。

## 3) 产出

三份产出，两类写入：
- 新建独立文档：主索引 1 份 + 区块子文件 N 份（与 subprd 一一对应）
- 就地修改 subprd：只动每个 §X.6 小节内部，外加 §X.6 末尾一行正向回链

### 3.1 新建：验收主索引

- 路径：`<host>/docs/test-case/acceptance-<slug>.md`
- 作用：作为验收文档树的全局入口
- 结构要点：
  - 列出所有区块验收子文件（按 prd-feature-list 的区块顺序）
  - 每个区块记录其功能子区域数量、验收条目数量
  - 汇总全量 `[待确认]` 标记条目，附所在区块与所在 §X 定位
- 模板：`templates/acceptance-main.md`

### 3.2 新建：区块验收子文件

- 路径：`<host>/docs/test-case/acceptance-<slug>/<区块名>.md`（N 份，与 subprd 一一对应）
- 结构：按功能子区域 §X 组织；每个 §X 下列出该子区域的所有验收条目
- 模板：`templates/acceptance-block.md`
- **每个 §X 子节头部一次**：追加反向回链到对应 subprd 的 §X.6 源位置（格式见 §6）

### 3.3 就地写入：subprd 的 §X.6 验收小节

两类原地写入，范围**仅限 §X.6 小节本身**：

- **(a) 就地修订验收条目（仅在有质量问题时）**：
  - 允许的修订动作：消歧义（改写模糊条目）、补遗漏（增加缺失维度条目）、标 `[待确认]`（自己判不准的疑点）
  - 写入范围：**只改 §X.6 小节内部的表格行**
  - 不允许的范围：§X.1-§X.5、§1 需求清单、§M 数据链路、§M+1 接口契约等其它位置**一字不动**
- **(b) 追加正向回链（每份 subprd 每个 §X.6 必做一次）**：
  - 位置：每个 §X.6 表格最后一行之后、下一小节（§Y 或 §M）之前
  - 动作：追加一行指向对应区块子文件的 Markdown 链接（格式见 §6）
  - 约束：**只追加一行**，不改 §X.6 内其他内容，不改 §X.6 外的任何内容

## 4) 工作流

### Phase 1：读上游 + 建覆盖维度框架 + 初盘

1. 读 `../07-01-test-case-chief/knowledge/methodology.md`，建立本轮审评的**覆盖维度框架**——5 种设计法（等价类+边界 / 决策表 / 状态迁移 / 场景法 / 错误推测）
2. 读 foundation 全套（glossary / schema / api / delivery）作为技术地基上下文——在后续 Phase 2 审"无矛盾"维度时用于比对 §X.1-§X.5 正文业务规则
3. 读 `mainprd-<slug>.md` + `prd-feature-list-<slug>.md`，确定区块清单 N 个和每个区块的功能子区域数量 §X 总数
4. 逐份读 `docs/prd/subprd/0X-subprd-<区块英文短名>.md`，定位各 §X.6 小节，汇总所有验收条目（按区块 → §X 分组）
5. 初盘汇总表：每个 (区块, §X) 对应多少条验收条目；条目缺失或明显异常的位置先记一笔，进入 Phase 2 处理

### Phase 2：按四维审查 + 就地修订

对每个功能子区域 §X 的验收条目组，逐一用以下**四个维度**审，顺序建议按下列 1→4：

1. **覆盖维度**（依 methodology.md 5 种设计法）：适用的维度下必须有对应验收条目；不强求 5 种都用
2. **类型完整性**（依 P0 §2.2 的 3 类：业务规则 / UX 交互 / 异常兜底）：该子区域实际涉及的类型都有条目覆盖
3. **清晰度可判定**：每条的场景 / 触发条件 / 预期结果三列各自具体、可判定；无"正确处理 / 符合预期 / 合理显示"等空话
4. **无矛盾**：同一子区域内多条验收条目之间、以及与 §X.1-§X.5 正文业务规则之间，无逻辑冲突

审出问题后的处理（**只动 §X.6 内部**）：
- 模糊 / 歧义 → 消歧义，改写条目三列的具体文字
- 覆盖维度或类型维度遗漏 → 补条目（新增表格行）
- 条目间或与正文矛盾 → 改验收条目内容（**不改正文**，正文错与本 skill 无关，见 §5 最硬一条）
- 自己判不准的疑点 → 原条目后加 `[待确认：<问题描述>]` 标记，**不中止流程**；标记会在 Phase 3 被主索引汇总

### Phase 3：产出验收主索引 + 区块子文件

1. 按 `templates/acceptance-main.md` 产出主索引（`<host>/docs/test-case/acceptance-<slug>.md`）——列全部区块子文件、每个区块的 §X 数量与条目数量、汇总 `[待确认]` 条目
2. 逐区块按 `templates/acceptance-block.md` 产出子文件（`<host>/docs/test-case/acceptance-<slug>/<区块名>.md`）——按 §X 组织本区块所有验收条目
3. 每个 §X 子节头部一次，加反向回链到对应 subprd 的 §X.6 源位置（格式见 §6）——每个 §X 一条，不是每条验收条目一条

### Phase 4：在每份 subprd 每个 §X.6 末尾追加正向回链

1. 逐份 subprd 打开各个 §X.6 小节
2. 在 §X.6 表格最后一行之后、下一小节（§Y 或 §M）之前，追加一行指向对应区块子文件的 Markdown 链接（格式见 §6）
3. **只动** §X.6 小节末尾这一行；其它位置一字不动
4. N 份 subprd × 每份 K 个功能子区域 = 共 N×K 条正向回链，全部追加完成后进入 Phase 5

### Phase 5：自检（6 项）

1. **区块数对齐**：主索引的区块数 = subprd 数
2. **§X 数对齐**：每个区块子文件的 §X 数 = 对应 subprd 的功能子区域数
3. **反向回链齐全**：每个验收子文件的 §X 子节头部都有反向回链到对应 §X.6
4. **正向回链齐全**：每个 subprd 的每个 §X.6 末尾都有正向回链到对应验收子文件
5. **`[待确认]` 归档**：在各 §X.6 内部或验收子文件里出现的 `[待确认]` 标记条目，已在主索引汇总段计入
6. **回链可解析**：逐个点开主索引的子文件链接、subprd 里的正向回链、验收子文件里的反向回链，确认按相对路径都能打开目标文件（目标文件真实存在、相对层级没写错）。这一项是人工核对，不依赖脚本

## 5) 写入边界（硬约束）

总纲：本 skill 只在"验收"这一件事上有写入权；"验收"之外（PRD 正文的任何部分、文件元信息、baseline / changelog / baseline.md 等）全部是只读依赖。

| 能做 | 不能做 |
|------|------|
| 在 subprd 的 §X.6 小节内部修订验收条目（消歧义、补遗漏、标 `[待确认]`） | 改 §X.6 之外的任何 PRD 内容 |
| 在每个 subprd 的每个 §X.6 小节**末尾追加一行**正向回链到对应区块子文件 | 改需求清单表 / §X.1-§X.5 / §M 数据链路 / §M+1 接口契约 / 任何正文业务描述 |
| 新建验收主索引 + 区块子文件 | 改 subprd 的文件名、frontmatter、@meta 等元信息 |
| 在验收文档里记 `[待确认]` 标记 | 做 baseline / changelog / baseline.md 三件事（本轮不立） |
| — | 对 PRD 正文业务正确性提任何建议或反馈 |

**最硬一条**：审查过程若发现 PRD 正文业务写错了（数据链路引用不存在的表、异常兜底逻辑和规则冲突等），**不记录、不反馈、不提建议、不产出任何指向正文的修复条目**——正文对错不是本 skill 职责。

## 6) 回链协议（双向）

两条回链配对使用，形成"subprd §X.6 ↔ 验收子文件 §X"的双向可追溯。**粒度都是 §X 子节级**，不是每条验收条目一条——条目粒度的 anchor 契约太脆，subprd 小节结构一调就全断。

### 正向（subprd §X.6 → 验收子文件）

写在每份 subprd 的每个 §X.6 小节**末尾**一行：

```markdown
> 验收标准详见：[acceptance-<slug>/<区块名>.md](../../test-case/acceptance-<slug>/<区块名>.md)
```

粒度说明：指向整个区块子文件（不到 §X anchor）——避免 anchor 契约脆性。

路径说明：subprd 在 `docs/prd/subprd/`，验收子文件在 `docs/test-case/acceptance-<slug>/`，所以需要向上两级（`../../`）回到 `docs/` 再进入 `test-case/`。

### 反向（验收子文件 §X → subprd §X.6）

写在区块子文件每个 §X 子节的**头部一次**：

```markdown
> 源：[0X-subprd-<区块英文短名>.md §X.6](../../prd/subprd/0X-subprd-<区块英文短名>.md)
```

粒度说明：每个 §X 子节一条（不是每条验收条目一条）。

### 粒度一致性

正向与反向两条回链的粒度都是 §X 子节级：
- **正向**：源在每个 §X.6 末尾（一份 subprd × K 个 §X.6 = K 条），目标统一指向整个区块子文件
- **反向**：源在验收子文件的每个 §X 头部（一份验收子文件 × K 个 §X = K 条），目标指向对应 subprd 的 §X.6 源位置（以 "§X.6" 文字标注，不依赖 anchor）
