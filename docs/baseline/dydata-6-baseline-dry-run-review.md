# DYDATA-6 baseline dry-run 复核记录

## 结论

DYDATA-6 的正式 baseline 只能在扫描证据可信后生成。首次 dry-run 因证据分类错误被拒绝；修订套包扫描器并重新安装 2.0 后，第二次 dry-run 通过人工复核，可进入受控画像和正式 baseline 生成。

## 首次 dry-run：拒绝

- 错把 `.pytest_cache/README.md` 当成项目 README。
- 错把后端路由、`App.tsx`、`main.tsx` 和通用组件当成页面。
- 将 API 文件数量描述成接口线索，无法反映实际端点数量。
- 未识别 `models.py` 和 Alembic 迁移，模型证据为 0。
- 将 `__pycache__` 中的编译缓存当成配置证据。
- 输出包含开发机绝对路径，不适合提交到仓库。

因此，首次结果未生成正式 `project-profile.md` 或 `baseline-audit-dy-data.*`。

## 扫描器纠正

- 根目录 README 优先，并忽略依赖、构建产物、测试缓存、Python 缓存和编译文件。
- 页面只从明确的 `pages` / `views` / `screens` 目录或页面型文件名识别。
- API 文件、API 端点、模型文件、模型定义和迁移文件分别计数。
- 识别常规 `models.py`、实体文件与 Alembic / migration 路径。
- baseline 仅保留仓库相对路径；`hostRoot` 固定为 `.`。
- 页面用途、用户角色和页面定位不再由文件数量自动猜测。

套包回归结果：`npm run test:ai-pm`，114 项通过。

## 第二次 dry-run：通过

命令：

```text
node .agent/project-manager-suite/skills/01-01-project-baseline-auditor/scripts/collect-baseline-gaps.mjs . --json --dry-run --slug dy-data
```

复核证据：

| 证据 | 结果 | 人工判断 |
|---|---:|---|
| 项目 README | `README.md` | 正确 |
| 页面文件 | 14 | 均位于 `apps/web/src/pages/`，未混入组件或后端路由 |
| API 源文件 | 9 | 8 个后端 routes 文件 + 1 个前端 API client |
| API 端点 | 63 | 来自后端路由装饰器声明 |
| 模型定义 | 37 | 来自 ORM `Base` 模型声明 |
| 迁移文件 | 17 | 与 `alembic/versions/` 当前文件数一致 |
| 配置线索 | 5 | 未混入 `__pycache__` 或 `.pyc` |
| 绝对路径 | 0 | baseline 只使用相对路径 |

第二次 dry-run 仍报告 BRD、PAGE_EXPLAINER、FOUNDATION、PRD 缺失，这是套包正式产物缺口，不代表现有项目没有任何产品、视觉、架构或规格材料。现有材料的权威级别与迁移关系以 `docs/governance/authority-map.md` 为准。

## 后置索引复核

baseline 完成后，`ai-project-manager` 按路由要求调起 `project-link-indexer`。首次生成的 `project-link-graph.json` 暴露了同类可移植性缺陷：`hostRoot` 使用了 worktree 绝对路径。该结果未被接受为最终产物。

标准套包已补测试并修订为 `hostRoot: "."`，同时将 `.pytest_cache`、Python 缓存和本地虚拟环境纳入统一忽略清单。重新安装后强制刷新索引，最终包含 296 个节点、58 条关系、0 个诊断问题，且不再包含缓存节点或本地运行日志；baseline、文件索引、安装清单和版本锁均不包含本机绝对路径。
