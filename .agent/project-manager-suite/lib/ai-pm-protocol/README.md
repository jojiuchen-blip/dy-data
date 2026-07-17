# AI Development Assistant Protocol Layer

这一层是开发助手内部主入口 `ai-project-manager` 后续脚本化改造的统一规则源。

当前阶段只做第一版协议配置落地，不直接承担执行逻辑。

## 文件说明

- `constants.js`
  定义通用枚举，例如字段层级、字段来源、文件角色、阶段 ID。
- `file-roles.js`
  定义 3 类全局文件和 1 类状态回写能力的角色信息。
- `field-contracts.js`
  定义字段包与每类全局文件的字段合同。
- `stages.js`
  定义阶段、最小交付物、默认承接 skill 和阶段判断规则。
- `routing.js`
  定义阶段到能力的路由映射、准入规则和页面标签归一规则。
- `rules-sync.js`
  定义宿主 `docs/rules/` 规则同步策略。
- `bootstrap.js`
  定义 hooks / OpenCode / Codex 三种启动引导通道的统一策略元数据。
- `index.js`
  汇总导出。

## 当前边界

这一层当前不直接：

- 解析 Markdown 文档
- 改写宿主项目文件
- 自动生成 bootstrap 正文
- 自动执行阶段判断

这些能力会在后续脚本和 bootstrap 生成层中逐步接入。

## 设计要求

- 新增字段时优先修改字段合同，而不是散改多个脚本
- 新增阶段时优先修改阶段和路由模块
- 新增平台注入通道时优先复用 bootstrap 配置
- 后续工具脚本应尽量只依赖本目录，不直接硬编码协议文本
