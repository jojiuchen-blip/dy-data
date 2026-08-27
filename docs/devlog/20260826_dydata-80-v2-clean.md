# DYDATA-80 v2-clean 开发记录

## 本次变更

- 从最新 `origin/main` 建立隔离分支，保留原工作区未提交改动不变。
- 清理财务看板原型中的 Mock 标记、原型边界横幅、场景切换器和角色切换演示控件。
- 将“演示动作 / 模拟导入成功 / 演示数据”等可见文案改为正式业务动作名称。
- 删除未再被页面引用的 `ScenarioSwitcher` 与 `ImportDialog` 组件，并清理对应无效样式。
- 新增 v2-clean 页面结构与业务交互验收基线及路由矩阵；视觉继续继承主系统 V0.2，不另建规范。

## 验证

- `npm test -- --reporter=dot --maxWorkers=1 --no-file-parallelism`：71 passed。
- `npm run build`：通过。
- 浏览器访问当前工作树独立端口的 `/finance/promotion`：演示文案与演示控件不存在，财务角色上下文保留；截图为 `pwScreenShot/dydata-80-prototype-finance-promotion-1440.png`。

## 当前边界与后续

原型仍只承担页面结构与业务交互基线，不代表真实 API、数据库、权限、导入或结算能力。生产代码的非阻塞对齐已在本分支独立提交；全量回归、390/768/1440 浏览器验收、PR/CI、目标环境部署与 smoke 仍是发布硬门禁。
