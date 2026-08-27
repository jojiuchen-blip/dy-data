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
- 主应用视觉回归 `python -m pytest tests/test_visual_smoke.py -q --tb=short`：229 passed，2 warnings。
- 主应用其余全量回归 `python -m pytest --ignore=tests/test_visual_smoke.py -q --tb=short`：1182 passed，2 skipped，261 warnings；与视觉回归合计 1411 passed、2 skipped、0 failed。
- `npm --prefix apps/web run build`：TypeScript 检查与 Vite 生产构建通过；仅保留现有大 chunk 警告。
- `git diff --check`：通过。
- 视觉用例中的旧财务页面标题已更新为 v2-clean 权威名称；结算默认门店、线索三级导航、订单详情 StrictMode 重放和文件上传增加异步就绪断言，未修改生产业务逻辑。
- 独立评审发现并关闭 3 个 Important 缺口：门店或月份切换且新账单仍在加载/刷新/失败时不再暴露旧账单确认动作；409 版本冲突立即关闭旧确认弹窗、使旧版本失效并重新拉取；线索演示模式恢复 `/admin/clue-allocation` 的 D05-D08 验收路径，但不扩展到财务、结算或通用管理页面。最终复审 Critical/Important/Minor 均为 0，Ready: yes。

## 当前边界与后续

原型仍只承担页面结构与业务交互基线，不代表真实 API、数据库、权限、导入或结算能力。生产代码的非阻塞对齐已在本分支独立提交；本地全量回归、390/768/1440 自动化浏览器验收和 Web 生产构建已通过。PR/CI、目标 PostgreSQL 门禁、目标环境部署与线上 smoke 仍是发布硬门禁。
