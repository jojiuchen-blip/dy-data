# 开发日志 — 2026-09-10

> 主题：DYDATA-93 管理员规则发布权限
> 操作人：jojiuchen-blip（AI 执行）
> 关联计划：[T0.1](../plans/delivery-plans/sub-delivery-plan-dydata-93-admin-rules-T0.1-permissions.md)

## 一、执行概要

| 任务 | 关联 | 状态 |
|---|---|---|
| 最小权限发布修复与回归 | DYDATA-93 / T0.1 | 本地实现，尚未发布 |

## 二、操作详情

- 目标：按用户已审阅计划允许有 D03 的普通管理员发布 SKU 分账规则，不扩大其他高风险权限。
- 操作：独立工作树基于 df33f73；三文件计划一致性、环境与上下文检查通过。真实登录红测单条和文件提交均返回403，理由为最高管理员要求；随后仅调整两处发布依赖，保留认证、页面权限、业务事务。前端按服务端 is_highest_admin 禁用手动重建，并说明发布后自动重算。
- 验证：最初2失败/3通过；最小修复后52项API与权限通过；加入失效会话、停用和匿名负例后，最终相关API/权限/前端流程67 passed，2项既有弃用警告。Web build 独立命令exit0，保留既有大包警告。git diff --check通过。
- 本任务无 Schema 漂移；现有 SKU API 顶部权限为授权后台管理员，本次与其单条/导入发布约定一致。固定手动重建/结算范围权限边界仅在账号规则补明，不在 S4 改写 foundation。
- 全局文件验证0错误/0警告，S4路由允许。链接索引刷新发现33项坏链，需区分既有基线与本次新增；不擅自修改其他线索PRD。
- 生产账号、规则、重算与发票均未改动。

## 三、变更总览

| 操作 | 文件 | 说明 |
|---|---|---|
| 修改 | apps/api/dy_api/routes/fee_admin.py | 两类发布使用管理员依赖 |
| 修改 | apps/web/src/pages/AdminSkuRulesPage.tsx | 手动重建角色提示与禁用 |
| 修改 | tests/test_api_fee_admin.py | 真实会话正负例、幂等和零写入 |
| 修改 | tests/test_frontend_admin_rules_workflow.py | 重建入口权限契约 |
| 新建/修改 | docs/plans/delivery-plans/、docs/plans/execution-plan.md | 审阅与执行状态 |
| 修改 | docs/rules/account-access-control.md | 最小权限边界 |

Git 提交记录：本增量尚未提交。

## 四、发现的问题 / 缺陷

旧发布接口固定最高管理员，造成普通管理员获页面授权后仍不能发布；已通过真实登录测试证明。

## 五、复盘

权限修复同时验证允许与拒绝，不能通过覆盖认证依赖来假造普通管理员成功。🔧 仅记录，不新增通用规则。

## 六、待跟进事项

- [ ] 独立审查结论与修正。
- [ ] 真实浏览器普通管理员发布成功/失败链路。
- [ ] 全量pytest、CI、受控部署与生产只读验收。
- [ ] DYDATA-92 同风格操作指引另行接入。

## 补充更新：浏览器验收与发布准备

- 用户要求继续推进，已启动完整 pytest，执行会话84588，报告目标 logs/dydata93-full-tests.xml。报告未完成前不作全量通过结论。
- 新增 tests/test_visual_admin_rule_permissions.py，不覆盖 get_current_user；真实HTTP登录的普通管理员浏览器发布、刷新回读、同日冲突与最高管理员专用按钮禁用通过（1 passed）。
- GET回读补强2项通过；独立审查0 Critical/0 Important，浏览器证据缺口已补。
- 治理套包122 tests通过，协议检查0错误/0警告；git diff --check通过。
- 只读核对生产最后成功部署为1e91f4dc，worker启动；当前origin/main=df33f73，与本分支基础无偏离。GitHub和SSH授权可用，不需用户重复登录。
- 未触发生产部署，未写入生产规则或财务数据；必须先等全量回归并通过PR/CI。
- 发布前发现主线/生产回退风险：git cherry证明aa3373a等DYDATA-87提交未合入origin/main，代码diff缺少完整POI分页与归属防覆盖。生产worker只读grep实际仍cursor分页；已记录DYDATA-87评论6a5dde62。发布放行暂停，需协调纳入已验证采集修复且保留线索新变更，不触碰未审阅补算driver。

## 补充更新：经用户同意整合已提交采集修复

- 用户明确同意联合验证发布。当前分支无冲突应用aa3373a（no-commit），只补入bab2612/52500ae的PG门禁与来源保护测试，不导入旧全局驾驶舱或其他工作树未提交代码。
- 四个采集运行时文件、PG及结算保护测试与52500ae内容一致；最新线索formal_allocation_runtime.py和routes/_data.py与df33f73内容一致。
- 独立只读整合审查0 Critical/Important/Minor，可进入CI；真实PG仍是显式CI门禁，本地跳过不能算通过。
- 旧全量84588因代码基线改变而定向停止；未停止DYDATA-87的其他测试。最终专项3976、全量1709正在执行，报告logs/dydata93-integrated-targeted.xml及logs/dydata93-integrated-full.xml。
- 自动跟进dydata-87已更新最新生产回退与整合状态，仍为ACTIVE，每15分钟；防止按旧65ee07b生产状态触发补算。
- 整合专项最终113 passed、3项既有弃用警告，包含真实登录浏览器流程。完整pytest1709仍运行，草稿PR仅用于CI与真实PG验证，不代表合并或发布放行。
