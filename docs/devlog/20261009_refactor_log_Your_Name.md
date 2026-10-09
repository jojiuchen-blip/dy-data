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

本地实现与验收完成，准备提交分支 `codex/ranking-follow-metrics-correction`。GitHub PR、CI、合并结果待补充。未执行生产部署、迁移或全量历史状态回填。

## 复盘

统计口径不同的指标应分别携带分子、分母，不能以分母相等作为数据完整性条件。已有回归覆盖；仅记录，不新增全局规则。
