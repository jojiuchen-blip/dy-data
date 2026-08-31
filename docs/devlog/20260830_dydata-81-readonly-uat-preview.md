# DYDATA-81 门店端财务只读 UAT 预览记录

> 日期：2026-08-30
>
> 状态：已提供用户验收地址；等待逐页验收。T1.1 正式系统实施仍为待开发，DYDATA-81 未关闭。

## 范围

- 新增隔离入口 `apps/web/uat.html` 与独立 Vite 配置。
- 覆盖：全国门店榜单、单店分账（含推广费明细/管理费明细页签与账单异议入口/表单）、开票确认、发票状态查看。
- T1.2 不改正式 `App.tsx`、`Shell.tsx`、正式门店页面、真实 API、`/finance/*`、权限、导航或现有测试；工作树中这些既有脏改动保持未触碰。

## 本地访问地址

- `http://127.0.0.1:4190/uat.html#/ranking`

## 已执行验证

- 计划结构校验：2 个 Task、13 个必需章节，`passed: true`。
- 计划状态一致性：唯一进行中 Task 为 T1.2，`passed: true`。
- UAT 合同测试：`python -m pytest tests/test_frontend_dydata81_uat_preview.py -q`，当前实现覆盖四页导航、排行依据、费用明细页签、账单异议默认收起/弹层、入口/类型与字段、开票提醒/时间节奏与当前页面节点高亮，`11 passed`。
- UAT 独立构建：`vite build --config vite.uat.config.ts`，成功。
- TypeScript：`tsc --noEmit`，成功。
- 浏览器：四页在 1440、768、390 各一张；390 宽度重点核对指标卡横向轨道、表格容器滚动和开票表单单列。
- 点击链路：全国门店榜单 → 单店分账 → 开票确认 → 发票状态查看；已验证排行依据选项切换、费用明细两个页签切换、账单异议入口 → 二次确认 → 空白表单，以及开票时间节奏的“发票提交”页面节点高亮。UAT 无正式数据，复制/登记/异议提交等写入动作不提交。
- 网络：UAT 浏览器会话仅载入本地静态资源 GET；无 mutation 请求、无 `/finance/*` 请求。
- 控制台：最终页面为 0 error、0 warning。

## 截图与边界

- 截图目录：`output/playwright/dydata-81-uat/r2/`（四页 × 1440/768/390）；异议入口与表单三档截图位于 `output/playwright/dydata-81-uat/r4/`（本轮复核）。
- 无正式数据时使用“暂无数据”“尚未生成”，没有金额、账期、审核状态或确认成功的伪造值。
- 开票登记、账单确认、发票状态查询均保持不可写；UAT 不调用任何真实财务写接口。

## 账单异议规则检索与 UAT 入口

本轮检索的唯一业务依据为：

- `docs/superpowers/specs/2026-08-20-dydata-19-settlement-finance-design.md` §6.2：门店从账单或订单明细选择费用方向、账期、账单版本和争议订单；必填争议金额、异议类型、说明、联系人、手机号和证明资料；异议类型固定为费率错误、订单/数据遗漏、金额错误、其他。
- `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md` §3.1：正式请求字段为 `feeDirection`、`disputeType`、`description`、`contactName`、`contactPhone`、`disputedAmountCent`、`orders[]`、`evidence[]`、`readVersion`；提交成功状态由服务端返回 `PENDING`。
- `docs/prd/subprd/08-subprd-finance-disputes.md` §3：异议只冻结当前费用方向；结果前可撤回，结果后只能新建纠正异议；服务端负责订单归属、并发和证明对象键校验。
- 冻结临时看板 `codex/dydata-19-finance-mock@9a574fa` 的 `StoreBillsPage.jsx` 与 `App.test.jsx`：入口位于账单明细内部且不突出，点击后先二次确认，再进入异议表单。

UAT 变更仅呈现上述结构：费用明细页签下方保留小字“发起账单异议”；入口打开二次确认；确认后展示当前页签对应的费用方向、四类类型、争议金额、联系人、手机号、争议订单、问题说明和证明材料字段。因当前 UAT 没有正式账单或受控证明对象，提交按钮保持禁用，不模拟 `PENDING`、上传成功或任何状态流转。

## 后续门禁

1. 用户逐页验收 UAT 页面，重点确认四页顺序、费用明细页签、账单异议入口和开票时间节奏。
2. 仅在用户书面确认后，才新开/恢复 T1.1 正式系统实施。
3. T1.1 仍需真实 API 契约、正式门店权限、写操作授权、全量门禁与生产部署门禁；本 UAT 不能替代这些条件。
