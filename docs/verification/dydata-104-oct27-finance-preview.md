# DYDATA-104 财务导入逐行冻结预览 UI

2026-10-27；前端基线 `9fafcf7`，真实 API 联调使用财务 worker 的 `e31b82f0`（本树 cherry-pick 为 `a2ce16e`）。该后端提交仅为联调依赖，前端交付提交不重复包含其文件。没有生产请求、生产改账、Linear 消息或 push。

## 用户可见行为

- 上传并预览后及导入记录详情均显示同一个业务预览表：原文件行号、完整门店/发票编号、字段原值→新值、是否变更、状态变化、允许修改范围和阻断原因。
- 表格只消费 `GET /api/v1/admin/finance-imports/{batchId}/rows?page=&pageSize=` 保存的上传时快照。没有通过当前业务资料另查或拼造原值；旧批次未冻结时明确要求重新上传。
- 金额沿用整数分格式化，`0`、`null`、空文本、缺失字段分别显示；不存在目标与已撤销资料分别说明。业务 ID 始终保留字符串。
- 复用 DataTable、TablePagination、ResourcePanel、Button，无新增 CSS 或设计令牌。每页20/50条；空结果不显示“1-0”这种伪范围。
- 只有后端整批 `previewSummary.frozenAvailable=true`、阻断行数0、实际存在预览行、当前行未阻断，且批次场景为可确认，才启用现有“确认提交”。加载、请求失败、旧批次、全批其他页存在阻断时均禁用；后端仍负责最终权限、状态与并发复验。
- 上传、预览和切批次相互隔离；已取消上下文的迟到上传结果不覆盖当前表单，已卸载批次的迟到预览不串数据。同页跳转不会误把已就绪批次永久禁用。没有自动提交。

## 验证环境与方法

Browser plugin not available，使用仓库现有 Python Playwright / Chromium。真实 FastAPI、独立合成 SQLite 数据库和真实 Vite 前端；只有测试身份由既有 fixture 提供，不替换成功 API 响应。加载态测试仅暂停请求再放行，响应仍由真实 API 生成。运行在回环地址随机端口，桌面1440×1000、移动390×844。

测试主路径：`/finance/stores?month=2026-08` → 上传合成 CSV → 冻结逐行预览 → 分页/失败重试/显式确认；详情路径 `/finance/imports?month=2026-08` → 选择批次 → 同表核对。

```powershell
python -m pytest tests/test_dydata104_finance_preview_browser.py tests/test_design_system_enforcement.py tests/test_frontend_user_facing_contracts.py -q --tb=short
npm --prefix apps/web run build
git diff --check
```

最终结果：联合 pytest `43 passed`，退出码0（其中真实 API 浏览器5项，设计/用户文案约束38项）；TypeScript检查及 Vite生产构建通过，退出码0；`git diff --check` 退出码0。构建仅有既有大包警告，pytest仅有既有MCP认证配置弃用提示。

新增5个真实 API 浏览器测试：

1. 实际上传61行，预览请求加载时禁止提交；上传后直接修改合成当前档案，页面仍显示冻结的旧 SAP；完整长门店ID及分页正确；后台真实403禁用并可重试恢复；无自动提交。
2. 旧批次请求延迟时切换新批次，旧响应不会串入；历史无快照批次提示未知；缺少行数据时为空态；移动端无页面水平溢出。
3. 第61行被后端阻断，即使第一页各行通过，也不能确认整批；翻页可看到具体业务键和阻断原因。
4. 合成冻结记录中保留金额0、null及缺失键，真实GET和页面分别显示，长发票号无精度丢失，内部状态转中文。
5. 只有明确点击“确认提交”才调用正式提交/更正接口；成功后读取合成数据库验证当前资料确已变更。

页面身份、非空内容、关键交互、运行时错误以及桌面截图均核查；移动截图核查旧快照缺失警示和空态。截图位于 pytest 临时工件目录的 `frozen-preview-desktop.png` / `legacy-preview-mobile.png`，不提交真实数据或图片。

## 验收边界

真实数据库/上传/权限/提交链路已在合成环境执行；不代表生产部署或历史财务数据已完成业务验收。后端金额/状态矩阵及 PostgreSQL 专项由对应 worker 的财务验证记录负责。当前前端不额外计算业务允许规则，只消费冻结预览和整批汇总；后端最新状态可能仍在明确提交时拒绝并发冲突。

本任务无新增 foundation 漂移；未修改基础文档、计划、后端路由、模型、迁移或其他 worker 的测试。生产发布和全库集成 CI 由主线程独立验收。
