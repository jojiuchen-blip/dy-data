# dy-data 生产运行手册

本文档面向 Linux Docker Compose 部署，覆盖 PostgreSQL、FastAPI、worker、React 静态构建、受最高管理员保护的 noVNC Chromium 采集容器、反向代理、迁移和数据刷新任务。业务范围包括经营结算、线索运营和后台管理，产品定义以 `docs/项目产品介绍书.md` 为准。

## 1. 配置原则

- 生产配置只允许来自环境变量、Docker secret 或服务器上的未跟踪配置文件。
- 不提交真实业务数据、抖音账号、cookie、密钥、本地路径或导出文件。
- `config.local.json`、采集输出、浏览器 profile 和下载目录必须保持未跟踪状态。
- 开票、红冲、作废和厂家审核均在系统外完成；生产系统只登记发票事实、导入已完成的结果、计算结转投影并保留查询、导出和审计记录，不接 OCR 或外部验真。

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

2. 校验 Compose 插值，并确认输出不包含任何 `CHANGE_ME_*` 占位符：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml config
```

3. 标准发布使用受控脚本并传入已经通过 CI 的目标提交：

```bash
APP_DIR=/opt/dy-dashboard/repo \
ENV_FILE=/opt/dy-dashboard/env/production.env \
bash deploy/tencent/deploy.sh <verified-commit-sha>
```

脚本会在构建前展开并校验 Compose 配置，发现 `CHANGE_ME_*` 立即终止；启动 PostgreSQL 后、执行 migration 前使用 `pg_dump --format=custom` 生成非空备份，默认写入 `/opt/dy-dashboard/logs/backups/pre-migrate-<UTC时间>.dump` 并设置为 `0600`。随后执行 `alembic upgrade head`、启动运行服务并校验首页、未登录鉴权和 CLI 登录入口。任何步骤失败都会退出非零并输出受限尾部日志。

Compose 的 `migrate` 服务执行 `alembic upgrade head`，API 和 worker 会等迁移成功后启动。排障时可以单独运行：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm migrate
```

发布后必须保存目标提交、CI/部署日志、备份文件路径和 smoke 结果。若 migration 或 smoke 失败，不得删除历史迁移或直接修改生产数据掩盖问题：先停止新流量/worker，保留故障日志，使用最近一次验证通过的提交前滚修复；确需数据库恢复时，在确认会丢弃故障发布后的写入后，使用本次 `pre-migrate-*.dump` 在隔离环境验证恢复，再按事故流程执行生产恢复。应用层可回退到上一个已验证提交，但只有 migration 明确支持 downgrade 且已评估数据影响时才允许数据库降级。

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

## 8. 受限 Ops Agent 与 8GB 资源护栏

Ops Agent 是独立的、无 HTTP 端口的运维进程。它只接受数据库中已确认的两类固定命令：`restart(worker)` 和 `restart(browser)`；不提供 shell、exec、stop、remove、scale、镜像或任意参数入口。Docker socket 只挂载到 Ops Agent，API 服务不挂载 Docker socket。目标容器必须通过当前 Compose project/service label 唯一匹配；零个或多个匹配均 fail closed。

命令 claim 使用短 TTL（pending 默认 120 秒）和单目标活动唯一约束。运行中的过期 claim 会回收为 pending，并递增 `lease_epoch`；完成更新必须同时匹配 command、owner、epoch 且仍未过期，因此旧执行者不能完成已被回收的命令。已领取 lease 的有限预算按串行链路相加：pending TTL 余量、两次 Docker label 查询、restart grace/响应余量和 replacement heartbeat 等待；restart 副作用前还会原子校验 owner/epoch/lease 并按剩余链路续租。每次命令成功、失败或拒绝完成时，`cooldown_until` 都从完成时间重新起算固定 300 秒。

重启 browser 前，Ops Agent 会拒绝活动导出：检查共享的 `/run/browser/browser-export.active` 标记、browser heartbeat 活动字段，以及 `job_runs` 中 `backend_aweme_export` 的 queued/running 状态。worker 重启使用 300 秒 Docker grace period；Compose 的 `exec` 命令保证 SIGTERM 传递到 scheduler，scheduler 应先停止领取新任务。重启后必须看到新实例或同实例的新 `started_at` heartbeat，才会把命令记为成功。

资源采样读取进程树 RSS、Linux cgroup current/limit、`MemAvailable` 和 swap。默认阈值是主机已用内存告警 6.0 GiB、停止 6.4 GiB、进程树 RSS 2 GiB、cgroup current 3 GiB、swap 使用 0；这些值只是可配置的 benchmark 初值，不代表已通过生产验证。worker 在领取重型子进程前遇到 drain/stop 决策会返回 control error，已有子进程 RSS 护栏仍按自身配置工作。

首次启用或数据库迁移新增表后，由 PostgreSQL 角色管理员重复执行最小权限脚本。脚本不会设置或保存密码，也不会自动修改 PUBLIC ACL。PostgreSQL 数据库通常默认向 PUBLIC 提供 `TEMPORARY`，旧数据库的 `public` schema 也可能仍向 PUBLIC 提供 `CREATE`；这两类有效权限不能通过只对 `dy_ops_agent` 执行 `REVOKE` 来抵消。

因此，执行 bootstrap 前必须由管理员完成一次显式前置门禁。先盘点 PUBLIC ACL 和所有登录角色的现有效权限，不得直接假设其他业务角色不需要临时表或迁移建表能力：

```sql
SELECT database_acl.privilege_type, database_acl.is_grantable
FROM pg_database AS database
CROSS JOIN LATERAL aclexplode(
    COALESCE(database.datacl, acldefault('d', database.datdba))
) AS database_acl
WHERE database.datname = current_database()
  AND database_acl.grantee = 0;

SELECT schema_acl.privilege_type, schema_acl.is_grantable
FROM pg_namespace AS namespace
CROSS JOIN LATERAL aclexplode(
    COALESCE(namespace.nspacl, acldefault('n', namespace.nspowner))
) AS schema_acl
WHERE namespace.nspname = 'public'
  AND schema_acl.grantee = 0;

SELECT rolname,
       has_database_privilege(oid, current_database(), 'CREATE') AS database_create,
       has_database_privilege(oid, current_database(), 'TEMP') AS database_temp,
       has_schema_privilege(oid, 'public', 'CREATE') AS public_schema_create
FROM pg_roles
WHERE rolcanlogin
ORDER BY rolname;
```

只对盘点后确认仍需这些能力、且收紧前已经拥有相同有效权限的业务或迁移角色补直接授权，然后再收紧 PUBLIC。下面的角色变量必须替换为实际审计确认的角色；不要把未知角色批量授权，也不要在 bootstrap 脚本中自动执行这组全局变更：

```sql
\set required_temp_role 'replace_after_audit'
\set required_migration_role 'replace_after_audit'
GRANT TEMPORARY ON DATABASE :"DBNAME" TO :"required_temp_role";
GRANT CREATE ON DATABASE :"DBNAME" TO :"required_migration_role";
GRANT CREATE ON SCHEMA public TO :"required_migration_role";

REVOKE CREATE, TEMPORARY ON DATABASE :"DBNAME" FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
```

若未完成该前置，或 `dy_ops_agent` 是数据库/schema owner，bootstrap 会在事务内 fail closed 并回滚。前置校验通过后再执行最小权限脚本，随后在交互式 `psql` 中用 `\password` 设置部署环境密钥，且不要把密钥放进命令行、仓库或日志：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml exec -T postgres \
  sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < scripts/ops/bootstrap_ops_agent_role.sql

docker compose --env-file deploy/.env -f deploy/compose.yaml exec postgres \
  sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
# 在 psql 内执行：\password dy_ops_agent
```

`dy_ops_agent` 的业务表权限固定为：`ops_commands` 仅 `SELECT/UPDATE`，`component_heartbeats` 仅 `SELECT/INSERT/UPDATE`，`job_runs` 仅 `SELECT`。脚本先撤销该角色在所有非系统 schema 的既有表、序列和 schema 权限及角色成员关系，再验证其不具有数据库 `CREATE/TEMP` 和 `public` schema `CREATE`，最后授予固定集合；任何额外有效业务表权限或对象所有权带来的越权都会 fail closed。执行完成后再把独立凭据写入未跟踪的 `OPS_AGENT_DATABASE_URL`。

本地只做配置与专项验证，不执行生产 Docker 操作：

```bash
python -m pytest -q tests/test_ops_agent.py tests/test_worker_resource_metrics.py tests/test_deploy_compose_config.py
DY_WEB_BASE_URL=https://dy-business-engine.com \
OPS_AGENT_DATABASE_URL=postgresql+psycopg://dy_ops_agent:CHANGE_ME@postgres:5432/dy_dashboard \
docker compose -f deploy/compose.yaml -f deploy/compose.acceptance.yaml config
```

4C/8GB Linux 主机上的三轮 acceptance、Docker socket 的宿主机权限隔离、目标 PostgreSQL 上执行并核验最小权限脚本、生产 canary、回滚和真实 worker/browser replacement heartbeat 均是未验证门禁；未完成这些门禁前，不得把阈值或 Ops Agent 标记为生产验证结论。
