# dy-data 宿主专项规则

这里是项目真实技术栈和任务类型规则的唯一落点。套包提供路由与通用协议，本目录负责把它们适配为 dy-data 可执行规则。

## 规则入口

- `backend-tasks.md`：FastAPI、SQLAlchemy、认证授权和 API 变更。
- `database-tasks.md`：PostgreSQL、Alembic、数据回填和查询验证。
- `frontend-tasks.md`：React、TypeScript、Vite、真实 API 和视觉系统。
- `debugging.md`：从症状到数据、服务、页面和生产环境的逐层取证。
- `docs-and-plans.md`：Linear、执行驾驶舱、项目画像和文档权威同步。
- `devlog.md`：`docs/devlog/` 的可提交开发日志和 `/logs/` 的运行日志边界。

## 使用方式

1. 按 `AGENTS.md` 完成 turn gate、套包锁和阶段路由。
2. 根据任务类型加载本目录中最小必要规则。
3. 技术事实冲突时以当前代码、依赖、迁移、部署配置和真实环境证据为准。
4. 需求范围、优先级、验收和状态以 Linear 为准；本目录不复制 issue 内容。

规则模板来自公司套包，但本目录内容必须根据宿主技术栈维护，不能从套包默认示例直接复制其他语言、框架或数据库约束。
