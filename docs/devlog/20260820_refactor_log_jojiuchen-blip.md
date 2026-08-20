# 开发日志 — 2026-08-20

> 主题：DYDATA-71/72/75 进入 S4 生产修复
> 操作人：jojiuchen-blip
> 关联计划：docs/plans/execution-plan.md

---

## 一、执行概要

| # | 任务 | 关联 | 状态 |
|---|------|------|------|
| 1 | DYDATA-71/72/75 进入 S4 生产修复 | 本轮推进 | ✅ |
| 2 | T1.1 分佣规则与账号管理优化 | DYDATA-71 | ✅ |
| 3 | T1.2 商品口径自定义值 | DYDATA-72 | ✅ |
| 4 | T1.3 订单费用明细直达访问 | DYDATA-75 | ✅（待发布） |

**本日关键结论**：三项业务实现、目标回归、全量门禁和独立评审已完成；当前进入提交、远端 CI、合并与腾讯云公网环境发布。

---

## 二、操作详情

### 任务 1：DYDATA-71/72/75 进入 S4 生产修复
- **目标**：核验四项用户反馈并完成开发、验证和生产部署
- **操作**：拉取远端 main；读取 Linear DYDATA-71/72/75；创建隔离 worktree 与正式三任务交付计划；完成计划结构和一致性校验
- **结果**：正式计划已建立，T1.1 进入进行中；当前根因已定位，待建立失败测试后实现
- **涉及文件**：无

### 任务 2：T1.1 分佣规则与账号管理优化
- **目标**：固定并高亮四步流程、精简入口、强化启停状态和商品口径提醒；提升指定门店账号配置效率。
- **操作**：实现 sticky 步骤导航、移除浏览搜索、将批量导入移入第 1 步；新增商品类型提醒；新增门店搜索/CSV-TXT 导入、服务端技术用户名生成和右侧独立滚动。
- **结果**：目标 API/前端测试 18 项通过，Web production build 通过。
- **涉及文件**：`apps/web/src/pages/AdminSkuRulesPage.tsx`、`apps/web/src/pages/AdminAccountsPage.tsx`、`apps/web/src/styles.css`、`apps/api/dy_api/routes/admin.py`、`apps/api/dy_api/schemas.py`

### 任务 3：T1.2 商品口径自定义值
- **目标**：允许产品范围和商品类型创建合法新值，同时保持单字段兼容校验和导入原子性。
- **操作**：编辑器改为可输入建议值；API 允许同次显式新组合，拒绝保留字、空白和超长值；统一单个、批量和导入提交规则。
- **结果**：API 35 项、前端契约 6 项通过，Web production build 通过。
- **涉及文件**：`apps/web/src/pages/AdminProductTypeVisibilityPage.tsx`、`apps/api/dy_api/routes/fee_admin.py`、`apps/api/dy_api/schemas.py`

### 任务 4：T1.3 订单费用明细直达访问
- **目标**：允许直接访问 `/details`，并始终限制在账号授权门店范围内。
- **操作**：前端取消来源门禁并区分直达/下钻文案；API 允许无来源查询；数据层按可选门店、月份和强制授权门店集合拼接过滤；同步 PRD/API Foundation。
- **结果**：RED 3 项失败后转 GREEN；相关 API 28 项、视觉 10 项、前端契约 54 项通过。最终全量回归 1216 passed、2 skipped、0 failed；Web production build、diff check 与独立评审通过。
- **涉及文件**：`apps/web/src/pages/OrderDetailsPage.tsx`、`apps/api/dy_api/routes/dashboard.py`、`apps/api/dy_api/routes/_data.py`、`docs/prd/subprd/03-subprd-order-fee-details.md`、`docs/prd/foundation/foundation-api-dy-data/settlement-reporting.md`

<!-- 复杂决策型任务可展开分析：
### 任务 N：标题（决策类）
- **背景问题**：为什么要做这个决策
- **方案对比**：（表格或列表）
- **最终决策**：选了什么 + 为什么
- **涉及文件**：列表
-->

---

## 三、变更总览

### 文件变更清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `apps/web/src/pages/AdminSkuRulesPage.tsx`、`apps/web/src/styles.css` | 分佣步骤、状态和商品口径提醒 |
| 修改 | `apps/web/src/pages/AdminAccountsPage.tsx`、`apps/api/dy_api/routes/admin.py`、`apps/api/dy_api/schemas.py` | 账号门店选择、导入、滚动和技术用户名 |
| 修改 | `apps/web/src/pages/AdminProductTypeVisibilityPage.tsx`、`apps/api/dy_api/routes/fee_admin.py` | 商品口径自定义值 |
| 修改 | `apps/web/src/pages/OrderDetailsPage.tsx`、`apps/api/dy_api/routes/dashboard.py`、`apps/api/dy_api/routes/_data.py` | 订单明细直达与授权范围过滤 |
| 修改 | `tests/` 相关用例 | TDD 回归与过期验收更新 |
| 修改 | `docs/prd/`、`docs/plans/` | 契约与交付证据同步 |

> 收口时由 AI 从各任务「涉及文件」聚合去重生成。操作类型：新建 / 修改 / 删除。

### Git 提交记录

| 时间 | Commit | 内容 |
|------|--------|------|

---

## 四、发现的问题 / 缺陷

- 订单费用明细前端、API 和 SQL 三层都把来源上下文误当作必需条件，导致菜单直达被阻断。
- 一条历史静态测试仍要求保留已由 DYDATA-71 删除的“产品范围浏览搜索”，已更新为新验收口径。

---

## 五、复盘

### 做得好的
- 对三个需求分别建立目标回归，并保留门店越权与导出范围用例。
- 先同步 Linear 最新反馈，再改实现和权威 PRD/API 文档，避免历史说明覆盖新需求。

### 遇到的问题
- **现象**：`/details` 无来源时不发请求且 API 返回 422。
- **根因**：页面 `enabled`、API 参数校验和 SQL 固定过滤同时依赖来源上下文。
- **经验**：> 直达页面的默认数据范围必须由登录态授权决定，来源参数只能缩小范围，不能承担授权职责。
- **🔧 是否提炼为规则**：⬜ 仅记录

### 今日经验总结
1. 来源参数与权限范围必须分离 → 仅记录
2. 用户删除模块后要同步清理强制保留旧模块的静态测试 → 仅记录

---

## 五·附、方法论沉淀（可选）

> 当天工作中如果有可复用的方法论、设计原则、或跨项目通用的经验，在此抽象记录。
> 普通开发日不需要填写此章节。

---

## 六、待跟进事项

- [ ] 全量 pytest 与独立评审已完成；待提交与 CI。
- [ ] 合并 `main` 后触发 Tencent Lighthouse Deploy，并记录部署 SHA 与业务页面 smoke。
- [ ] 回填 DYDATA-71、DYDATA-72、DYDATA-75，等待人类 Owner 最终验收。
