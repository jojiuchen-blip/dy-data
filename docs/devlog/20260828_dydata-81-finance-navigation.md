# DYDATA-81 财务一级导航开发日志

## 范围

- 新增独立一级“财务”，桌面和移动端均位于“后台”之前，默认进入 `/finance/promotion`。
- 六个既有财务页面统一归入财务二级导航。
- 移除门店结算“SAP 建议”和门店 B02 直达 `/finance/stores` 的前端特例。
- 不修改 API、业务规则、数据模型、迁移或 DYDATA-82。

## TDD 记录

1. 红灯：前端源码契约 2 项失败，分别命中旧门店特例与缺失的 `finance` 一级 section。
2. 红灯：浏览器用例命中缺失“财务”一级项和门店旧 SAP 入口；修正测试定位器后确认失败来自目标行为。
3. 绿灯：最小修改 `Shell.tsx` 与 `App.tsx` 后，聚焦源码契约 2 项、导航与门店浏览器场景 5 项通过。
4. 审查红灯：新增 949×466 视口内可达断言后，仅该参数失败，确认新增一级项使低高度桌面侧栏溢出。
5. 审查绿灯：增加低高度桌面专用侧栏压缩规则，财务/后台 bounding box 均回到视口内，四视口参数测试 4 passed。
6. 全量复跑中 1440×900 参数曾因页面标题 10 秒等待超时单点失败；该参数独立重复 3 次均通过，确认属于全量视觉批次性能波动，随后把新用例的页面就绪等待统一提高到 30 秒。

## 验证记录

- `python -m pytest tests/test_frontend_user_facing_contracts.py -q`：15 passed。
- `python -m pytest tests/test_visual_smoke.py -k "finance_primary_navigation or store_navigation_hides_finance" -q`：5 passed，229 deselected。
- `python -m pytest tests/test_visual_smoke.py -k "finance_primary_navigation or store_navigation_hides_finance or settlement_desktop_subnav_keeps_every_item_visible" -q`：6 passed，228 deselected。
- `python -m pytest`：最终复跑 1418 passed，2 skipped，263 warnings，用时 34 分 06 秒。
- `npm --prefix apps/web run build`：通过；保留既有大 chunk 警告，无新增编译错误。
- `git diff --check`：通过；Windows 工作树仅提示 LF/CRLF 转换警告。
- 390×844、768×1024、1440×900、949×466 可视检查：财务/后台顺序和激活态正确，无导航重叠；门店直达拒绝通过。
- 独立代码审查初次结果：Critical 0、Important 2（同一低高度可达问题及其测试缺口）；补失败断言与 CSS 修复后最终复审为 Critical 0、Important 0、Minor 1、`Ready to merge: Yes`。Minor 为低于约 430px 的极端桌面高度可后续增加独立滚动，不阻塞本次 949×466 验收。

## Foundation 漂移

本任务无 Foundation 漂移。页面仍使用既有 D01/B02 权限与财务路由契约，只删除错误的前端跨模块兼容，不修改 Schema、API 或术语定义。

## 剩余交付门禁

- 本地全量测试、Web 构建、计划一致性和差异检查已通过。
- 提交、推送与 Linear 验证记录回填在本轮完成。
- PR、CI、生产部署、线上 smoke 和用户最终验收仍属于 DYDATA-81 后续发布门禁，本轮不提前关闭 Issue。
