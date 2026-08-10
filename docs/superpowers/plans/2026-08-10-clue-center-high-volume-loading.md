# 线索中心高数据量加载优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让线索中心保留旧数据后台刷新、合并重复 GET、按需搜索门店、压缩传输并让正式品牌署名随腾讯云版本生效。

**Architecture:** 保留现有 React/FastAPI/SQLAlchemy 技术栈。前端增强资源状态和请求协调，后端把全量门店列表从初始筛选响应拆成有权限边界的限量搜索接口，Nginx 只做安全压缩不做用户数据共享缓存；正式构建按页面拆包并验证品牌产物。

**Tech Stack:** React 19、TypeScript 5、Vite 7、FastAPI、Pydantic、SQLAlchemy、PostgreSQL、SQLite 测试、Nginx、Pytest。

## Global Constraints

- 商品类型默认值必须继续是 `all`。
- 浏览器缓存必须按登录用户隔离，并在登录/退出时清理。
- 不得在 Nginx 缓存带 Cookie 的业务 API 响应。
- 门店搜索必须复用当前账号的 store scope 和商品类型可见性约束。
- 腾讯云整机 CPU 与内存不得持续超过 70%。
- 不删除业务数据，不启用已关闭的定时任务。
- 所有行为变更必须先看到对应测试按预期失败，再写生产实现。

---

### Task 1: 资源状态保留与最后请求获胜

**Files:**
- Modify: `apps/web/src/hooks/useApiResource.ts`
- Test: `tests/test_frontend_clue_center.py`

**Interfaces:**
- Produces: `useApiResource(...): { data, error, rawError, loading, refreshing, reload }`
- Invariant: `loading === true` 仅在无成功数据时成立；刷新失败不清空 `data`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_frontend_clue_center.py` 添加源码契约，要求 hook 使用函数式状态更新保留 `current.data`、暴露 `refreshing`，并用请求序号拒绝过期响应。

- [ ] **Step 2: 验证 RED**

Run: `python -m pytest -q tests/test_frontend_clue_center.py -k resource_preserves`

Expected: FAIL，现有 hook 明确写入 `data: undefined` 且没有 `refreshing`。

- [ ] **Step 3: 最小实现**

使用 `useRef` 保存 request ID；启动请求时保留现有 data，成功/失败只允许最新 ID 更新；禁用资源时清空状态。

- [ ] **Step 4: 验证 GREEN**

Run: `python -m pytest -q tests/test_frontend_clue_center.py -k resource_preserves`

Expected: PASS。

### Task 2: GET 合并与用户隔离的短时缓存

**Files:**
- Modify: `apps/web/src/api/client.ts`
- Test: `tests/test_frontend_clue_center.py`

**Interfaces:**
- Produces: `requestJson(path, params, options)`，options 支持 `cacheKey`、`maxAgeMs`、`forceRefresh`。
- Produces: `clearRequestJsonCache()`，登录和退出前后调用。

- [ ] **Step 1: 写失败测试**

添加契约测试，要求存在进行中请求 Map、TTL Map、100 键上限、认证切换清理，以及 overview 只合并不持久缓存。

- [ ] **Step 2: 验证 RED**

Run: `python -m pytest -q tests/test_frontend_clue_center.py -k request_deduplication`

Expected: FAIL，当前每次直接 `fetch`。

- [ ] **Step 3: 最小实现**

按完整 URL 和显式用户 cache namespace 生成键；复用未完成 Promise；只给门店搜索配置 60 秒 TTL；插入第 101 个键时淘汰最旧键；登录/退出清空。

- [ ] **Step 4: 验证 GREEN**

Run: `python -m pytest -q tests/test_frontend_clue_center.py -k request_deduplication`

Expected: PASS。

### Task 3: 小型筛选元数据与按需门店搜索 API

**Files:**
- Modify: `apps/api/dy_api/schemas.py`
- Modify: `apps/api/dy_api/routes/clues.py`
- Modify: `apps/api/dy_api/routes/_data.py`
- Test: `tests/test_api_clues.py`

**Interfaces:**
- Extends: `GET /api/v1/clues/filters?include_assigned_stores=false`
- Produces: `GET /api/v1/clues/filter-options/stores`
- Produces: `DashboardDataStore.clue_store_options(...) -> list[dict[str, str]]`

- [ ] **Step 1: 写失败 API 测试**

覆盖：旧 filters 默认仍返回门店；`include_assigned_stores=false` 返回空列表；新接口按 q/省/市筛选；limit 最大 100；selected store 被保留；普通门店账号无法搜索越权门店。

- [ ] **Step 2: 验证 RED**

Run: `python -m pytest -q tests/test_api_clues.py -k 'filter_options or excludes_assigned_stores'`

Expected: FAIL，新参数和路由不存在。

- [ ] **Step 3: 最小实现**

在数据层复用 `_store_scope_clause`、`_visible_product_type_clause`，使用参数化 `LOWER(name) LIKE :query`、`DISTINCT` 和 `LIMIT :limit`；路由使用 Pydantic 返回 `StoreOption` 列表。

- [ ] **Step 4: 验证 GREEN**

Run: `python -m pytest -q tests/test_api_clues.py -k 'filter_options or excludes_assigned_stores'`

Expected: PASS。

### Task 4: 线索页面按需加载门店与一致状态

**Files:**
- Modify: `apps/web/src/components/SearchableStoreSelect.tsx`
- Modify: `apps/web/src/pages/ClueCenterPage.tsx`
- Modify: `apps/web/src/api/client.ts`
- Modify: `apps/web/src/types/dashboard.ts`
- Test: `tests/test_frontend_clue_center.py`

**Interfaces:**
- Adds optional props: `loading`, `onSearch`, `onOpen` to `SearchableStoreSelect`。
- Produces: `fetchClueStoreOptions(query, userCacheScope)`。

- [ ] **Step 1: 写失败前端测试**

要求初始 filters 明确传 `include_assigned_stores=false`；门店组件聚焦后加载、输入 200ms 防抖；页面使用 `refreshing` 文案；旧 overview 存在时不显示不可用面板；默认商品类型仍为 all。

- [ ] **Step 2: 验证 RED**

Run: `python -m pytest -q tests/test_frontend_clue_center.py -k 'lazy_store or background_refresh or default_product'`

Expected: FAIL。

- [ ] **Step 3: 最小实现**

增加可选异步 props；ClueCenter 维护查询、防抖值和是否启用；所选门店 ID 传给 API；主资源文案不依赖筛选资源 loading。

- [ ] **Step 4: 验证 GREEN**

Run: `python -m pytest -q tests/test_frontend_clue_center.py -k 'lazy_store or background_refresh or default_product'`

Expected: PASS。

### Task 5: 安全压缩与按页面拆包

**Files:**
- Modify: `deploy/nginx.conf`
- Modify: `apps/web/src/App.tsx`
- Test: `tests/test_frontend_clue_center.py`
- Test: `tests/test_deploy_contract.py`（若不存在则在最接近的 deploy contract 测试文件追加）

**Interfaces:**
- Nginx: `gzip on`、`gzip_vary on`、`gzip_min_length 1024` 和安全 MIME 列表。
- React: 非当前页面使用 `lazy(() => import(...))` 和统一 `Suspense` 占位。

- [ ] **Step 1: 写失败测试**

要求 Nginx 含 gzip 指令且 `/api/` 无 `proxy_cache`；要求 App 使用 lazy/Suspense，不再同步导入所有重页面。

- [ ] **Step 2: 验证 RED**

Run: `python -m pytest -q tests/test_frontend_clue_center.py tests/test_deploy_contract.py -k 'gzip or lazy_route'`

Expected: FAIL。

- [ ] **Step 3: 最小实现**

配置 gzip；把页面改为具名导出兼容的 lazy wrapper；保持授权门禁和路由逻辑不变。

- [ ] **Step 4: 构建验证**

Run: `npm run build`

Expected: exit 0，入口 JS 显著小于基线 1.39 MB，页面代码输出为异步 chunks。

### Task 6: 品牌署名构建与回归

**Files:**
- Verify: `apps/web/src/components/BrandAttribution.tsx`
- Verify: `apps/web/src/components/brand-attribution-masks.ts`
- Verify: `apps/web/src/components/Shell.tsx`
- Test: `tests/test_frontend_theme_brand.py`
- Test: `tests/test_design_system_docs.py`
- Test: `tests/test_visual_smoke.py`

**Interfaces:**
- Consumes: `npm run build:brand-attribution`
- Produces: 正式 dist 中可检索到 `dc-brand-attribution` 与 SPACE mask 数据。

- [ ] **Step 1: 运行生成器并检查无漂移**

Run: `npm run build:brand-attribution`

Expected: exit 0；`git diff -- apps/web/src/components/brand-attribution-masks.ts docs/design-system/attribution/brand-attribution-masks.css` 无意外差异。

- [ ] **Step 2: 运行品牌测试**

Run: `python -m pytest -q tests/test_frontend_theme_brand.py tests/test_design_system_docs.py tests/test_design_system_enforcement.py`

Expected: 全部 PASS。

- [ ] **Step 3: 检查正式构建产物**

Run: `rg -n 'dc-brand-attribution|SPACE AI Native' apps/web/dist`

Expected: 至少命中组件 class/无障碍标签或生成 mask。

### Task 7: 全量回归、性能门禁和发布准备

**Files:**
- Create: `docs/operations/clue-center-performance-release.md`
- Verify: all modified files

**Interfaces:**
- Produces: 唯一镜像标签、旧镜像回滚表、测试/性能/资源证据。

- [ ] **Step 1: 全量本地回归**

Run: `python -m pytest -q tests/test_frontend_clue_center.py tests/test_api_clues.py tests/test_frontend_theme_brand.py tests/test_design_system_enforcement.py tests/test_design_system_docs.py`

Run: `npm run build`

Expected: 全部 exit 0。

- [ ] **Step 2: 静态检查**

Run: `python -m compileall -q apps/api/dy_api`

Run: `git diff --check`

Expected: exit 0。

- [ ] **Step 3: 测试环境性能验证**

记录小 filters 响应体积、overview/store search p50/p95、重复请求数、入口 chunk 体积、LCP/INP/CLS；任何指标未达设计目标则不进入部署。

- [ ] **Step 4: 腾讯云可回滚部署**

记录旧镜像；构建唯一标签；仅替换 API/Web/Proxy；验证健康、真实数据、默认全部类型、后台刷新、门店搜索、gzip 和品牌署名；监控 CPU/内存不持续超过 70%。失败则恢复旧标签。

## 自检

- 设计中的旧数据保留、请求合并、按需筛选、缓存、压缩、默认全部类型、包拆分、品牌署名、70% 资源门禁和回滚均有对应任务。
- 计划未引入 Redis、数据库分片或全站资源层迁移。
- 后端权限边界和前端用户缓存命名空间保持一致。
