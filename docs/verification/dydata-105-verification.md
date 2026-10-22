# DYDATA-105 实现与验证记录

关联 [Linear DYDATA-105](https://linear.app/keith-lim/issue/DYDATA-105)、[主计划](../plans/delivery-plans/main-delivery-plan-dydata-105.md)、[账号权限规则](../rules/account-access-control.md)。本记录区分候选实现、隔离验证、CI、生产部署与业务接受；本轮没有生产写入或部署。

## 实现范围

- 管理员统一为 `admin`，固定全部页面；数据范围保持原样。全国范围管理员可以新增、变更全部账号，受限管理员只管理自身全部覆盖的门店账号。账号无删除入口和接口；最后一名有效全国管理员受事务并发保护。
- 全局规则、角色默认、同步、重算仍要求全国范围。旧角色迁移到 0064，保留密码、状态、门店和组织绑定，审计旧页面覆盖并使旧 Web、CLI、MCP 凭据失效。
- 导出头移除内部授权数组，集合只记数量，ASCII JSON 最多 1024 字节；实际查询仍按完整授权执行。财务中文筛选正常编码，SAP 超量导出明确拒绝而非截断。
- 线索支持账户 ID / POI ID 批量精确匹配，与门店名称选择合并；列表、总数与导出使用同一授权集合。最多 1000 个唯一输入 ID / 所选门店，显式空数组为零结果，超限整体拒绝。
- 财务费用、门店、异议补齐分页；管理费重复导入只在原发票仍是当前有效版本且内容完全相同时返回无变化，避免重复生成正式发票。
- 已作废/红冲发票的重新开票候选独立展示，保留当前发票列表与金额口径；财务同查询刷新保留上一完整发布结果及其导出版本。
- 账号审计按事件发生时的前后范围快照检查；转店前记录和缺少范围的历史记录对受限管理员隐藏，全国管理员保留完整历史，审计不记录密码或哈希。
- 门店搜索框重新聚焦、输入、选中或卸载时取消旧离焦回调，避免快速重新输入被上次选中项覆盖；正常离焦仍回显当前选择。

## 已取得的证据

命令均在隔离候选工作树执行，数据库与浏览器使用合成数据。下列专项结果不能相加为互不重复的总测试数。

| 验证 | 命令 / 资产 | 当前结果与实际断言 |
|---|---|---|
| 管理员真实浏览器与演示回归 | `python -m pytest tests/test_visual_admin_rule_permissions.py tests/test_frontend_clue_demo_mode.py -q` | 19 passed，78.67 秒；全国/受限账号新增、变更、重载回读，23 页固定权限、无删除、发布/冲突、发布后刷新失败、两个旧别名保留查询及 hash；7 项真实浏览器，12 项演示合同 |
| 真实 Nginx 大范围导出 | `DY_TEST_NGINX=1 python -m pytest tests/test_dydata105_export_nginx.py -q` | 4 passed，16.75 秒（最终组织重叠场景）；真实 4 KB 缓冲反代、170 家授权门店及重叠组织范围、GET/1000 所选门店 POST、空/非空 CSV；代理与直接 API 字节一致，UTF-8 BOM、授权行和头部容量正确 |
| PostgreSQL 迁移与保护 | `tests/test_admin_unification_postgres.py`、`tests/test_dashboard_publication_migration.py` 及迁移/部署合同测试 | 34 passed；包括 3 项真实账号 PG 用例、2 项空库/带数据全链迁移；并发互停只允许保留一名管理员，等待锁后重验已撤权操作者，旧三类凭据失效 |
| PostgreSQL 发布脚本 | `python scripts/verify_postgres_release_gate.py`；`python scripts/verify_postgres_populated_release_gate.py` | 均退出 0；当前 head `20261022_0064`、事务锁串行、已有快照回填和异常记录保护 |
| 线索 API / 前端专项 | `tests/test_clue_bulk_filters.py`、相关既有 API/跟进测试及前端合同 | C 切片分别 110、83、58 项通过；重叠套件不累加。覆盖前导零、长 ID、一对多、命名空间冲突、未授权/未匹配、1001 拒绝和回退禁用 |
| 线索真实桌面 / 手机及恢复权限集成 | `python -m pytest tests/test_job_recovery_and_evidence.py tests/test_clue_bulk_filter_browser.py -q` | 47 passed，56.74 秒；3 项真实 1440 / 390 浏览器，包括名称/ID 合并、26 行下载、手机收起的 N 家/无匹配摘要、第二页清除回第一页；恢复权限含受限拒绝及环境/数据库全国管理员成功 |
| 线索真实 PostgreSQL | `tests/test_clue_follow_up_postgres.py`、`tests/test_clue_bulk_filters_postgres.py` | C 切片 12 passed，49.27 秒；1000 ID 查询/导出和行锁后门店范围重验 |
| 最终集成账号/线索 PG | `python -m pytest tests/test_admin_unification_postgres.py tests/test_clue_follow_up_postgres.py tests/test_clue_bulk_filters_postgres.py -q` | 15 passed，47.00 秒，退出 0；合并后的权限能力与线索锁检查共同运行 |
| 财务真实浏览器 | `python -m pytest tests/test_dydata105_buttons_browser.py tests/test_dydata105_finance_pagination_browser.py tests/test_finance_export_browser.py -q` | 58 passed，154.56 秒，无失败/跳过；四类导入、CSV/XLSX、实际业务回读、61行全量下载、两方向及五档页大小；14项相关既有 visual 另行通过，mock项在台账注明 |
| 权限与发布结果集成 | `tests/test_dashboard_publication_browser.py`、`tests/test_account_audit_scope.py`、`tests/test_admin_unification.py`、`tests/test_api_account_permissions.py` 与四个线索 API 模块 | 109 passed，162.85 秒；含历史审计范围隔离、固定管理员权限和财务旧发布结果保持/导出 |
| 最终按钮与账号集成 | `python -m pytest tests/test_dydata105_remaining_buttons_browser.py tests/test_account_scope_browser.py -q` | 10 passed，56.82 秒；其中新增 6 项真实 API 用例补齐 7 组按钮证据，另 4 项账号选择/导入验证 |
| 财务 PostgreSQL 并发 | `python scripts/verify_postgres_finance_import_concurrency.py` | 退出 0；一个版本 1 提交成功，另一并发提交返回 VERSION_CONFLICT |
| 重新开票候选与剩余按钮集成 | `python -m pytest tests/test_dydata105_candidate_scope_browser.py tests/test_dydata105_remaining_buttons_browser.py -q` | 9 passed，68.07 秒；门店 A 到 B 的真实候选请求延迟时清除 A，正常响应仅 B；401/403 为明确错误注入，成功响应均来自真实 API，业务计数与金额不变 |
| 结算范围连续性与角色边界 | `python -m pytest tests/test_settlement_scope_continuity.py -q` | 25 passed，18.01 秒；全国管理员可停用并幂等重试，受限管理员/门店/匿名被拒且无业务写入；原月份延续和冻结账单断言保留 |
| Web 构建 | `npm --prefix apps/web run build` | 退出 0，9.88 秒（源码 `c9213fe`，含重新开票范围、门店搜索框及错误提示优先级修复）；后续仅测试/文档变更。存在既有的打包块大于 500 kB 提示 |
| 治理套包 | `npm --prefix .agent/project-manager-suite run test:ai-pm` | 122 passed；锁定 suite 2.0.1、协议与全局文件门禁通过 |

最终集成补证：七个浏览器模块 **91 passed，245.61 秒**；接口/迁移等九模块 **225 passed，557.81 秒**；错误提示修正后六组浏览器 **43 passed，279.47 秒**；筛选布局/线索分页 **9 passed，16.68 秒**。各组合可能重叠，均无失败或跳过。[财务按钮台账](dydata-105-buttons.md) 逐项区分真实 API、mock 和页面无此入口；231 条动作记录不是独立按钮数或覆盖率。原 7 组待补证交互已由新增真实 API 用例覆盖。

合成截图：[受限管理员权限](../../pwScreenShot/dydata105/admin-scoped-permissions.png)、[管理员规则发布](../../pwScreenShot/dydata105/admin-rule-published.png)、[线索桌面批量筛选](../../pwScreenShot/dydata105/clue-bulk-1440.png)、[手机批量输入超限反馈](../../pwScreenShot/dydata105/clue-bulk-390.png)。

## 故障证据与修复边界

导出故障的生产只读日志显示同一请求 API 返回 200，Nginx 返回 502，并记录 `upstream sent too big header while reading response header from upstream`。隔离环境在修复前复现空结果和非空结果均为 502；修复后上述 4 项真实反代回归通过。此结论证实候选修复，不代表线上已更新。

原“最高管理员不能发布规则”的具体用户操作缺少可复现输入。本轮已验证管理员规则发布、冲突、受限范围拒绝以及提交成功后刷新失败的提示，但不将角色合并冒称为该历史反馈的根因证明。

首次全仓测试使用系统 Python 时被用户目录中已安装的同名 `tests` 包遮蔽，8 项在收集阶段报错；切换独立虚拟环境后收集恢复。一次中间全仓运行在合并最后测试修正前主动停止，不能计为通过。完整结果以最终运行记录为准。

## 完整扫描与失败复验

19:05 启动的完整扫描运行至 20:08：**4496 项，4167 passed、34 failed、295 skipped，3785.69 秒，退出 1**。进程启动时的 Python 测试夹具在运行期间没有重新导入；期间修复的功能和测试由后续独立进程验证，不能把此记录改称全仓绿色。

失败分为已确认需求导致的旧角色/能力夹具与断言、旧迁移用例未固定目标版本、页面分页/两行筛选的旧断言，以及回归中确认的财务旧发布结果隐藏、门店搜索框过期回调和错误提示优先级。规则冲突用例改为核对真实 409、稳定错误码、页面业务消息及冲突后仍只有一个业务版本，不再依赖旧通用文案。受限范围拒绝和拒绝后零写入断言保留并加强。

295 个跳过项：283 个未在完整扫描进程启用的 PostgreSQL 专项、4 个 opt-in Nginx、2 个镜像运行检查、4 个规模测试、2 个 Windows 平台条件。与本需求直接相关的真实 PG、Nginx 已独立执行，见上表；未执行的其他可选测试不计为通过。

原 34 个失败映射到当前 32 个完整测试函数（包含重命名、额外范围负向和全国管理员正向），在代码 `4c4c85d` 统一复验：**69 passed，0 failed / error / skipped，188.72 秒，退出 0**。全部原失败均有对应验证，记录为完整扫描后修复与复验，不声称一次全仓全绿。Linear 已转 In Review；草稿 PR 的最终 CI 待审核，生产未部署。

## 交付与剩余事项

2026-10-22 发布前 CI `39777041439` 在提交 `1600de6` 完整扫描得到 **4225 passed、3 failed、293 skipped，1751.56 秒**；显式 PostgreSQL 门禁通过，后续 Nginx/构建步骤未执行。三个失败分别为未同步最终页面提示优先级的合同断言，以及两条依赖宿主上海时区的财务日期边界断言。产品实现保持不变：合同测试分别验证页面显式提示优先、无页面提示时保留业务原因、5xx 隐藏内部消息；日期用例显式指定 `Asia/Shanghai` 浏览器时区，保留原精确 UTC 边界与导出数据断言。需等待修正提交的完整 CI 放行后合并部署，不把失败运行记为通过。

修正后以进程 `TZ=UTC` 运行上述两个完整测试模块：**24 passed，0 failed / skipped，97.04 秒**。`git diff --check`、全局文件验证和 S4 路由通过。该专项结果不替代新提交的完整 CI。

- Foundation 变更已记录在 [契约回捞请求](../plans/foundation-plans/foundation-change-requests-dydata-105.md)，当前运行合同同步至 [API 契约](../api-contract.md)。历史 Foundation 不作为本轮已同步完成的证据。
- 按钮证据需标明真实 API / 浏览器、mock、未测或页面本无入口；不能以组件存在或一次点击代替数据结果。
- 链接索引命令退出 0、mode=noop，但诊断仍有 33 个既有历史断链和 4 个 PNG 不入索引造成的误报；4 个本轮截图文件均实际存在，不将此报告说成全库链接零问题。
- 0064 会撤销旧管理员凭据；部署需同步前后端并完成正常备份门禁。有账号迁移历史时禁止自动 downgrade，回滚需审阅备份恢复方案。
- 生产迁移、部署、上线核验及业务接受仍未执行；DYDATA-105 在这些条件完成前不关闭。
