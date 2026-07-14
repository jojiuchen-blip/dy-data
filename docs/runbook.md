# dy-data 生产运行手册

本文档面向 Linux Docker Compose 部署，覆盖 PostgreSQL、FastAPI、worker、React 静态构建、受最高管理员保护的 noVNC Chromium 采集容器、反向代理、迁移和数据刷新任务。业务范围包括经营结算、线索运营和后台管理，产品定义以 `docs/项目产品介绍书.md` 为准。

## 1. 配置原则

- 生产配置只允许来自环境变量、Docker secret 或服务器上的未跟踪配置文件。
- 不提交真实业务数据、抖音账号、cookie、密钥、本地路径或导出文件。
- `config.local.json`、采集输出、浏览器 profile 和下载目录必须保持未跟踪状态。
- v1 不接退款接口，不上线发票/到票/OCR/财务审核流程；退款只通过订单/券状态参与内部分账排除和异常诊断。

## 2. 本地开发

复制示例配置后填入本机配置：

```powershell
Copy-Item config.example.json config.local.json
```

也可以用环境变量覆盖配置：

```powershell
$env:DOUYIN_APP_ID = "CHANGE_ME_APP_ID"
$env:DOUYIN_APP_SECRET = "CHANGE_ME_APP_SECRET"
$env:DOUYIN_ACCOUNT_ID = "CHANGE_ME_ACCOUNT_ID"
$env:DY_DATA_CONFIG = ".\config.local.json"
```

安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
```

PowerShell entrypoints read Python in this order:

1. `DY_DATA_PYTHON_EXE`
2. `paths.python_exe` in `DY_DATA_CONFIG`, `config.local.json`, or `config.json`
3. `.venv\Scripts\python.exe`
4. `python` on `PATH`

Python scripts under `scripts/` add the repository root before importing `src.dy_data`, so isolated embedded Python runtimes do not fail with `ModuleNotFoundError: No module named 'src'`.

## 3. 生产部署

部署文件位于 `deploy/`。

1. 复制环境变量模板，并在服务器上替换所有 `CHANGE_ME_*`：

```bash
cp deploy/.env.example deploy/.env
```

2. 校验 Compose 插值：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml config
```

3. 启动服务：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
```

Compose 会先运行一次 `migrate` 服务执行 `alembic upgrade head`，API 和 worker 会等迁移成功后启动。排障时可以单独运行：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm migrate
```

只有 `proxy` 服务发布宿主机端口。`postgres`、`api`、`worker`、`web`、noVNC 和 Chromium CDP 只暴露在 Docker 网络中。公网部署时，在 proxy 或上游负载均衡终止 TLS，并确保容器原始端口不对宿主机开放。

## 4. 最高管理员登录

生产必须配置：

- `DY_SUPER_ADMIN_USERNAME`
- `DY_SUPER_ADMIN_PASSWORD_HASH`
- `DY_SESSION_SECRET`

`DY_SUPER_ADMIN_USERNAME` 是系统最高管理员账号名，不再提供默认账号。`DY_SUPER_ADMIN_PASSWORD_HASH` 支持 PBKDF2 或 bcrypt。开发测试可以启用 `DY_API_TEST_MODE=true` 并显式配置 `DY_TEST_ADMIN_PASSWORD`，生产不得启用测试模式。

业务页面和明细导出都要求登录；后台管理类接口和 `/browser/` noVNC 入口只允许最高管理员访问，避免把数据采集行为暴露给普通门店账号。

## 5. 数据任务

后端 worker 负责：

- 从 `2026-01-01 00:00:00 Asia/Shanghai` 起补数。
- 每日按重叠窗口刷新订单、券、核销、职人/抖音号、POI 和 SKU 规则。
- 物化一行一券的 `settlement_order_details`。
- 刷新门店销售排名和门店月度分账汇总。
- 将未匹配销售归属、POI、SKU、异常退款/撤销核销等问题写入 `data_quality_issues`。
- 将每次任务状态写入 `job_runs`。

采集是后端服务行为，不在前端看板展示触发按钮。生产默认 worker 命令是：

```bash
python -m apps.worker.scheduler
```

默认 `WORKER_MODE=collect_and_settle`，每次运行会按 `DOUYIN_COLLECT_OVERLAP_DAYS` 重叠窗口拉取抖音开放平台数据，写入 raw/dimension 表，再刷新结算明细和汇总表。应急排障时可以临时设置 `WORKER_MODE=settlement_only`，只基于数据库现有 raw 数据重算看板。

首次全量回填可以单独运行一次：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm worker \
  python -m apps.worker.collect_once --start 2026-01-01 --end 2026-06-12 --skip-browser-export
```

日常重叠窗口刷新可以使用：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm worker \
  python -m apps.worker.collect_once --overlap-days 7 --skip-browser-export
```

生产至少需要配置以下采集变量：

- `DOUYIN_APP_ID`
- `DOUYIN_APP_SECRET`
- `DOUYIN_ACCOUNT_ID`
- `WORKER_MODE`
- `DOUYIN_COLLECT_START`
- `DOUYIN_COLLECT_OVERLAP_DAYS`
- `DOUYIN_VERIFY_CHUNK_DAYS`
- `BROWSER_CDP_URL`
- `BROWSER_EXPORT_COMMAND`
- `BACKEND_AWEME_EXPORT_URL`

检查任务状态：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml exec postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "select job_id, job_name, status, started_at, finished_at, success_count, failed_count, error_message from job_runs order by started_at desc limit 20;"
```

采集完成后，使用有权限的测试账号访问销售、排名、结算、订单明细和线索页面，确认 API 数据可读、筛选口径一致且汇总可下钻到明细。所有业务页面和导出都要求登录；任务状态、管理接口、采集入口和 `/browser/` 还需满足对应管理员权限。

轮换抖音开放平台凭据时，只更新服务器环境变量或未跟踪 `.env`，然后重启 worker/API 容器；不要改前端代码，不要把新凭据写入仓库。轮换 noVNC/抖音后台登录态时，通过受保护 `/browser/` 入口重新登录，浏览器 profile 保存在 Docker volume 中。

生产浏览器采集应通过适配器启动：

```bash
python scripts/exports/auto_export_backend_aweme_chromium.py \
  --job-name backend_aweme_chromium_export \
  --cdp-url "$BROWSER_CDP_URL" \
  --download-dir "$BROWSER_EXPORT_DOWNLOAD_DIR" \
  --artifact-dir "$BROWSER_EXPORT_ARTIFACT_DIR" \
  --command 'python -m apps.worker.browser_exports.backend_aweme'
```

适配器会写入 `running` 状态，校验 Chromium CDP 可达，执行具体采集命令；失败时记录 `failed`，成功后清理单次临时下载目录。具体采集命令会收到 `JOB_RUN_ID`、`BROWSER_CDP_URL`、`BROWSER_EXPORT_RUN_DIR`、`BROWSER_EXPORT_DOWNLOAD_DIR` 和 `BROWSER_EXPORT_ARTIFACT_DIR`。

### 5.1 线索分配 M1 数据基础

`alembic upgrade head` 会创建线索主池、状态事件、评分快照运行批次和门店评分快照表，并扩展原始线索与门店主数据。M1 保留既有 `clue_center_orders` / `clue_assignment_rounds` 作为旧投影；新主池不会把抖音 `follow_life_account_id/name` 当作我方实际分配结果。

业务提供的适用门店坐标文件只能作为一次性导入输入，不能提交到仓库或在 worker 运行时直接读取。先在受控数据库执行 dry run：

```bash
python scripts/import_store_locations.py \
  --input /secure/input/store-locations.xlsx \
  --dry-run
```

核对未映射 POI、无效坐标和关闭门店后，再显式开启有效门店的分配参与资格：

```bash
python scripts/import_store_locations.py \
  --input /secure/input/store-locations.xlsx \
  --enable-participation
```

坐标文件中的“门店ID”按 POI 处理，必须先通过 `dim_store_poi_mappings` 映射到内部 `dim_stores.store_id`；脚本不会直接用它创建内部门店。文件可选提供“门店所在省份”；若省份缺失，worker 只会在同一 `follow_poi_id` 的原始 `auto_province_name/auto_city_name` 证据唯一且城市一致时补齐。省、市、规范城市键或坐标不完整的门店不会成为候选门店。

缺失 `follow_poi_id`、映射失败或锚点的省市/坐标不完整时，线索会在主池记录原因并进入总部池；不会回退到 `intention_poi_id`。锚点有效但尚未由 M2 策略分配的线索不会伪装成总部或门店任务：`pool_location` 为空，`allocation_state=pending_allocation`。`pool_location` 只保存 `store_follow_up_pool`、`headquarters_pool`、`closed` 三种业务池语义。

每次完成 `collect_and_settle` 后，worker 会刷新全量线索主池；上海时区 `03:00` 后首次成功任务会尝试生成当日门店评分快照。评分只读取 `execution_mode=formal` 的成熟轮次，旧抖音分配轮次默认标记为 `legacy`，不污染正式评分。手动导入或评分刷新前后应检查 `data_quality_issues` 与 `job_runs`，不要从日志、导出或截图中传播完整联系方式。

需要在受控环境手动重算时，可生成一个新的不可变评分批次；此命令不输出数据库连接串或联系方式：

```bash
python scripts/refresh_store_scores.py --lookback-days 30 --min-samples 20 --dry-run
```

最高管理员还可调用以下 API 查看不含联系方式的主池/评分数据，或手动创建新的不可变评分批次：

- `GET /api/v1/admin/clue-allocation/master-leads`
- `GET /api/v1/admin/clue-allocation/store-scores`
- `POST /api/v1/admin/clue-allocation/store-scores/refresh`

## 6. noVNC 浏览器

通过看板同域名访问 `/browser/`。Nginx 使用 `auth_request` 调用 `/api/v1/auth/me`，因此 noVNC 入口必须先完成后台管理员登录。

浏览器容器使用 Docker volume 保存 Chromium profile 和下载目录。这些 volume 可能包含抖音登录态和导出文件，禁止复制进仓库或通过静态文件服务暴露。

## 7. v2 / 诊断脚本

旧退款导出脚本和发票/财务确认流程不属于 v1 上线门禁。只有在产品明确需要 v2 售后明细或财务确认时，才重新评估退款接口、发票字段、OCR 和正式应收确认规则。

诊断脚本可以在本地人工执行，但输出文件必须保持未跟踪，不得提交真实 CSV/JSON。
