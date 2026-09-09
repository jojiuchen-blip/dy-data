# 开发日志 — 2026-09-09

> 主题：DYDATA-90 采集前置修复
> 操作人：codex
> 关联计划：docs/plans/delivery-plans/main-delivery-plan-dydata-90-collector-fixes.md

## 执行结果

本地实现及专项验证通过；全仓回归已执行，保留一项可复现的界面测试失败。未提交、未部署、未开启自动同步。本次范围是采集前置缺陷，完整 02:00 日批、两小时基础资料刷新和动态历史预算仍由 DYDATA-90 后续承接。

## 变更

| 文件 | 结果 |
|---|---|
| src/dy_data/douyin_client.py | 新增订单修改时间窗口与分页，复用原有额度和限流入口 |
| apps/worker/collectors/orders.py | 合并新增和修改观察，传递订单与券的源版本 |
| apps/worker/collectors/normalizers.py | 提取可信源时间，不以抓取时间替代 |
| apps/worker/collectors/verify_records.py | 传递核销及撤销版本 |
| apps/worker/repositories.py | 保护旧记录与同秒冲突，使用真实主键记录数据质量问题 |
| apps/worker/collectors/refunds.py | 支持官方及既有时间别名；已存快照重放修复时间；保留已确认时间并记录冲突 |
| tests/test_worker_source_updates.py | 新增持久化、重放、冲突与退款时间回归 |
| tests/test_douyin_openapi_client.py | 验证修改窗口分页、额度入口和无效参数零请求 |

## 验证

- 最终代码相关专项：94 passed，9.66s；output/dydata90-final-targeted.txt。
- 较早扩展 worker/client 组合：370 passed、120 skipped、1 failed。失败为 test_browser_export_marker_cleans_on_signal_and_restores_handler，单独重跑通过；组合信号处理存在不稳定现象，根因未确定，不归因于 Windows 或本轮代码。
- 全仓 pytest：2485 passed、140 skipped、1 failed，1688.01s。失败为 tests/test_visual_store_finance_pages.py::test_store_summary_metrics_stay_compact_in_one_row 的390×844结算页变体，未找到“当期推广服务费”文案；单独重跑仍失败（4.88s）。对应界面与测试文件本轮未改动，未判定最终根因，留待单独处理。日志 output/dydata90-pytest-full.txt、output/dydata90-visual-rerun.txt。全仓进程早于复查补丁启动，后续补丁由最终专项覆盖。
- 独立复查四项问题已修正；异常退款事件冲突路径也补传 session，确保留下 DQI。
- Bandit：0 High、0 Medium、6 Low；为已有五处断言和 TOKEN_URL 误报。详情 docs/security/20260909-dydata90-collector-fixes.md。
- git diff --check 通过。全局文件与正式计划门禁另存 output/dydata90-final-*.json。

## 边界与待办

- 无数据库迁移、依赖变更或 foundation 契约漂移。
- 未执行生产完整单日落库，不代表生产同步已恢复。
- 未验证核销撤销和线索修改的接口窗口覆盖性。
- 下一步：完成日批调度与预算控制后，进行有限单日生产试跑并核对写入、耗额和状态变化。

