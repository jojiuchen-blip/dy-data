# AI Development Assistant Tools

本目录存放开发助手主入口 `ai-project-manager` 第一阶段脚本化改造的工具脚本。

当前目标不是替代主入口，而是把已经稳定、可判定、可重复执行的部分收敛成工具层能力。

---

## 当前工具一览

| 工具 | 作用 | 当前状态 |
|------|------|----------|
| `generate-host-rules.mjs` | 同步宿主 `docs/rules/` 默认规则文件 | 已有能力，复用中 |
| `validate-global-files.mjs` | 校验全局文件入口、结构和规则目录状态 | V1 可用 |
| `route-check.mjs` | 判断当前阶段、推荐阶段、阶段门禁和阻断原因 | V1 可用 |
| `bootstrap-host.mjs` | 安全补齐宿主骨架并复用规则同步 | V1 可用 |
| `install-suite-into-host.mjs` | 将完整套件安装或同步到宿主 `.agent/project-manager-suite/` | V1 可用 |
| `verify-suite-lock.mjs` | 校验宿主安装态版本锁和套件内容哈希 | V1 可用 |
| `devlog-sync.mjs` | 每日日志新建/追加与规则候选池联动 | V1 可用 |
| `check-protocol-alignment.mjs` | 检查协议文档与结构化实现的双向追踪是否一致 | V1 可用 |

---

## 推荐使用顺序

建议按以下顺序使用：

1. `validate-global-files.mjs`
2. `route-check.mjs`
3. `bootstrap-host.mjs`
4. `install-suite-into-host.mjs`
5. `verify-suite-lock.mjs`
6. `devlog-sync.mjs`

原因：

- 先确认宿主当前是否健康
- 再判断当前应该进入哪个阶段
- 再补骨架和规则目录
- 再把完整套件安装或同步到宿主内路径，固定后续执行入口
- 最后做日志沉淀与规则候选联动

---

## 工具说明

## `generate-host-rules.mjs`

作用：

- 将套件默认规则源 `skills/00-01-ai-project-manager/references/rules/*.md` 同步到宿主 `docs/rules/`

特点：

- 默认只补缺失，不覆盖已有文件
- 支持 `--force`
- 支持 `--dry-run`

适用场景：

- 宿主项目首次初始化 `docs/rules/`
- 宿主缺少默认规则文件

---

## `validate-global-files.mjs`

作用：

- 识别规则、画像、计划、最近日志入口
- 校验结构性必备标记
- 检查多权威候选和规则目录缺口

适用场景：

- 每次启动后先做健康检查
- 在进入后续自动化动作前做只读校验

当前边界：

- V1 重点是结构性校验
- 还没有做更细粒度的字段逐项解析和自动修复

---

## `route-check.mjs`

作用：

- 基于画像、计划、日志判断当前阶段和推荐阶段
- 判断是否允许进入目标阶段
- 输出门禁检查、阻断原因和下一步动作

当前重点门禁：

- 启动最小必需字段包
- 页面任务必补字段包
- 阶段切换日志回写前置条件
- S3 / S4 的基础进入条件

当前边界：

- V1 主要依赖宿主 Markdown 结构和关键字段
- 暂未覆盖所有复杂场景和更深层语义判断

---

## `bootstrap-host.mjs`

作用：

- 安全补齐宿主基础目录骨架
- 复用 `generate-host-rules` 补齐 `docs/rules/`
- 在显式前置条件满足时创建模板文件

当前策略：

- 默认优先创建目录和规则目录
- 若当前目录是容器目录，新宿主物理目录名必须来自 `--interview-json` 中的 `project_name`
- 不默认静默创建 `project-profile.md`
- 创建 `project-profile.md` 时，必须同时提供 `--interview-complete` 与 `--interview-json`，且会把访谈字段真实回写到画像模板
- 默认创建 `execution-plan.md`，因为它属于启动骨架和 AI 持续记忆系统关键文件
- 不覆盖已有权威文件

适用场景：

- 新项目初始化
- 宿主项目缺少骨架目录
- 宿主缺少规则目录或默认规则文件

当前边界：

- V1 不负责自动迁移整个套件到宿主 `.agent/`
- V1 不负责自动删除旧套件目录
- V1 不替代主入口完成访谈；调用方必须先完成访谈并提交结构化结果

### 最小可用示例（从零到骨架）

`--interview-json` 指向的访谈结果文件必须包含以下四个键，值都是非空字符串；也可以把这四个键包在顶层 `startupMinimum` 对象里，两种结构脚本都接受：

| 键名 | 中文含义 |
|------|----------|
| `project_name` | 项目名称（在容器目录下初始化时，新宿主目录名取自它） |
| `project_one_liner` | 项目一句话目标 |
| `target_users` | 目标使用者 |
| `main_problem` | 主要问题（这个项目要解决什么） |

最小 `interview.json` 完整示例：

```json
{
  "project_name": "demo-mall",
  "project_one_liner": "给个体小商家的一站式在线开店工具",
  "target_users": "个体小商家",
  "main_problem": "现有开店方案成本高、上手慢"
}
```

从零到宿主骨架的完整命令序列。`<suite-path>` 指套件根目录：源码仓库联调时为 `project-manager-suite/`，安装到宿主后为 `.agent/project-manager-suite/`；命令默认在宿主项目根目录执行。

1. 主入口完成启动访谈后，把访谈结果按上面的示例保存为 `interview.json`。
2. 补齐骨架。在空目录（容器目录）下执行时，会按 `project_name` 新建宿主目录并在其中建骨架；输出中的 `Effective root` 就是宿主根目录：

   ```bash
   node <suite-path>/tools/bootstrap-host.mjs . --interview-complete --interview-json interview.json --create-profile-file --create-rules-file
   ```

3. 校验骨架是否健康。查的是规则 / 画像 / 计划 / 日志四类全局文件入口与结构标记；输出的 `Errors: 0` 且 Issues 里没有 `[error]` 条目即通过：

   ```bash
   node <suite-path>/tools/validate-global-files.mjs <宿主根目录>
   ```

4. 查看当前阶段与下一步动作。输出 `Can enter: yes` 表示允许进入目标阶段，`Next action` 会给出下一步建议：

   ```bash
   node <suite-path>/tools/route-check.mjs <宿主根目录>
   ```

---

## `install-suite-into-host.mjs`

作用：

- 将完整 `project-manager-suite` 安装或同步到宿主 `.agent/project-manager-suite/`
- 复用宿主已有 `.agent/` 目录；若宿主尚未创建 `.agent/`，脚本会自动创建
- 固定后续工具命令的宿主内执行路径

当前策略：

- 默认安装目标固定为宿主 `.agent/project-manager-suite/`
- 若宿主 `.agent/` 已存在，复用该目录，不覆盖其他宿主资产
- 默认支持对已安装套件执行“同步/升级”写入，不要求宿主是空目录
- 若目标路径被未知目录占用，必须显式传 `--force` 才允许替换
- 默认不删除源套件目录；仅在显式传 `--move` 时，安装成功后才删除源目录

适用场景：

- 新项目骨架已经建立，需要把完整套件装入宿主
- 宿主已存在 `.agent/`，希望一键安装或升级 `project-manager-suite`
- 联调完成后，希望把当前套件同步到宿主内固定路径

### 升级语义与残留清理

- 默认的“同步/升级”（目标已是已安装套件时自动进入 `upgrade` 模式）是**增量复制**：源里有的文件会被新建或覆盖，宿主里多出来的文件不会被自动删除。
- 因此套件迭代中被删除或改名的文件，升级后会残留在宿主 `.agent/project-manager-suite/` 里。脚本会把这类文件列成 `Stale files` 清单打印出来（`--json` 模式在 `files.stale` 字段），只提示、不代删，由使用者确认后手动清理。
- 需要完全干净的安装时，显式传 `--force`：先整体删除目标目录再全新复制，不会有残留。这是破坏性操作，执行前确认目标目录下没有需要保留的手工改动。
- 每次安装/升级都会在目标目录写入脱敏的 `.install-manifest.json`，并在宿主 `.agent/project-manager-suite.lock.json` 写入可提交的版本锁。
- 两份文件只记录明确的 package 版本、相对目标路径、跨平台稳定的 SHA-256 内容哈希和生成工具，不记录源目录、宿主目录或本机绝对路径。
- 内容哈希会先把 UTF-8 文本的 CRLF 规范化为 LF，二进制文件保持原始字节，因此 Windows 与 Linux 的 clean checkout 可复算同一结果。
- 后续命令应先运行 `node .agent/project-manager-suite/tools/verify-suite-lock.mjs .`；版本、内容、manifest 元数据或安装文件清单漂移时返回非零退出码。

当前边界：

- V1 不负责判断项目阶段
- V1 不替代 `bootstrap-host.mjs` 补齐宿主业务骨架
- V1 默认只管理 `.agent/project-manager-suite/`，不接管宿主 `.agent/` 其他内容

---

## `verify-suite-lock.mjs`

作用：

- 读取宿主 `.agent/project-manager-suite.lock.json`
- 校验安装目录、package 版本和跨平台稳定的 SHA-256 内容哈希
- 校验 `.install-manifest.json` 与 lock 的元数据一致，并核对 `installed_files` 与实际套件文件集合
- 检测套件文件被手工修改、漏同步、manifest 漂移或锁文件失配

使用：

```bash
node .agent/project-manager-suite/tools/verify-suite-lock.mjs <host-project-root> [--json]
```

校验通过时退出码为 0；锁缺失、套件缺失、版本不匹配或内容漂移时退出码为 1。

---

## `devlog-sync.mjs`

作用：

- 新建每日日志
- 追加同日日志补充更新
- 命中规则升级信号时同步更新规则候选池

适用场景：

- 一轮有效推进结束后
- 用户要求“写日志 / 总结今天 / 补今日日志”时

当前边界：

- V1 重点是结构化写入
- 暂未接入 git 提交记录聚合
- 不自动回写执行计划状态
- 日志文件负责当天工作的总结沉淀，计划文件仍是 AI 执行判断依据
- 规则候选池目前是“追加记录”能力，不做复杂去重合并

---

## `check-protocol-alignment.mjs`

作用：

- 检查协议文档中的“结构化实现”映射是否完整
- 检查结构化实现文件的 Traceability 头是否反向指回协议源
- 提前发现“文档改了、结构化实现没改”或“结构化实现改了、文档没回写”的分叉
- 在显式传入变更文件，或可自动读取当前 git 工作区变更时，提示本轮还应同步检查的关联文件

适用场景：

- 改了协议文档中的映射关系后
- 改了 `lib/ai-pm-protocol/` 或 `lib/bootstrap/` 中的 Traceability 头后
- 想快速确认协议文档和结构化实现是否仍然双向对齐时
- 想确认“这次改了 A 文件，还应检查哪些关联文件”时

当前边界：

- V1 先覆盖协议文档与结构化实现的双向对照
- 变更影响分析的输入有两种：显式传 `--changed`，或未传时从当前 git 工作区自动识别变更文件（包括未暂存的修改）
- 还没有覆盖“协议文档 ↔ 工具脚本 ↔ 平台入口”的全量自动对照

---

## 重要说明

- 这些工具当前都以“安全优先”为原则
- 先校验，再补目录，再做受控写入
- 不应把它们理解为“已经完全替代主入口判断”
- 现阶段最可靠的用法是：`validate` + `route-check` + 有条件地执行 `bootstrap` 或 `devlog`

---

## 相关文档

- `lib/ai-pm-protocol/README.md`（协议结构化实现层的说明）
- `tests/README.md`（工具层测试的运行方式与覆盖范围）
