# DYDATA-81 门店端财务只读 UAT 预览实施计划

> **范围**：仅在独立 UAT 入口实现并验证门店端四个二级页面，以及单店分账内的费用明细与账单异议模块；不改动正式 `App`、`Shell`、门店正式页面、`/finance/*`、接口、权限、导航或测试。
>
> **授权**：用户于 2026-08-30 明确回复“开始”，此前已确认按 UAT 方案制作。
>
> **目标**：让用户先验收页面结构、字段、响应式与合法空态；不产生任何真实写操作、部署或 Issue 关闭。

## 1. 冻结输入与边界

- 设计规格：[DYDATA-81 门店端财务只读 UAT 预览设计规格](../specs/2026-08-29-dydata-81-store-finance-uat-design.md)。
- 验收合同：[DYDATA-81 页面合同矩阵](../../uat/dydata-81-page-contract-matrix-2026-08-29.md)。
- 业务边界：用户最新确认、DYDATA-19 / DYDATA-31、正式 API；临时看板仅提供结构、功能和交互合同。
- 受保护边界：`/finance/*`、正式 `apps/web/src/App.tsx`、`apps/web/src/components/Shell.tsx`、现有正式页面、真实 API 和其测试均不在本 Task 修改范围。
- UAT 不保存、确认、登记、导入、审核、结算或部署；不使用历史凭据，不访问财务端路由。

## 2. 实现路径

1. 新建独立 Vite 入口 `apps/web/uat.html`，不改变正式入口 `index.html` 或正式路由。
2. 新建 `apps/web/vite.uat.config.ts`，将 UAT 入口单独编译为静态预览；正式 `vite.config.ts` 和 `package.json` 不改。
3. 在 `apps/web/src/uat/` 内实现 hash 路由、UAT Shell、四页和单店分账内嵌模块及局部样式；只导入设计 token、共享 `Button`、`TextField`、`SelectField`、`TertiaryNav` 等视觉组件，不调用正式 API。
4. UAT 所有业务值以“暂无数据”“尚未生成”“待确认”呈现，只有用户确认的购买方基准资料可静态显示；绝不出现虚构金额、账期、审核状态、测试/预览/试运行业务提示。
5. 在静态契约测试先红后绿后，执行 UAT 专项构建、浏览器三档截图、只读网络检查与受保护范围检查。

## 3. 交付文件

- 新增：`apps/web/uat.html`
- 新增：`apps/web/vite.uat.config.ts`
- 新增：`apps/web/src/uat/main.tsx`
- 新增：`apps/web/src/uat/UatPreviewApp.tsx`
- 新增：`apps/web/src/uat/uat-preview.css`
- 新增：`tests/test_frontend_dydata81_uat_preview.py`
- 新增或更新验证证据：`output/playwright/dydata-81-uat/`
- 更新：本计划、DYDATA-81 T1.2 子交付计划、任务看板与主交付计划状态。

## 4. 逐步执行与验证

### Task 1：先写 UAT 合同测试（红灯）

**Files:** `tests/test_frontend_dydata81_uat_preview.py`

1. 断言独立入口与 UAT 根组件存在。
2. 断言二级导航顺序为“全国门店榜单 → 单店分账 → 开票确认 → 发票状态查看”，且不存在独立“订单费用明细”入口。
3. 断言榜单四卡、六列和“排行依据”，单店左右确认区、两个费用明细页签、底部账单异议空态、开票提醒/时间节奏/两栏八字段、发票状态五张推广卡均存在。
4. 断言 UAT 代码不出现 `¥0.00`、固定演示账期、测试/预览/试运行业务文字，也不出现 `fetch(`、`POST`、`PUT`、`PATCH`、`DELETE` 或 `/finance/`。
5. 执行 `python -m pytest tests/test_frontend_dydata81_uat_preview.py -q`，预期先因实现文件不存在而失败。

### Task 2：实现隔离 UAT Shell 与四页结构

**Files:** `apps/web/uat.html`, `apps/web/vite.uat.config.ts`, `apps/web/src/uat/main.tsx`, `apps/web/src/uat/UatPreviewApp.tsx`, `apps/web/src/uat/uat-preview.css`

1. 用独立 hash 路由呈现四个入口，页面跳转只改变 UAT hash，不跳进正式应用。
2. 使用当前设计 token、共享表单/按钮/二级导航组件，建出系统风格的顶栏、内容容器、卡片、表格、筛选区和空态。
3. 排名页：标题、筛选占位、四张指标卡、六列空表和位于表格标题右侧的“排行依据”；不显示副标题、管理服务费、结算参考或订单笔数。
4. 单店分账：一行可横向滚动的六张指标卡，左右并列的推广服务费确认与管理服务费确认；其后嵌入推广费明细/管理费明细页签和账单异议空态。无数据不伪造金额、状态或可提交异议。
5. 开票确认：用户确认的开票提醒和规则性时间节奏之后为等高左右栏；左栏基准资料与复制动作，右栏为购买方名称、填写人电话、税率、开票日期、20 位数电专票号码、不含税金额、税额、价税合计；不放静态校验规则、账期说明框、账单表或错误条。
6. 发票状态：固定五张推广指标卡，保留推广记录、管理服务费发票信息、差额台账的无数据结构；搜索入口只描述服务端精确查询，不伪造结果。

### Task 3：回归、构建与视觉证据

**Files:** `tests/test_frontend_dydata81_uat_preview.py`, `pwScreenShot/dydata-81-store-finance/uat-preview/`

1. 再次运行 UAT 合同测试，预期转绿。
2. 执行 `npm --prefix apps/web exec vite build -- --config vite.uat.config.ts`，验证独立入口可构建，不替换正式构建产物。
3. 启动 UAT 本地服务后，用真实浏览器在 1440、768、390 宽度采集四页截图；390 重点检查卡片单行横向轨道与开票表单单列。
4. 检查浏览器网络记录：无 mutation 请求、无 `/finance/*` 请求。
5. 执行 `git diff --check`，并确认本 Task 的改动文件不匹配受保护范围。

## 5. 停止条件

- 任何实现需要改动正式页面、`Shell.tsx`、`App.tsx`、真实 API、`/finance/*` 或其测试时，立即停止并报告。
- 任一合同项需要演示金额、日期、状态或虚构确认成功时，保持合法空态并标记待后续真实 API UAT。
- 只有用户逐页认可 UAT 后，才可创建正式系统实施 Task；本计划完成不等于 DYDATA-81 完成。
