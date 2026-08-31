# DYDATA-81 门店端财务页面开发记录

## 范围

- 仅实现订单分佣下的全国门店榜单、单店分账、开票确认和新增发票状态查看。
- 未修改 `/finance/*` 页面、API、财务端导航数组或财务端受保护测试；按用户 2026-08-28 验收反馈，仅删除门店结算导航中的“SAP 建议”及门店角色对 `/finance/stores` 的访问例外，财务/管理员入口保持不变。
- 未执行数据库迁移或生产部署。

## 实现

- 新增共享七步月度结算时间轴，三页按账单确认、发票提交、厂家审核阶段显示当前环节。
- 单店分账新增推广/管理方向卡、原始/调整/确认净额与可展开的真实订单费用明细；确认仍使用既有账单版本、幂等键和 409 刷新逻辑；无可用异议能力时使用业务空态，不在正式页面展示开发 Issue 编号。
- 开票确认按原临时看板的结构补齐左右双栏核验工作区：购买方完整开票信息、一键复制、数电专票表单、门店手工填写不含税金额/税额/开票金额、七项前端核验及全宽提交动作；页面视觉使用正式系统 token。登记仍只向真实接口提交契约内字段，并保留既有红冲/作废替换闭环。
- 按 2026-08-28 用户最新确认，开票账期由系统自动确定：一次选中该门店全部当前可开票且未开票的完整账期并合并开一张票；门店只读查看，不可选择、切换、添加或移除账期。抵扣组及组内必含账期继续完全使用服务端投影，不在浏览器重算财务规则。
- 共享时间轴的“当前环节”状态条改用品牌橙高亮背景、边框与文字，在单店分账、开票确认、发票状态查看三页保持一致。
- 新增 `/settlement/invoice/status`，使用 B02 权限和真实发票列表/详情接口，提供账期、门店、号码、状态筛选及厂家状态、结算归属和账期分配详情。
- 按 2026-08-28 逐页验收反馈，全国门店榜单保留 4 张紧凑指标卡：销售金额、核销金额、当期推广服务费、累计推广服务费；单店分账保留上述 4 张并增加当期管理服务费、累计管理服务费，共 6 张。删除“结算参考净额”卡片；桌面同排展示，窄屏保持单行并在卡片容器内横向查看。
- 后端尚未提供驳回原因和税额拆分持久化字段；开票确认仅校验门店手工填写的金额勾稽，不向接口伪造字段；缺失原因显示业务空态，不在正式页面展示开发 Issue 编号。

## 验证

- `python -m pytest tests/test_frontend_store_finance_pages.py -q`：6 通过。
- `python -m pytest tests/test_frontend_store_settlement_confirmation.py tests/test_frontend_store_finance_pages.py -q`：9 通过。
- `python -m pytest tests/test_frontend_user_facing_contracts.py -q`：14 通过。
- 既有开票视觉交互回归：2 通过。
- `python -m pytest tests/test_design_system_enforcement.py -q`：23 通过。
- `python -m pytest tests/test_visual_store_finance_pages.py -q`：10 通过，覆盖三页 390/768/1440、无横向溢出、订单明细展开和发票详情读取。
- `npm --prefix apps/web run build`：通过。
- 用户反馈后新增门店 SAP 隔离契约；`tests/test_frontend_store_finance_pages.py` 7 项通过，桌面二级导航 5 项可见性回归通过。
- `python -m pytest tests/test_visual_store_finance_pages.py -q`：10 项通过并重新生成 9 张截图；门店端二级导航不再出现“SAP 建议”。
- 指标卡反馈完成后：`tests/test_frontend_store_finance_pages.py` 8 项通过；`tests/test_visual_store_finance_pages.py` 16 项通过；既有榜单接口与桌面导航回归 2 项通过；Web build 通过。
- 开票核验补齐后：门店财务/确认静态测试 13 项、用户文案契约 14 项、设计系统 23 项通过；浏览器核验交互测试通过，确认 ¥10.24 自动拆分为不含税 ¥9.66、税额 ¥0.58，七项核验通过后提交按钮可用；三档页面视觉回归其余 16 项通过。
- 最新账期规则回归：`tests/test_frontend_store_finance_pages.py` 11 项通过；`tests/test_visual_store_finance_pages.py` 19 项通过，其中明确覆盖“历史未开票时自动定位 2026-07”“历史已开时定位当前 2026-08”及账期控件禁用、无手动抵扣组按钮。
- `design-qa.md`：源参考与 1440 浏览器实现完成同次视觉对照，最终结果 `passed`。
- 截图：`pwScreenShot/dydata-81-store-finance/final/` 含三页三档宽度、指标卡及开票核验状态截图。
- 本地 4181 已从旧 DYDATA-19 Mock 切换到本工作树正式构建；根页面返回 200，`/api/v1/auth/me` 经同源代理到正式 API 并返回未登录 401，证明本地入口未使用假登录或本地角色切换。
- 使用现有已登录浏览器对 4181 做只读实页检查：开票页显示禁用的“系统确定开票账期”、自动定位说明、更新后的 1—6 日确认与 6 日 24:00 自动确认；榜单不显示管理服务费指标，单店分账同时显示当期与累计管理服务费。

## 风险与后续

- 用户逐页验收前，DYDATA-81 与本任务保持进行中。
- 全量 `python -m pytest -q` 的两次运行均被宿主执行通道中断，未取得可读完成报告；不得将其记为通过。门店端专项、浏览器回归与 Web build 已单独完成。

## 续作记录（2026-08-28）

- 开票页面移除浏览器本地日期/月度默认值，账期由正式 API 返回的最新业务账期驱动；开票日期由服务端按北京时间和账单确认/锁账边界校验。
- 购买方信息与税率改为门店逐字段手工填写并逐字段校验；金额按三位小数计算后四舍五入到分，金额勾稽允许 0.01 元容差，保留用户确认的精确错误文案。
- 发票状态页移除“待开票”筛选和本地号码模糊过滤，号码查询透传后端精确条件后再分页；审核原因未由接口回传时显示通用空态，不在页面暴露开发 Issue 编号。
- 发票金额不再按税率自动拆分；门店手工填写不含税金额、税额、价税合计，三项最多输入三位小数后四舍五入到分，仅校验“不含税金额 + 税额 = 开票金额”，允许 0.01 元容差。
- 状态页补齐服务端精确查询后的分页控件；缺失金额指标显示“暂无数据”或“尚未生成”，不再把接口缺失值渲染成真实的 `¥0.00`。
- 定向回归：`python -m pytest tests/test_frontend_store_settlement_confirmation.py tests/test_frontend_user_facing_contracts.py tests/test_frontend_store_finance_pages.py tests/test_api_store_billing.py -q`，91 项通过。
- `python -m pytest tests/test_visual_store_finance_pages.py -q -k "verification_workspace or locked_and_all_billable"`：3 项通过，覆盖三位小数四舍五入以及全部可开票账期合并选择。
- `npm --prefix apps/web run build`：通过。
- 全量 `python -m pytest` 曾因工具会话中断且残留进程未形成完整汇总；已清理残留进程，本轮不将全量测试标记为通过。
- Foundation 漂移登记：`S4-FCR-006`，待治理评审；未直接修改冻结 Foundation 正文。
