# DYDATA-71/72/75 生产修复主交付计划

> **版本**：v1
> **发布日期**：2026-08-20
> **适用范围**：账号管理、分佣规则、商品口径、订单费用明细
> **开发模式**：isolated-worktree
> **上游发现结论**：canProceed=true, slug=dy-data
> **人类授权**：用户已明确要求拉取远端、核验本轮需求并最终生产部署

## 0. 本计划使用指南

1. 以 Linear DYDATA-71、DYDATA-72、DYDATA-75 的最新描述和评论为需求、范围及验收权威。
2. 按 T1.1 → T1.2 → T1.3 执行；每个 Task 开始前读取对应子计划和真实代码。
3. 每项先补失败测试，再做最小实现；最终统一进入全量验证、代码评审、合并与生产发布。

### 0.1 PRD 加载约束

- 读取 `docs/prd/mainprd-dy-data.md` 建立结算与后台全局地图。
- T1.1 以 DYDATA-71 和 `docs/rules/account-access-control.md` 为主。
- T1.2 以 DYDATA-72、SKU 商品口径 API/Schema foundation 为主。
- T1.3 以 DYDATA-75、订单费用明细 PRD/API foundation 为主。
- Linear 新反馈覆盖历史计划中的过期“不开发/不部署”说明，但不得覆盖权限和数据正确性硬规则。

### 0.2 读前门禁 / AI 自检清单

- [x] 远端 `origin/main` 已拉取到 `ee7fb990acb83274f6443135eafdf498c39925cb`。
- [x] 当前工作位于隔离 worktree 和 `codex/dydata-71-72-75-production-fixes` 分支。
- [x] 三个 Linear issue 均已读取，第四项反馈已归入 DYDATA-71。
- [x] 已核对前端、API、权限规则和现有测试中的根因证据。
- [x] 当前 Task 的失败测试已建立并稳定复现。

### 0.3 完成前验证门禁

- 执行 `git diff --check`、相关 pytest、`python -m pytest`、`npm --prefix apps/web run build`。
- 对账号门店权限验证存在/重复/越权输入；对订单明细验证全局与指定门店账号范围。
- 对页面关键状态执行 Playwright 或浏览器截图核验。
- 生产发布必须记录 CI、部署 SHA、公开 smoke、回滚点和 Linear 回填。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Node.js | >= 18（本地 v24.18.0） | `node --version` |
| Python | >= 3.12（本地 3.12.10） | `python --version` |
| Git | 可访问 origin | `git --version` |

| 工程依赖目录 | 检测命令 |
|---|---|
| `apps/web/node_modules/` | `Test-Path apps/web/node_modules` |

> 本地没有 Docker；它不是 T1.1-T1.3 的本地执行依赖。镜像构建由 GitHub Actions 发布闸门执行并提供证据。

## 1. 差距基线

| 差距 | 影响 | 对应任务 | 状态 |
|---|---|---|---|
| 分佣步骤条不固定、不联动高亮，入口重复且状态区分弱 | 批量发布流程难定位 | T1.1 | 已修复 |
| 分佣 SKU 未配置商品类型时无跨页提醒 | 用户不知道应到商品口径维护 | T1.1 | 已修复 |
| 指定门店账号缺少门店搜索、批量导入，创建表单不能独立滚动 | 多门店账号配置效率低 | T1.1 | 已修复 |
| 新建账号仍要求手填技术账号名 | 业务表单暴露内部标识 | T1.1 | 已修复 |
| 商品口径编辑只能选择现有值，后端拒绝新组合 | 无法添加新的产品范围和商品类型 | T1.2 | 已修复 |
| 订单明细无来源参数时前端不请求、后端返回 422 | 菜单直接访问不能展示数据 | T1.3 | 已修复，待发布 |

## 2. 分工与边界

| 角色 | 职责 |
|---|---|
| AI | 需求核验、测试驱动实现、验证、提交、发布与证据回填 |
| 人类 Owner | 最终业务验收与 Done 决策 |
| GitHub Actions | 全量 CI、镜像构建、腾讯云生产部署 |

- 不改变分佣费率计算、生效时间、版本语义和历史结算结果。
- 不削弱账号页面权限或门店数据范围；批量导入只更新当前表单草稿。
- 技术用户名继续保留为唯一鉴权/审计标识，新建时由服务端生成，编辑时保持不变。
- 商品口径自定义值不建立第二真相源；成功写入后即由 `dim_sku_product_rules` 进入现有元数据集合。

## 3. 执行阶段

### Phase 1：后台交互与账号门店选择

**Entry Criteria**：DYDATA-71 最新反馈、权限规则和现有页面代码已读取。

**Exit Criteria**：T1.1 验收测试通过，不改变权限边界。

| Task | 子开发计划 | 状态 | 完成日期 |
|---|---|---|---|
| T1.1 | [sub-delivery-plan-dydata-71-72-75-production-fixes-T1.1-admin-ui.md](sub-delivery-plan-dydata-71-72-75-production-fixes-T1.1-admin-ui.md) | 已完成 | 2026-08-20 |

### Phase 2：商品口径自定义值

**Entry Criteria**：T1.1 完成；DYDATA-72 的组合校验决策已写入测试。

**Exit Criteria**：单个、批量与文件导入均接受合法新值并保持原子性。

| Task | 子开发计划 | 状态 | 完成日期 |
|---|---|---|---|
| T1.2 | [sub-delivery-plan-dydata-71-72-75-production-fixes-T1.2-product-types.md](sub-delivery-plan-dydata-71-72-75-production-fixes-T1.2-product-types.md) | 已完成 | 2026-08-20 |

### Phase 3：订单明细直接访问与生产发布

**Entry Criteria**：T1.1、T1.2 完成；订单明细门店范围查询方案已有 API 测试。

**Exit Criteria**：直接访问与下钻访问均正常，全量门禁、远端 CI、生产部署和 smoke 通过。

| Task | 子开发计划 | 状态 | 完成日期 |
|---|---|---|---|
| T1.3 | [sub-delivery-plan-dydata-71-72-75-production-fixes-T1.3-order-details-release.md](sub-delivery-plan-dydata-71-72-75-production-fixes-T1.3-order-details-release.md) | 进行中 | - |

## 4. 任务看板

- 看板入口：[task-kanban-dydata-71-72-75-production-fixes.md](task-kanban-dydata-71-72-75-production-fixes.md)

## 5. 发布闸门

- [ ] T1.1、T1.2、T1.3 的 Verification Method 已执行并记录 Evidence
- [x] `git diff --check`、全量 pytest、Web production build 均通过
- [x] 独立代码评审无阻断问题
- [ ] 分支推送、合并到 `main`、GitHub Verify 和腾讯云部署成功
- [ ] 生产 `/`、鉴权端点及三个目标页面 smoke 通过
- [ ] DYDATA-71、DYDATA-72、DYDATA-75 回填提交、CI、部署和剩余风险

## 6. 风险与应对

| 风险 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| 自定义商品口径形成无意组合 | 报表筛选口径混乱 | 仅允许非保留、非空、长度受限值；同次同时设置的新 scope/type 作为显式组合；单项更新仍校验兼容 | AI | 待观察 |
| 自动技术用户名影响登录 | 新账号不可识别 | 保留后端唯一字段；优先使用所属账户编号登录，响应和审计仍保留技术标识 | AI | 待观察 |
| 直接订单明细查询扩大数据范围 | 越权读取门店数据 | 后端强制 `scope_store_ids`，分别测试全局、指定门店和空范围 | AI | 待观察 |
| 本地缺少 Docker | 无法本地验证镜像 | GitHub Actions 构建四个镜像并作为发布硬闸门 | GitHub Actions | 已知 |
| 生产发布失败 | 新版本未上线 | 保留部署前 SHA，使用现有 Lighthouse 工作流和回滚机制 | AI | 待观察 |

## 7. AI 执行示例

1. 从看板选择唯一进行中的 Task。
2. 打开子计划，先运行指定失败测试。
3. 修改核心文件并执行目标测试，记录 Evidence。
4. 同步三份计划状态，再进入下一 Task。
5. 全部任务完成后执行发布闸门并回填 Linear。

## 8. PRD → 任务反向索引

| PRD / Requirement | Task | 子开发计划 |
|---|---|---|
| Linear DYDATA-71 最新描述与 2026-08-20 评论 | T1.1 | [T1.1](sub-delivery-plan-dydata-71-72-75-production-fixes-T1.1-admin-ui.md) |
| Linear DYDATA-72 §4-6 与 2026-08-20 自定义值反馈 | T1.2 | [T1.2](sub-delivery-plan-dydata-71-72-75-production-fixes-T1.2-product-types.md) |
| Linear DYDATA-75 与订单费用明细 PRD | T1.3 | [T1.3](sub-delivery-plan-dydata-71-72-75-production-fixes-T1.3-order-details-release.md) |
