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

三次仍缺失时，任务为 `FAILED / INCOMPLETE_RESPONSE`，`retryable=true`，生成 `product_sync_incomplete_response` 数据质量告警；当前目录整批不更新，不伪造 SKU 或 `NOT_FOUND`。列表返回的任意无 SKU 商品均按其精确商品 ID 自动加入补查，包括没有目录/订单基准的新增商品。空记录保留 `product_sync_missing_sku_identity` 告警和计数，但告警本身不构成完整性闭环。

**空记录的一致规则**：完整扫描三种状态及全部游标后，冻结“已知 SKU 缺口 ∪ 任意列表空 SKU 商品”的商品 ID 集合，每个商品只进入一个有界补查批次。同商品在另一页/状态已给出部分或完整已知 SKU，也不能自动消除其空记录，必须通过精确商品 ID 复核。ID 响应给出实际 SKU 后可恢复；已有精确 SKU ID 的商品若 ID 响应仍空，按已知 SKU 查询恢复。未知商品没有可查询的 SKU ID 时，只重查商品 ID（最多三次）；仍空即失败，不能从商品名称或商品 ID 推造 SKU，也不能标全量成功。

**成功与新鲜度**：未闭环时，任务 `status=failed`、`success_count=0`，不会进入当前快照更新或成功游标更新路径；已有 `last_synced_at`、`sync_run_id`、上次成功任务均保持。`product_sync_latest_success_at` 对失败任务返回空。测试包含提交后重新读取，确保调度/API不能将这次空数据失败当作新鲜完整来源。

每次运行的 `job_runs.metadata_json.lookup_stats` 保留商品/SKU逻辑查询次数、部分响应次数、每批上限及现有客户端的业务/网络重试上限。日志只输出尝试次数和缺失数量，不输出凭据、游标或外部完整载荷。

### 重试预算

本次补偿只处理已成功返回但不完整的响应，不捕获传输、配额或客户端错误后重新开始。现有客户端默认业务响应最多 3 次，每个业务尝试的网络最多 3 次，因此每次逻辑查询的商品 HTTP 上界为 9；缺失补偿最多 3 次逻辑查询，单批理论上界为 27 次商品 HTTP。认证取 token / 刷新 token 请求单独受现有客户端与 governor 控制，不包含在这个商品 HTTP 上界中。统计中的 HTTP 数为显式上界，逻辑查询次数为实测次数。

网络三次耗尽会立即抛出到任务失败路径，不启动第三次缺失补偿；真实客户端的 FakeHttp 测试验证一次部分成功后仅发生三次网络尝试，连同一次 token 请求共五次 HTTP 调用。定时器仍按最近启动时间限制创建新任务，不自动立即重新执行失败任务。未修改整个客户端通用重试策略。

## 验证

执行命令（测试解释器使用可用 Python 环境，`PYTHONPATH` 指向本工作树）：

```powershell
python -m pytest tests/test_worker_product_sync.py tests/test_product_sync_sku_lookup.py tests/test_product_sync_completeness.py tests/test_douyin_openapi_client.py tests/test_product_sync_heavy_admission.py tests/test_worker_scheduler.py tests/test_dydata104_scheduler_maintenance.py tests/test_api_admin_sync_control_plane.py tests/test_product_sync_sku_lookup_postgres.py tests/test_api_fee_admin.py tests/test_api_product_type_visibility.py tests/test_product_sync_completeness_postgres.py -q
git diff --check
```

更正后结果：未配置 PG 的扩展组 `203 passed, 13 skipped`，pytest 退出码 0；随后在主线程提供的本机独立合成测试库执行以下 PostgreSQL 组，结果 `29 passed`、零跳过，退出码 0，耗时 177.32 秒，覆盖了此前13项跳过（原有8项，加空商品闭环/新鲜度5项）。每项使用独立随机 schema，不访问生产库。`git diff --check` 退出码 0；最终完整性窄组再次执行 `22 passed`。既有149条警告来自 FastAPI/Starlette、MCP认证配置与SQLite datetime 弃用提示，没有测试失败。原 `198 passed, 8 skipped` 仅为更正前记录，不能作为空商品完整性验收。

```powershell
# 通过本地未跟踪配置注入 DYDATA_PUBLICATION_TEST_DATABASE_URL / DY_MAINTENANCE_POSTGRES_URL；不记录连接值。
python -m pytest tests/test_product_sync_heavy_admission.py tests/test_product_sync_sku_lookup_postgres.py tests/test_product_sync_completeness_postgres.py -q --tb=no --disable-warnings
```

覆盖：同商品 125 个长 ID SKU 跨三页、另一个非清单下架 SKU、全部商品状态；超过基准数量的商品和 101 SKU 的分批补查；部分商品/SKU响应恢复；三次缺失耗尽后的提交回读、零覆盖和告警；内联重复、商品/归属冲突；游标回环；真实客户端传输重试边界；URL 参数编码；PR63 分类、后台导入、重任务资源准入及调度回归。

## 剩余验收边界

- 本机专用 PostgreSQL 专项已通过；最终集成 CI 仍需独立验证。
- 全库回归、最终 CI、生产发布和真实平台全量覆盖由集成负责人另行验收；本记录不声称真实平台已返回所有目标 SKU。
- 现有平台流程只对来源已暴露的精确 SKU 建档；未知商品精确 ID 补查仍没有 SKU 时明确失败并保持事实，不将其标为全量成功。
- 本任务无新增 foundation 漂移。PR63 已登记的商品分类文档差异继续由原责任方维护；本次未改动基础文档或计划。
