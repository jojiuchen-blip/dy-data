# 编码规范索引

> **适用项目**：通用 Java Spring Boot + Vue 3 + MySQL + Python 技术栈项目
> **规范来源**：阿里巴巴 Java 开发手册 + PEP 8 / Google Python Style Guide + 项目实际技术栈定制
> **使用方式**：AI 通过 `project-manager-suite/skills/06-01-coding-standards/SKILL.md` 自动导航；人工可直接浏览本索引
> **权威源说明**：本目录是当前 skill 的规范权威源；若当前 AI IDE 不支持 skill，直接从本文件进入即可

---

## 规则等级

| 标记 | 含义 |
|------|------|
| 【强制】 | 必须遵守，违反可能导致 Bug 或严重可维护性问题 |
| 【推荐】 | 建议遵守，提升代码质量和一致性 |
| 【参考】 | 了解即可，视场景灵活采用 |

---

## 当前规范文件一览

| # | 文件 | 适用场景 |
|---|------|---------|
| 01 | [01-java-naming.md](./01-java-naming.md) | 类名、方法名、变量名、常量、DTO / VO / Entity 命名 |
| 02 | [02-java-formatting.md](./02-java-formatting.md) | Java 缩进、大括号、换行、注释格式 |
| 03 | [03-java-oop.md](./03-java-oop.md) | OOP 规约、集合处理、并发与设计细节 |
| 04 | [04-java-exception-log.md](./04-java-exception-log.md) | 异常处理、日志输出、错误口径 |
| 05 | [05-mysql-table.md](./05-mysql-table.md) | 建表、字段、索引、DDL 规范 |
| 06 | [06-mysql-sql-orm.md](./06-mysql-sql-orm.md) | SQL 编写、查询优化、MyBatis / ORM 映射 |
| 07 | [07-vue-frontend.md](./07-vue-frontend.md) | Vue 3 组件、页面、交互与样式规范 |
| 08 | [08-engineering.md](./08-engineering.md) | 工程分层、领域模型、模块边界 |
| 09 | [09-api-design.md](./09-api-design.md) | REST API 设计、请求响应格式、分页与契约 |
| 10 | [10-python-naming-style.md](./10-python-naming-style.md) | Python 命名、导入、类型注解、Docstring（Google 风格） |
| 11 | [11-python-engineering.md](./11-python-engineering.md) | Python 异常处理、日志、项目结构、依赖管理 |

---

## 当前范围说明

- 当前仓库实际内置的是 `01` 到 `11` 共 11 份规范文档（`01`-`09` 为 Java/MySQL/Vue/API，`10`-`11` 为 Python）。
- 测试规范和测试用例文档规范目前**未在本目录落地文件**，维护索引时不应提前列出不存在的文件。
- 若后续补充测试相关规范，文件名使用 `12-testing.md` 和 `13-test-case-design.md`（`10`/`11` 已被 Python 规范占用，不得复用编号），并同步更新本索引和 `coding-standards/SKILL.md` 的路由表。

---

## 规范未覆盖技术栈时的回退口径

任务涉及本目录没有专门规范的技术栈（例如 Node.js 后端、SQLite、Go 等）时，按以下顺序回退，**不要现场编造整套语言规范，也不要假装存在未落地的规范文件**：

1. **通用工程规范优先**：加载 [08-engineering.md](./08-engineering.md)，其中分层、模块边界、领域模型等约束与具体语言无关，直接适用。
2. **宿主技术栈约定其次**：遵循宿主项目自身的技术约定（项目规则文件、README、BRD 中注明的技术选型），以及套件的默认技术栈参考 `ai-project-manager/references/defaults/tech-stack.md`。
3. **邻近规范类比参考**：语义相通的条目可类比采用（如命名一致性、异常必须处理、日志不吞错等跨语言通则），但只取通则，不照搬语言特有语法规则。
4. **显式标注缺口**：在产出中说明"该技术栈无专门规范，按通用工程规范 + 宿主约定执行"，方便后续补规范时回溯。

---

## 加载规则

1. **AI 加载**：通过 `coding-standards` skill 自动匹配任务类型，只读取 1-2 个最相关子文档。
2. **人工查阅**：按上表找到对应文件直接阅读。
3. **禁止全量读入**：除非在做规范盘点或规则迁移，否则不要一次性读完整个目录。
