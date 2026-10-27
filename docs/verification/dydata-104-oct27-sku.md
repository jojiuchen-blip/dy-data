# DYDATA-104：长期 SKU 完整同步验证（2026-10-27）

范围：T3.1 / 2026-10-27 用户确认的精确 SKU 关联与常规商品同步。基线 `d206a654`，保留 PR63 商品分类规则；未修改月结、财务、模型、迁移、费率或人工分类。仅使用合成 ID、模拟 HTTP 和本地测试数据库，没有向真实平台发请求或写入生产。

## 已有能力与本次根因

`src/dy_data/douyin_client.py` 已按单个 JSON 数组参数编码 `product_ids` / `sku_ids`，分别限制每批 10 个商品、50 个 SKU。本次保留客户端，新增通过 requests.PreparedRequest 验证实际 URL 的测试。长 ID 始终使用字符串，保留特殊字符与大于 JavaScript 安全整数范围的精确值。

`apps/worker/product_sync.py` 已扫完上架、下架、封禁三种状态的全部游标页；目录和原始订单中已知的精确商品/SKU 对用于缺口补查。缺口不在于缺少一套补查功能，而是以下边界：

- SKU 部分成功响应原先直接报错，不能恢复短暂漏返回；商品 ID 部分返回则直接合成 `NOT_FOUND`，混淆未返回与权威不存在。
- 内联同 SKU 的冲突被 `setdefault` 静默去重；补查中的已见 SKU 在过滤时可能跳过商品或归属身份冲突检查。
- 列表只防相邻游标重复，未明确阻断非相邻游标回环。

## 修复结果

每个商品批次和 SKU 批次最多调用三次查询，只重查缺失 ID，已返回的结果不重复请求。重复、非请求 ID、已知商品关联冲突、创建者/归属冲突、畸形行或错误码直接失败。SKU 的独立状态枚举继续要求已验证的 `status=1`，不把未知/删除状态继承为商品上架。

三次仍缺失时，任务为 `FAILED / INCOMPLETE_RESPONSE`，`retryable=true`，生成 `product_sync_incomplete_response` 数据质量告警；当前目录整批不更新，不伪造 SKU 或 `NOT_FOUND`。未知商品未提供任何精确 SKU ID 时保留跳过行为，并新增 `product_sync_missing_sku_identity` 告警和跳过计数；不能从商品名称或商品 ID 推造一个 SKU。

每次运行的 `job_runs.metadata_json.lookup_stats` 保留商品/SKU逻辑查询次数、部分响应次数、每批上限及现有客户端的业务/网络重试上限。日志只输出尝试次数和缺失数量，不输出凭据、游标或外部完整载荷。

### 重试预算

本次补偿只处理已成功返回但不完整的响应，不捕获传输、配额或客户端错误后重新开始。现有客户端默认业务响应最多 3 次，每个业务尝试的网络最多 3 次，因此每次逻辑查询的商品 HTTP 上界为 9；缺失补偿最多 3 次逻辑查询，单批理论上界为 27 次商品 HTTP。认证取 token / 刷新 token 请求单独受现有客户端与 governor 控制，不包含在这个商品 HTTP 上界中。统计中的 HTTP 数为显式上界，逻辑查询次数为实测次数。

网络三次耗尽会立即抛出到任务失败路径，不启动第三次缺失补偿；真实客户端的 FakeHttp 测试验证一次部分成功后仅发生三次网络尝试，连同一次 token 请求共五次 HTTP 调用。定时器仍按最近启动时间限制创建新任务，不自动立即重新执行失败任务。未修改整个客户端通用重试策略。

## 验证

执行命令（测试解释器使用可用 Python 环境，`PYTHONPATH` 指向本工作树）：

```powershell
python -m pytest tests/test_worker_product_sync.py tests/test_product_sync_sku_lookup.py tests/test_product_sync_completeness.py tests/test_douyin_openapi_client.py tests/test_product_sync_heavy_admission.py tests/test_worker_scheduler.py tests/test_dydata104_scheduler_maintenance.py tests/test_api_admin_sync_control_plane.py tests/test_product_sync_sku_lookup_postgres.py tests/test_api_fee_admin.py tests/test_api_product_type_visibility.py -q
git diff --check
```

结果：`198 passed, 8 skipped`，pytest 退出码 0；`git diff --check` 退出码 0。8 项均为专用 PostgreSQL 环境依赖的显式跳过；149 条警告来自既有 FastAPI/Starlette、MCP 认证配置与 SQLite datetime 弃用提示，没有测试失败。新增 `test_product_sync_completeness.py` 含 17 个测试案例。

覆盖：同商品 125 个长 ID SKU 跨三页、另一个非清单下架 SKU、全部商品状态；超过基准数量的商品和 101 SKU 的分批补查；部分商品/SKU响应恢复；三次缺失耗尽后的提交回读、零覆盖和告警；内联重复、商品/归属冲突；游标回环；真实客户端传输重试边界；URL 参数编码；PR63 分类、后台导入、重任务资源准入及调度回归。

## 剩余验收边界

- 本地专用 PostgreSQL 测试 URL 未配置时，真实 PG 专项明确跳过；需要集成 CI 的专用 PostgreSQL 环境补验。
- 全库回归、最终 CI、生产发布和真实平台全量覆盖由集成负责人另行验收；本记录不声称真实平台已返回所有目标 SKU。
- 现有平台流程只对来源已暴露的精确 SKU 建档；未知商品没有 SKU ID 时只能告警并保持事实，不将同步成功状态解释为该未知商品所有规格已证实完整。
- 本任务无新增 foundation 漂移。PR63 已登记的商品分类文档差异继续由原责任方维护；本次未改动基础文档或计划。
