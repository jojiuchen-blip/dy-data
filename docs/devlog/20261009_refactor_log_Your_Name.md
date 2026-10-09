# 开发日志 — 2026-10-09

主题：打榜辅助指标及历史门店名称纠正；执行人：Your Name。
用户明确授权跳过 Linear，直接推送并合并 Git。[计划 T0.1](../plans/delivery-plans/sub-delivery-plan-clue-terminal-followup-T0.1.md)。

## 变更与口径

- 保留上午 24 小时指标的终态规则。跟进率使用同样的规则，取消 24 小时窗口：分配后核销计 1/1；退款、关闭前有人工跟进计 1/1，否则 0/0；未终态轮次立即计分母。早于分配或时间未知的终态继续排除业务指标。
- 跟进动作率恢复 `0c63965^` 的原人工跟进规则：全部正式分配轮次为分母；同门店、同轮次在分配后至观测截止存在未删除人工跟进为分子，包含未接通、战败、终态后补录；自动核销不算动作。
- 三个指标独立存储、汇总和展示分子分母。前端和 Excel 不要求分母相等。无分母显示暂无样本。指标版本升级，历史业务查询自动重建新口径快照，保留原组织绑定。
- 主指标下展示两个辅助指标及可悬停、聚焦、触屏查看的问号说明。同步组件目录、生成镜像及真实组件预览。
- `20261008_0061` 精确纠正两家门店历史名称，保留审计、来源摘要及条件回滚；不改变业务事实。详见 [上线核对](20261008_historical_store_name_correction.md)。

## 验证证据

- 完整 `python -m pytest -q --tb=short`：3370 passed、178 skipped，1487.44 秒。跳过项保留专用 PostgreSQL 环境等原有条件，不算通过。
- 新增 `tests/test_ranking_follow_live_browser.py` 后独立复验：2 passed，10.28 秒。真实 FastAPI、SQLite 源记录、业务快照、Vite、Chromium 链路；仅测试认证注入，未 mock API。1440/390 视口验证 24h=1/3、跟进率=2/2、动作率=1/4，以及真实空筛选的 0/0 和暂无样本、问号操作、无页面错误。
- 组件目录更新后 `test_design_system_docs.py`、`test_design_system_enforcement.py`、`test_frontend_user_facing_contracts.py`：71 passed。
- 两个辅助指标交互专项 Node 浏览器用例：2 passed；`npm --prefix apps/web run build` 与 `build:design-system` 通过。构建存在原有大包提示。
- 迁移专项 7、现有迁移 61、部署配置 26 项均通过，已包含在完整回归中。
- `git diff --check`、全局治理校验和计划一致性通过；独立代码审查未发现阻断项。

## 交付状态与边界

本地实现与验收完成，分支 `codex/ranking-follow-metrics-correction` 已推送并经 [PR #45](https://github.com/jojiuchen-blip/dy-data/pull/45) 合并 main，合并提交 `ddb3bab8ba7485af9e702881bab7e6008ba465b2`。
[合并前 CI](https://github.com/jojiuchen-blip/dy-data/actions/runs/37866909328) 及 [主分支 CI](https://github.com/jojiuchen-blip/dy-data/actions/runs/37869238798) 均通过。云端完整回归 3372 passed、178 skipped。

## 服务器部署（2026-10-09）

用户明确授权服务器部署，触发 [腾讯云发布](https://github.com/jojiuchen-blip/dy-data/actions/runs/37870328159)，固定业务版本为 `ddb3bab8ba7485af9e702881bab7e6008ba465b2`。
发布 Verify 已全部通过：完整回归 3372 passed、178 skipped；真实 PostgreSQL 及线索并发门禁、前端和四个镜像均通过。
首次 Deploy 在数据库备份期间 SSH Broken pipe（255），未到迁移。恢复工作流提交 `b8869c3b` 增加保活连接，校验原 Verify 成功、固定业务 SHA、服务器脚本散列，并拒绝并发原部署；没有跳过备份、迁移或健康门禁。
[恢复部署](https://github.com/jojiuchen-blip/dy-data/actions/runs/37873921163) 成功，2026-10-09 10:26:53（北京时间）记录 deployment complete，业务版本 `ddb3bab8ba7485af9e702881bab7e6008ba465b2`。
环境备份 `pre-production-cutover-20261009T021821Z.env`，数据库备份 `pre-migrate-20261009T021824Z.dump`（均位于服务器 `/opt/dy-dashboard/logs/backups/`）。迁移 `20260916_0060 -> 20261008_0061` 成功；API、浏览器、ops-agent、PostgreSQL 健康，worker 调度进程与队列/数据库 smoke、代理及公网入口检查通过。
生产只读回查 2026-09-07 至 2026-10-08：前端新动作率文案、两店历史名称、三种跟进指标各自分子/分母/百分比一致；集团、中心、大区、区域接口 200，汇总与抽样行独立指标校验通过。此回查不代表逐条业务事实全量审计；未执行全量历史状态回填。
服务器日志 `/opt/dy-dashboard/logs/release-resume-ddb3bab8-20261009T021821Z.log`。当前源码采用固定归档部署；以 last-deploy.json 和实际接口为版本证据，不以服务器旧 Git HEAD 代替。

## 复盘

统计口径不同的指标应分别携带分子、分母，不能以分母相等作为数据完整性条件。已有回归覆盖；仅记录，不新增全局规则。

## 看板悬停说明精简（2026-10-09）

【用户确认】看板移除问号，以指标名称悬停查看两三行计算说明；辅助指标更名“跟进动作衡量指标”。卡片、排名表、导出同步命名，数值和业务计算不变。仅看板启用无图标模式，保留键盘聚焦、触屏点击及 Escape 关闭。无 foundation 漂移。

本地专项92项通过，前端及组件目录构建通过；最终桌面悬停/移动点击与部署配置34项通过，diff和治理检查通过。腾讯部署SSH新增保活，保留所有验证与备份门禁。云端CI和上线结果待补充。


2026-10-09【用户确认】跟进率分母复用24小时有效跟进率分母，仅取消分子的24小时时限；超过24小时退款/关闭且未跟进仍保留0/1。跟进动作衡量指标独立分母不变，主24小时指标及自店核销率不变。指标版本升级v5，历史业务查询重算，保留组织归属。已明确授权修改、合并Git并部署服务器。

先更新边界测试复现旧行为：4失败、13通过；实施后第一轮121通过、5个旧分母预期失败，已按新口径更新。最终专项185项通过；前端构建、diff和治理检查通过；云端CI及部署结果待补充；不新增数据库字段，不执行历史线索状态回填。无foundation结构漂移。
