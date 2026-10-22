# DYDATA-105 B：结算与财务按钮证据

本台账记录真实界面已执行的动作及明确缺口。只要未测条目尚存，就不能称为全部按钮验收通过。

## 执行环境与证据

- 基线：`463de801841fdf319e01c4a60b1f57bd59c87c0b`，本次测试源码SHA-256见JSON。
- 本地真实 FastAPI + Vite + Chromium + 可丢弃SQLite；认证为显式合成覆盖。不是生产登录或真实PostgreSQL验收。
- 新写入模块使用module级独立服务与数据库，避免污染其他session夹具。
- 全部文件、金额和数据库值均为合成前置；未使用生产数据、未部署。

| 报告 | 用例 | 失败 | 跳过 |
|---|---:|---:|---:|
| `output/dydata105-finance-final-browser.xml` | 58 | 0 | 0 |
| `output/dydata105-finance-visual.xml` | 14 | 0 | 0 |

## 按钮台账

同一个参数化用例分别验证四类导入或两个费用方向；每个动作的角色、数据、预期、实际、报告与源码散列见同目录JSON。条目按页面与动作拆分，包含共享控件复用，不是独立实体按钮数量或全部按钮覆盖率。

| ID | 页面 | 实际动作 | 结果 | 预期与已核对事实 |
|---|---|---|---|---|
| B105-001 | `/ranking` | 搜索门店 | PASS | 61行分页末页61-61及跳转；月度/累计及产品筛选得到授权合成店；下钻带storeId/month |
| B105-002 | `/ranking` | 排行依据 | PASS | 61行分页末页61-61及跳转；月度/累计及产品筛选得到授权合成店；下钻带storeId/month |
| B105-003 | `/ranking` | 统计方式 | PASS | 61行分页末页61-61及跳转；月度/累计及产品筛选得到授权合成店；下钻带storeId/month |
| B105-004 | `/ranking` | 产品范围 | PASS | 61行分页末页61-61及跳转；月度/累计及产品筛选得到授权合成店；下钻带storeId/month |
| B105-005 | `/ranking` | 账期 | PASS | 61行分页末页61-61及跳转；月度/累计及产品筛选得到授权合成店；下钻带storeId/month |
| B105-006 | `/ranking` | 首页 | PASS | 61行分页末页61-61及跳转；月度/累计及产品筛选得到授权合成店；下钻带storeId/month |
| B105-007 | `/ranking` | 上一页 | PASS | 61行分页末页61-61及跳转；月度/累计及产品筛选得到授权合成店；下钻带storeId/month |
| B105-008 | `/ranking` | 下一页 | PASS | 61行分页末页61-61及跳转；月度/累计及产品筛选得到授权合成店；下钻带storeId/month |
| B105-009 | `/ranking` | 末页 | PASS | 61行分页末页61-61及跳转；月度/累计及产品筛选得到授权合成店；下钻带storeId/month |
| B105-010 | `/ranking` | 输入页码/跳转 | PASS | 61行分页末页61-61及跳转；月度/累计及产品筛选得到授权合成店；下钻带storeId/month |
| B105-011 | `/ranking` | 门店行下钻 | PASS | 61行分页末页61-61及跳转；月度/累计及产品筛选得到授权合成店；下钻带storeId/month |
| B105-012 | `/settlement` | 账期 | PASS | 实际选择账期及杭州/深圳门店，回显一致 |
| B105-013 | `/settlement` | 门店 | PASS | 实际选择账期及杭州/深圳门店，回显一致 |
| B105-014 | `/settlement` | 确认推广服务费 | PASS | 取消后0确认/0异议；确认回读12345/6789分；开票上下文正确 |
| B105-015 | `/settlement` | 确认管理服务费 | PASS | 取消后0确认/0异议；确认回读12345/6789分；开票上下文正确 |
| B105-016 | `/settlement` | 返回查看 | PASS | 取消后0确认/0异议；确认回读12345/6789分；开票上下文正确 |
| B105-017 | `/settlement` | 确认提交 | PASS | 取消后0确认/0异议；确认回读12345/6789分；开票上下文正确 |
| B105-018 | `/settlement` | 推广费明细 | PASS | 取消后0确认/0异议；确认回读12345/6789分；开票上下文正确 |
| B105-019 | `/settlement` | 管理费明细 | PASS | 取消后0确认/0异议；确认回读12345/6789分；开票上下文正确 |
| B105-020 | `/settlement` | 发起账单异议 | PASS | 取消后0确认/0异议；确认回读12345/6789分；开票上下文正确 |
| B105-021 | `/settlement` | 确认发起 | PASS | 取消后0确认/0异议；确认回读12345/6789分；开票上下文正确 |
| B105-022 | `/settlement` | 取消 | PASS | 取消后0确认/0异议；确认回读12345/6789分；开票上下文正确 |
| B105-023 | `/settlement` | 进入推广费开票 | PASS | 取消后0确认/0异议；确认回读12345/6789分；开票上下文正确 |
| B105-024 | `/settlement` | 提交异议并开始检测 | PASS | 只有确认发起后出现表单；正式POST及异步检测结果回读 |
| B105-025 | `/settlement` | 版本冲突恢复 | PASS | 409后关闭旧提交窗口并刷新当前版本 |
| B105-026 | `/details` | 推广服务费 | PASS | 空筛选禁用导出；两个费用方向CSV各1行，净额128641/32000分 |
| B105-027 | `/details` | 管理服务费 | PASS | 空筛选禁用导出；两个费用方向CSV各1行，净额128641/32000分 |
| B105-028 | `/details` | 搜索 | PASS | 空筛选禁用导出；两个费用方向CSV各1行，净额128641/32000分 |
| B105-029 | `/details` | 导出 | PASS | 空筛选禁用导出；两个费用方向CSV各1行，净额128641/32000分 |
| B105-030 | `/details` | 直接URL授权范围 | PASS | 授权店真实CSV成功；越权店拒绝且不泄露行 |
| B105-031 | `/details` | 来源URL授权范围 | PASS | 授权店真实CSV成功；越权店拒绝且不泄露行 |
| B105-032 | `/settlement/invoice` | 一键复制全部开票信息 | PASS | 剪贴板购买方正确；空表单校验；登记及替换均12345分；旧分配失效 |
| B105-033 | `/settlement/invoice` | 核验并登记发票 | PASS | 剪贴板购买方正确；空表单校验；登记及替换均12345分；旧分配失效 |
| B105-034 | `/settlement/invoice` | 重新加载释放账期 | PASS | 剪贴板购买方正确；空表单校验；登记及替换均12345分；旧分配失效 |
| B105-035 | `/settlement/invoice` | 恢复替换 | PASS | 已终止历史可恢复且替换后刷新链 |
| B105-036 | `/settlement/invoice` | 重新加载释放账期 | PASS | 已终止历史可恢复且替换后刷新链 |
| B105-037 | `/settlement/invoice` | 422保留输入和重试 | PASS | 422保留输入；再次成功回显 |
| B105-038 | `/settlement/invoice/status` | 服务端精确查询 | PASS | 短号码校验；20位精确查询；原生取消0事件；实际红冲/作废各1事件；重开保留历史 |
| B105-039 | `/settlement/invoice/status` | 查看详情 | PASS | 短号码校验；20位精确查询；原生取消0事件；实际红冲/作废各1事件；重开保留历史 |
| B105-040 | `/settlement/invoice/status` | 登记红冲 | PASS | 短号码校验；20位精确查询；原生取消0事件；实际红冲/作废各1事件；重开保留历史 |
| B105-041 | `/settlement/invoice/status` | 登记作废 | PASS | 短号码校验；20位精确查询；原生取消0事件；实际红冲/作废各1事件；重开保留历史 |
| B105-042 | `/finance/promotion` | 下载推广服务费厂家导入模板 | PASS | 下载实际UTF8 BOM CSV，模板正式列；导出行/列及金额分与真实API一致 |
| B105-043 | `/finance/promotion` | 导出当前筛选结果 | PASS | 下载实际UTF8 BOM CSV，模板正式列；导出行/列及金额分与真实API一致 |
| B105-044 | `/finance/promotion` | 导入推广服务费厂家信息 | PASS | 真实CSV预览、正式写入/金额回读、同key无新增审计、NO_CHANGE不可提交、撤销保留历史 |
| B105-045 | `/finance/promotion` | 上传并预览 | PASS | 真实CSV预览、正式写入/金额回读、同key无新增审计、NO_CHANGE不可提交、撤销保留历史 |
| B105-046 | `/finance/promotion` | 确认提交 | PASS | 真实CSV预览、正式写入/金额回读、同key无新增审计、NO_CHANGE不可提交、撤销保留历史 |
| B105-047 | `/finance/promotion` | 查看导入记录 | PASS | 真实CSV预览、正式写入/金额回读、同key无新增审计、NO_CHANGE不可提交、撤销保留历史 |
| B105-048 | `/finance/promotion` | XLSX上传并预览 | PASS | 实际xlsx1行零错误；收起后批次未commit，业务表数量不变 |
| B105-049 | `/finance/promotion` | 放弃预览（收起导入面板） | PASS | 实际xlsx1行零错误；收起后批次未commit，业务表数量不变 |
| B105-050 | `/finance/promotion` | 下载全部错误 | PASS | 61非法行全部错误可下载，错误数量与批次一致；正式表零写入 |
| B105-051 | `/finance/promotion` | 非法批次禁用提交 | PASS | 61非法行全部错误可下载，错误数量与批次一致；正式表零写入 |
| B105-052 | `/finance/promotion` | 搜索 | PASS | 61店筛选、单月累计、状态空集及恢复、跨页搜索复位；CSV完整61行及金额分 |
| B105-053 | `/finance/promotion` | 筛选账期 | PASS | 61店筛选、单月累计、状态空集及恢复、跨页搜索复位；CSV完整61行及金额分 |
| B105-054 | `/finance/promotion` | 指标口径 | PASS | 61店筛选、单月累计、状态空集及恢复、跨页搜索复位；CSV完整61行及金额分 |
| B105-055 | `/finance/promotion` | 发票审核状态 | PASS | 61店筛选、单月累计、状态空集及恢复、跨页搜索复位；CSV完整61行及金额分 |
| B105-056 | `/finance/promotion` | 首页 | PASS | 61行50/20分页、末页51-61及61-61；筛选回1页；导出全部61 |
| B105-057 | `/finance/promotion` | 上一页 | PASS | 61行50/20分页、末页51-61及61-61；筛选回1页；导出全部61 |
| B105-058 | `/finance/promotion` | 下一页 | PASS | 61行50/20分页、末页51-61及61-61；筛选回1页；导出全部61 |
| B105-059 | `/finance/promotion` | 末页 | PASS | 61行50/20分页、末页51-61及61-61；筛选回1页；导出全部61 |
| B105-060 | `/finance/promotion` | 输入页码/跳转 | PASS | 61行50/20分页、末页51-61及61-61；筛选回1页；导出全部61 |
| B105-061 | `/finance/promotion` | 每页20/50 | PASS | 61行50/20分页、末页51-61及61-61；筛选回1页；导出全部61 |
| B105-062 | `/finance/promotion` | 重置筛选 | PASS | 清空搜索并复位页码，恢复冻结月后61行 |
| B105-063 | `/finance/orders/promotion` | 搜索 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-064 | `/finance/orders/promotion` | 筛选账期 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-065 | `/finance/orders/promotion` | 销售渠道 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-066 | `/finance/orders/promotion` | 核销开始日期 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-067 | `/finance/orders/promotion` | 核销结束日期 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-068 | `/finance/orders/promotion` | 发票提交开始日期 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-069 | `/finance/orders/promotion` | 发票提交结束日期 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-070 | `/finance/orders/promotion` | 应用筛选 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-071 | `/finance/orders/promotion` | 重置筛选 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-072 | `/finance/orders/promotion` | 查看完整字段 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-073 | `/finance/orders/promotion` | 关闭 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-074 | `/finance/orders/promotion` | 导出全部命中结果 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-075 | `/finance/orders/promotion` | 下一页 | PASS | 61合成行页大小变化回1页，方向固定，下载完整61行且整数分合计正确 |
| B105-076 | `/finance/orders/promotion` | 每页20 | PASS | 61合成行页大小变化回1页，方向固定，下载完整61行且整数分合计正确 |
| B105-077 | `/finance/orders/promotion` | 每页50 | PASS | 61合成行页大小变化回1页，方向固定，下载完整61行且整数分合计正确 |
| B105-078 | `/finance/orders/promotion` | 每页100 | PASS | 61合成行页大小变化回1页，方向固定，下载完整61行且整数分合计正确 |
| B105-079 | `/finance/orders/promotion` | 每页200 | PASS | 61合成行页大小变化回1页，方向固定，下载完整61行且整数分合计正确 |
| B105-080 | `/finance/orders/promotion` | 每页500 | PASS | 61合成行页大小变化回1页，方向固定，下载完整61行且整数分合计正确 |
| B105-081 | `/finance/orders/promotion` | 61行全结果导出 | PASS | 61合成行页大小变化回1页，方向固定，下载完整61行且整数分合计正确 |
| B105-082 | `/finance/management` | 下载管理服务费厂家导入模板 | PASS | 下载实际UTF8 BOM CSV，模板正式列；导出行/列及金额分与真实API一致 |
| B105-083 | `/finance/management` | 导出当前筛选结果 | PASS | 下载实际UTF8 BOM CSV，模板正式列；导出行/列及金额分与真实API一致 |
| B105-084 | `/finance/management` | 导入管理服务费厂家信息 | PASS | 真实CSV预览、正式写入/金额回读、同key无新增审计、NO_CHANGE不可提交、撤销保留历史 |
| B105-085 | `/finance/management` | 上传并预览 | PASS | 真实CSV预览、正式写入/金额回读、同key无新增审计、NO_CHANGE不可提交、撤销保留历史 |
| B105-086 | `/finance/management` | 确认提交 | PASS | 真实CSV预览、正式写入/金额回读、同key无新增审计、NO_CHANGE不可提交、撤销保留历史 |
| B105-087 | `/finance/management` | 查看导入记录 | PASS | 真实CSV预览、正式写入/金额回读、同key无新增审计、NO_CHANGE不可提交、撤销保留历史 |
| B105-088 | `/finance/management` | XLSX上传并预览 | PASS | 实际xlsx1行零错误；收起后批次未commit，业务表数量不变 |
| B105-089 | `/finance/management` | 放弃预览（收起导入面板） | PASS | 实际xlsx1行零错误；收起后批次未commit，业务表数量不变 |
| B105-090 | `/finance/management` | 下载全部错误 | PASS | 61非法行全部错误可下载，错误数量与批次一致；正式表零写入 |
| B105-091 | `/finance/management` | 非法批次禁用提交 | PASS | 61非法行全部错误可下载，错误数量与批次一致；正式表零写入 |
| B105-092 | `/finance/management` | 搜索 | PASS | 61店筛选、单月累计、状态空集及恢复、跨页搜索复位；CSV完整61行及金额分 |
| B105-093 | `/finance/management` | 筛选账期 | PASS | 61店筛选、单月累计、状态空集及恢复、跨页搜索复位；CSV完整61行及金额分 |
| B105-094 | `/finance/management` | 指标口径 | PASS | 61店筛选、单月累计、状态空集及恢复、跨页搜索复位；CSV完整61行及金额分 |
| B105-095 | `/finance/management` | 开票状态 | PASS | 61店筛选、单月累计、状态空集及恢复、跨页搜索复位；CSV完整61行及金额分 |
| B105-096 | `/finance/management` | 首页 | PASS | 61行50/20分页、末页51-61及61-61；筛选回1页；导出全部61 |
| B105-097 | `/finance/management` | 上一页 | PASS | 61行50/20分页、末页51-61及61-61；筛选回1页；导出全部61 |
| B105-098 | `/finance/management` | 下一页 | PASS | 61行50/20分页、末页51-61及61-61；筛选回1页；导出全部61 |
| B105-099 | `/finance/management` | 末页 | PASS | 61行50/20分页、末页51-61及61-61；筛选回1页；导出全部61 |
| B105-100 | `/finance/management` | 输入页码/跳转 | PASS | 61行50/20分页、末页51-61及61-61；筛选回1页；导出全部61 |
| B105-101 | `/finance/management` | 每页20/50 | PASS | 61行50/20分页、末页51-61及61-61；筛选回1页；导出全部61 |
| B105-102 | `/finance/management` | 重置筛选 | PASS | 清空搜索并复位页码，恢复冻结月后61行 |
| B105-103 | `/finance/orders/management` | 搜索 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-104 | `/finance/orders/management` | 筛选账期 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-105 | `/finance/orders/management` | 销售渠道 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-106 | `/finance/orders/management` | 核销开始日期 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-107 | `/finance/orders/management` | 核销结束日期 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-108 | `/finance/orders/management` | 发票提交开始日期 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-109 | `/finance/orders/management` | 发票提交结束日期 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-110 | `/finance/orders/management` | 应用筛选 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-111 | `/finance/orders/management` | 重置筛选 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-112 | `/finance/orders/management` | 查看完整字段 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-113 | `/finance/orders/management` | 关闭 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-114 | `/finance/orders/management` | 导出全部命中结果 | PASS | 真实列表及空CSV；详情订单正确；完整筛选含北京时间到UTC边界；方向金额128641/32000分 |
| B105-115 | `/finance/orders/management` | 下一页 | PASS | 61合成行页大小变化回1页，方向固定，下载完整61行且整数分合计正确 |
| B105-116 | `/finance/orders/management` | 每页20 | PASS | 61合成行页大小变化回1页，方向固定，下载完整61行且整数分合计正确 |
| B105-117 | `/finance/orders/management` | 每页50 | PASS | 61合成行页大小变化回1页，方向固定，下载完整61行且整数分合计正确 |
| B105-118 | `/finance/orders/management` | 每页100 | PASS | 61合成行页大小变化回1页，方向固定，下载完整61行且整数分合计正确 |
| B105-119 | `/finance/orders/management` | 每页200 | PASS | 61合成行页大小变化回1页，方向固定，下载完整61行且整数分合计正确 |
| B105-120 | `/finance/orders/management` | 每页500 | PASS | 61合成行页大小变化回1页，方向固定，下载完整61行且整数分合计正确 |
| B105-121 | `/finance/orders/management` | 61行全结果导出 | PASS | 61合成行页大小变化回1页，方向固定，下载完整61行且整数分合计正确 |
| B105-122 | `/finance/management` | 查看历史版本 | PASS | 切换历史开关复位页码并保留筛选 |
| B105-123 | `/finance/management` | 仅看当前版本 | PASS | 切换历史开关复位页码并保留筛选 |
| B105-124 | `/finance/management` | 更正（桌面行Enter） | PASS | 实时读320000分，修改20位票号，正式新版本保留历史及相同金额 |
| B105-125 | `/finance/management` | 读取当前记录 | PASS | 实时读320000分，修改20位票号，正式新版本保留历史及相同金额 |
| B105-126 | `/finance/management` | 确认更正 | PASS | 实时读320000分，修改20位票号，正式新版本保留历史及相同金额 |
| B105-127 | `/finance/management` | 关闭 | PASS | 实时读320000分，修改20位票号，正式新版本保留历史及相同金额 |
| B105-128 | `/finance/stores` | 基础信息 | PASS | 61门店基础/SAP列表全可达，筛选/页签回1页，下载完整61店 |
| B105-129 | `/finance/stores` | SAP异议处理 | PASS | 61门店基础/SAP列表全可达，筛选/页签回1页，下载完整61店 |
| B105-130 | `/finance/stores` | 搜索门店 | PASS | 61门店基础/SAP列表全可达，筛选/页签回1页，下载完整61店 |
| B105-131 | `/finance/stores` | 账期 | PASS | 61门店基础/SAP列表全可达，筛选/页签回1页，下载完整61店 |
| B105-132 | `/finance/stores` | 费用方向 | PASS | 61门店基础/SAP列表全可达，筛选/页签回1页，下载完整61店 |
| B105-133 | `/finance/stores` | 指标口径 | PASS | 61门店基础/SAP列表全可达，筛选/页签回1页，下载完整61店 |
| B105-134 | `/finance/stores` | 首页 | PASS | 61门店基础/SAP列表全可达，筛选/页签回1页，下载完整61店 |
| B105-135 | `/finance/stores` | 上一页 | PASS | 61门店基础/SAP列表全可达，筛选/页签回1页，下载完整61店 |
| B105-136 | `/finance/stores` | 下一页 | PASS | 61门店基础/SAP列表全可达，筛选/页签回1页，下载完整61店 |
| B105-137 | `/finance/stores` | 末页 | PASS | 61门店基础/SAP列表全可达，筛选/页签回1页，下载完整61店 |
| B105-138 | `/finance/stores` | 输入页码/跳转 | PASS | 61门店基础/SAP列表全可达，筛选/页签回1页，下载完整61店 |
| B105-139 | `/finance/stores` | 每页20/50 | PASS | 61门店基础/SAP列表全可达，筛选/页签回1页，下载完整61店 |
| B105-140 | `/finance/stores` | 下载基础信息导入模板 | PASS | 实际CSV列、编码、基础/SAP行值与API一致 |
| B105-141 | `/finance/stores` | 导出门店基础信息 | PASS | 实际CSV列、编码、基础/SAP行值与API一致 |
| B105-142 | `/finance/stores` | 下载 SAP 编码确认模板 | PASS | 实际CSV列、编码、基础/SAP行值与API一致 |
| B105-143 | `/finance/stores` | 导出 SAP 编码差异清单 | PASS | 实际CSV列、编码、基础/SAP行值与API一致 |
| B105-144 | `/finance/stores` | 导入门店基础信息 | PASS | 真实导入SAP1050001/2，当前版本回读，重复幂等/NO_CHANGE/撤销保留历史 |
| B105-145 | `/finance/stores` | 导入最终确认 SAP 编码 | PASS | 真实导入SAP1050001/2，当前版本回读，重复幂等/NO_CHANGE/撤销保留历史 |
| B105-146 | `/finance/stores` | 上传并预览 | PASS | 真实导入SAP1050001/2，当前版本回读，重复幂等/NO_CHANGE/撤销保留历史 |
| B105-147 | `/finance/stores` | 确认提交 | PASS | 真实导入SAP1050001/2，当前版本回读，重复幂等/NO_CHANGE/撤销保留历史 |
| B105-148 | `/finance/stores` | 查看导入记录 | PASS | 真实导入SAP1050001/2，当前版本回读，重复幂等/NO_CHANGE/撤销保留历史 |
| B105-149 | `/finance/stores` | XLSX上传并预览 | PASS | 基础/SAP的xlsx预览不提交正式事实 |
| B105-150 | `/finance/stores` | 放弃预览（收起导入面板） | PASS | 基础/SAP的xlsx预览不提交正式事实 |
| B105-151 | `/finance/stores` | 查看详情 | PASS | 关闭不增加版本；确认后SYNTHETIC105成为当前值且仅增加1版本 |
| B105-152 | `/finance/stores` | 关闭 | PASS | 关闭不增加版本；确认后SYNTHETIC105成为当前值且仅增加1版本 |
| B105-153 | `/finance/stores` | 确认矫正并生成新版本 | PASS | 关闭不增加版本；确认后SYNTHETIC105成为当前值且仅增加1版本 |
| B105-154 | `/finance/disputes` | 账期 | PASS | 61异议分页、搜索/方向/状态复位；CSV61行，争议金额sum(101+i)分 |
| B105-155 | `/finance/disputes` | 门店 ID | PASS | 61异议分页、搜索/方向/状态复位；CSV61行，争议金额sum(101+i)分 |
| B105-156 | `/finance/disputes` | 费用方向 | PASS | 61异议分页、搜索/方向/状态复位；CSV61行，争议金额sum(101+i)分 |
| B105-157 | `/finance/disputes` | 处理状态 | PASS | 61异议分页、搜索/方向/状态复位；CSV61行，争议金额sum(101+i)分 |
| B105-158 | `/finance/disputes` | 首页 | PASS | 61异议分页、搜索/方向/状态复位；CSV61行，争议金额sum(101+i)分 |
| B105-159 | `/finance/disputes` | 上一页 | PASS | 61异议分页、搜索/方向/状态复位；CSV61行，争议金额sum(101+i)分 |
| B105-160 | `/finance/disputes` | 下一页 | PASS | 61异议分页、搜索/方向/状态复位；CSV61行，争议金额sum(101+i)分 |
| B105-161 | `/finance/disputes` | 末页 | PASS | 61异议分页、搜索/方向/状态复位；CSV61行，争议金额sum(101+i)分 |
| B105-162 | `/finance/disputes` | 输入页码/跳转 | PASS | 61异议分页、搜索/方向/状态复位；CSV61行，争议金额sum(101+i)分 |
| B105-163 | `/finance/disputes` | 每页20/50 | PASS | 61异议分页、搜索/方向/状态复位；CSV61行，争议金额sum(101+i)分 |
| B105-164 | `/finance/disputes` | 导出账单异议 | PASS | 61异议分页、搜索/方向/状态复位；CSV61行，争议金额sum(101+i)分 |
| B105-165 | `/finance/disputes` | 处理 | PASS | 关闭后重新打开；异步检测完成；不成立提交后DB status=5、说明一致且刷新可见 |
| B105-166 | `/finance/disputes` | 关闭 | PASS | 关闭后重新打开；异步检测完成；不成立提交后DB status=5、说明一致且刷新可见 |
| B105-167 | `/finance/disputes` | 启动系统检测 | PASS | 关闭后重新打开；异步检测完成；不成立提交后DB status=5、说明一致且刷新可见 |
| B105-168 | `/finance/disputes` | 重新检测 | PASS | 关闭后重新打开；异步检测完成；不成立提交后DB status=5、说明一致且刷新可见 |
| B105-169 | `/finance/disputes` | 处理结果 | PASS | 关闭后重新打开；异步检测完成；不成立提交后DB status=5、说明一致且刷新可见 |
| B105-170 | `/finance/disputes` | 处理说明 | PASS | 关闭后重新打开；异步检测完成；不成立提交后DB status=5、说明一致且刷新可见 |
| B105-171 | `/finance/disputes` | 确认处理 | PASS | 关闭后重新打开；异步检测完成；不成立提交后DB status=5、说明一致且刷新可见 |
| B105-172 | `/finance/imports` | 批次编号/详情 | PASS | 四类型可查历史，撤销生成关联批次、原当前事实失效、撤销审计仅1条 |
| B105-173 | `/finance/imports` | 撤销原因 | PASS | 四类型可查历史，撤销生成关联批次、原当前事实失效、撤销审计仅1条 |
| B105-174 | `/finance/imports` | 撤销批次 | PASS | 四类型可查历史，撤销生成关联批次、原当前事实失效、撤销审计仅1条 |
| B105-175 | `/finance/imports` | 逐业务键撤销覆盖链 | PASS | 四类型可查历史，撤销生成关联批次、原当前事实失效、撤销审计仅1条 |
| B105-176 | `/finance/imports` | 下载全部错误 | PASS | 61非法行错误跨页可达及全文件，关闭详情后零业务写入 |
| B105-177 | `/finance/imports` | 错误末页 | PASS | 61非法行错误跨页可达及全文件，关闭详情后零业务写入 |
| B105-178 | `/finance/imports` | 错误上一页 | PASS | 61非法行错误跨页可达及全文件，关闭详情后零业务写入 |
| B105-179 | `/finance/imports` | 错误首页 | PASS | 61非法行错误跨页可达及全文件，关闭详情后零业务写入 |
| B105-180 | `/finance/imports` | 关闭 | PASS | 61非法行错误跨页可达及全文件，关闭详情后零业务写入 |
| B105-181 | `/finance/imports` | 同路径查询导航 | PASS | 改变URL类型/月后旧批次详情与局部状态清除 |
| B105-182 | `/finance/*` | 门店角色直达拒绝 | PASS | 受限管理员CSV仅store-1；过期会话真实401且按钮消失 |
| B105-183 | `/finance/*` | 管理员受限店导出 | PASS | 受限管理员CSV仅store-1；过期会话真实401且按钮消失 |
| B105-184 | `/finance/*` | 会话失效 | PASS | 受限管理员CSV仅store-1；过期会话真实401且按钮消失 |
| B105-185 | `/finance/*` | 零数据导出 | PASS | 遵循正式空导出合同，下载只有表头的真实CSV，不能混同失败 |
| B105-186 | `/finance/*` | 零数据下载反馈 | PASS | 空文件成功后明确提示当前筛选无记录 |
| B105-187 | `/finance/disputes` | 详情打开后的下载成功反馈 | PASS | 打开详情后实际下载仍有用户可见成功反馈 |
| B105-188 | `/finance/disputes` | 下载失败反馈 | PASS | 失败使用alert角色且无伪成功 |
| B105-189 | `/finance/imports` | 错误文件下载失败反馈 | PASS | 错误下载失败可见且不伪报成功 |

## 尚未覆盖的实际控件

以下不是通过项，主线程必须补证后才可最终接受全部按钮。

| 页面 | 控件 | 原因 |
|---|---|---|
| `/details` | 销售月份/核销月份/数据状态/分页 | Direct/source URL and direction/export verified; full immediate-filter and >1-page matrix remains uncovered. |
| `/details` | 后续调整展开/上下文失效时返回单店分账 | Seeded rows have no follow-up adjustments; these conditional controls were not exercised in this new acceptance. |
| `/settlement/invoice/status` | 分页/重新开票 | Real red-flush/void replacement verified; pagination and separate resume button have only existing mock-contract coverage. |
| `/finance/orders/*` | 发票审核状态/结算状态 | Other complete filter/date fields verified; selectors not explicitly exercised by new browser tests. |
| `/finance/orders/*` | 字段来源与计算说明展开 | Source disclosure summary exists; its expand/collapse action was not exercised in this new acceptance. |
| `/finance/management` | 窄屏卡片的更正按钮 | The real current-version correction handler is verified through the desktop row keyboard action; this distinct narrow-screen button has not been clicked in the new acceptance. |
| `/finance/imports` | 导入类型/业务账期/批次列表分页/撤销行页大小与分页/错误页大小与跳转 | Real batch histories/errors/reversal verified; exhaustive list and nested pagination controls remain uncovered. |

## 当前源码不存在的提案动作

这些条目不计入实际按钮通过数。

| 页面 | 计划动作 | 源码事实 |
|---|---|---|
| `/ranking` | 重置/下载 | StoreRankingPage renders no reset or download control. |
| `/settlement` | 历史版本选择/下载/费用行下钻 | StoreSettlementPage has no version picker, export control or rowHref; /details is tested directly with source URL. |
| `/details` | 查询/重置/页大小/详情 | OrderDetailsPage uses immediate filters, fixed page size and read-only rows; no corresponding controls. |
| `/settlement/invoice` | 取消按钮 | No standalone cancel control; terminating native lifecycle prompts and abandoning imports are tested where present. |
| `/settlement/invoice/status` | 下载/状态筛选 | Current page exposes invoice-number exact search; no download or status selector. |

## 截图与集成证据

合成截图位于 `pwScreenShot/dydata105/`；文件散列见JSON。截图辅助审阅，结果以CSV内容/金额分及提交后数据库回读断言为准。

别名、真实Nginx及真实PG结果由主线程汇总到 [最终集成验证](dydata-105-verification.md)；B不将其他切片报告推断为本切片独立通过。

## 命令

```powershell
python -m pytest tests/test_dydata105_buttons_browser.py tests/test_dydata105_finance_pagination_browser.py tests/test_finance_export_browser.py -q --tb=short --junitxml=output/dydata105-finance-final-browser.xml
python -m pytest tests/test_visual_smoke.py -q --tb=short -k 'settlement_version_conflict or settlement_does_not_offer_stale or store_invoice_preserves_422 or store_invoice_recovers_terminated or single_sap_correction or dydata_81_dispute_detection or dydata_81_store_dispute_entry or finance_pages_use_live_fastapi or finance_sibling_navigation or imports_same_path_navigation or finance_import_clears_stale' --junitxml=output/dydata105-finance-visual.xml
git diff --check
```

报告与截图是本地运行证据；主线程还须汇总自身API、真实PG、真实Nginx与最终全仓运行结果，不复用历史通过数量。
本任务无 foundation 漂移：测试按当前正式接口与页面实际控件修正前置和定位，未改变API、Schema或费用口径。
