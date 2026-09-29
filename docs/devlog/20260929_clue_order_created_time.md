# 线索详情下单时间字段修正

- 用户确认：线索详情中的下单时间必须来自订单创建时间，不能使用线索生成或分配时间。
- 原因：详情抽屉将当前轮次的 `assigned_at` 显示为下单时间。
- 修改：详情接口新增可空 `order_created_at`，通过订单号关联 `raw_douyin_orders.create_order_time`；页面使用该字段并按现有北京时间格式展示。
- 缺失订单或创建时间时返回 null，页面显示 `-`，不回退到支付、线索或分配时间。分配历史和筛选口径不变。
- 验证：`python -m pytest tests/test_api_clues.py -q`，合并最新 main 后 42 passed；`npm --prefix apps/web run build` 成功；`git diff --check` 通过。
- 状态：用户已授权提交、推送、部署；发布门禁和线上核验由本次发布执行记录承接。核销/退款导致线索失效的独立修复不包含在本次字段修正中。
