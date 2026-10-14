# DYDATA-102/103 生产发布预案（本地，未执行）

状态：**草案，未执行**。本轮只做连接诊断与发布准备。未推送、未部署、未改生产、未创建凭据、未改代理规则/防火墙/VPN。

连接诊断结论：SSH 到 `dydata-production`（`124.222.59.236:22`）**TCP 可建立但 12 秒内收不到服务端 SSH banner**，连接停在 `Connection timed out during banner exchange`，本机 `Local version string` 已发出。同一条本机代理路径（`127.0.0.1:6544` HTTP CONNECT）可以成功读到 `ssh.github.com:443` 的 banner（`SSH-2.0-3bc2e72`）。**该 443 对照只能证明本机代理可以承载到外部的 SSH over 443，不能排除 22 端口链路的策略差异，因此不能据此排除本机侧原因**。当前只能判定“本机到该 IP:22 未收到 banner”，**根因未定**：远端 sshd 状态、22 端口链路策略、控制台侧状态均未确认。用户无法访问云控制台，因此没有可用的旁路通道可以证伪任一方向。**不做重复网络探测。**

---

## 1. 已核实的生产入口

| 项 | 已核实内容 |
| --- | --- |
| 部署工作流 | `.github/workflows/tencent-lighthouse-deploy.yml`，入口 `workflow_dispatch`（手动）；`push main` 仅在仓库变量 `TENCENT_DEPLOY_ON_PUSH=true` 时触发 |
| 触发条件守卫 | 工作流要求 `TENCENT_START_WORKER=true`，否则**在 SSH 之前**失败（持久化财务检测任务需要 worker） |
| 服务器脚本 | `deploy/tencent/deploy.sh`（服务器上执行；也可由工作流通过 `bash -s` 投递 bootstrap） |
| 服务器布局 | repo `/opt/dy-dashboard/repo`；env `/opt/dy-dashboard/env/production.env`；日志 `/opt/dy-dashboard/logs`；备份 `$LOG_DIR/backups` |
| 数据源/变量 | `TENCENT_HOST`、`TENCENT_SSH_PORT`、`TENCENT_SSH_USER`、`DY_WEB_BASE_URL`（仓库变量）；`TENCENT_SSH_KEY`、`TENCENT_KNOWN_HOSTS`（仓库密文） |
| 本机 SSH alias | `dydata-production`：HostName `124.222.59.236`、User `ubuntu`、Port 22、`IdentitiesOnly yes`、`BatchMode yes`、`StrictHostKeyChecking yes`、无 `ProxyJump`/无 `ProxyCommand`/`ControlMaster` 未启用、无驻留 ssh 主连接 |
| 本机管理通道 | 无 `tccli`/`aws`/`gcloud`；无 `.tccli`/`.tencentcloud`/`.aws` 配置；无 `TENCENTCLOUD_*`/密钥类环境变量。**没有可用云控制台入口，也没有现成 CLI 管理通道** |
| 本机可用出网路径 | `127.0.0.1:6544` = HTTP CONNECT 代理（对 22 端口返回 `200 Connection established`；对 `ssh.github.com:443` 可读到 banner）。另有 `giegiecloud` TUN（PID 15468，无任何 TCP 监听），DNS 对公网域名返回 `198.18.x.x` fake-IP 段——**该地址不是真实服务器，不得据此改 host 或 DNS** |

## 2. 发布原则（含关键约束）

1. **镜像 tag 必须显式统一为 stamp，且不得假设 `:local`**：`deploy/compose.yaml` 中 api（含 `migrate`，两者共用 `API_IMAGE`）、web、worker、browser、ops-agent 的镜像均为 `${*_IMAGE:-dy-dashboard-<name>:local}`——**支持用环境变量覆盖**（`API_IMAGE`、`WEB_IMAGE`、`WORKER_IMAGE`、`BROWSER_IMAGE`、`OPS_AGENT_IMAGE`；`deploy/.env.example` 已列出这些键）。但生产 `production.env` 由服务器侧维护，**其现值未知**：若未设置这些键，`deploy.sh` 的 `compose build` 会把镜像构建并覆盖到 `:local`，旧镜像即被顶掉。因此：发布前必须先 `docker inspect` 实际运行容器得到真实 `.Image`（不可变 image ID），再把各服务显式统一到带 stamp 的 tag（如 `dy-dashboard-api:20261013T...`），并在构建前写入环境文件，使本次构建产物不再落到 `:local`。无 Registry 推送，故没有可按 SHA 拉取的发布物。
2. **本次修复尚未提交**：当前分支 `codex/dydata-102-fee-details`，HEAD `937ea04`，改动未提交。`deploy.sh` 默认 `git reset --hard <TARGET_SHA>` 并要求工作区干净；因此发布前必须先落地一个可被服务器获取的目标 SHA（提交+推送），或在受控流程下用 `SKIP_GIT_SYNC=true` + 已投递归档。**本预案不执行该动作。**
3. **迁移只前进**：`alembic upgrade` 前的 lineage preflight 为只读；本次 5 天恢复修复**不需要新迁移**（未新增列/表），因此预期不触发 schema 变更。若生产 `alembic_version` 在目标源码中缺失，脚本会在 `alembic upgrade` 前停止并打印迁移源码区间，**不得**用 `alembic stamp` 绕过。
4. worker 必须启动：`TENCENT_START_WORKER=true`；恢复依赖 scheduler 真实 tick 领取新生成的行。

## 3. 待发布物清单（本 worktree 未提交改动）

新增：
- `apps/worker/day_recovery.py`（独立代际恢复核心）
- `tests/test_job_recovery_and_evidence.py`（21 项恢复回归）
- `tests/test_api_meta_statement_months.py`、`tests/test_api_month_readiness.py`、`tests/test_month_close_readiness_alert.py`、`tests/test_store_cumulative_empty_month.py`、`tests/test_frontend_statement_month.py`
- `apps/web/src/utils/statementMonth.ts`
- `docs/devlog/20261013_dydata-102-day-recovery.md`
- `docs/plans/dydata-102-103-production-release-plan.md`（本预案）

修改（业务面）：
- `apps/worker/priority_scheduler.py`、`repositories.py`、`daily_task.py`、`priority_budget.py`、`month_close.py`
- `apps/api/dy_api/routes/operations.py`（recover 由 501 占位改为真实调度）、`_data.py`、`dashboard.py`、`meta.py`、`settlement_audit.py`、`settlement_audit_readonly.py`
- `apps/web/src/App.tsx`、`api/client.ts`、`AdminProductSyncPanel.tsx`、`FinanceFeePage.tsx`、`FinanceOrderDetailsPage.tsx`、`FinanceStoresPage.tsx`、`StoreSettlementPage.tsx`

修改（测试面）：`tests/test_api_account_permissions.py`、`test_api_dashboard.py`、`test_frontend_finance_contracts.py`、`test_frontend_store_finance_pages.py`、`test_month_close.py`、`test_priority_scheduler.py`、`test_worker_subprocess_recovery.py`

统计：25 个已跟踪文件改动（+1344/−107），10 个未跟踪新增（`git ls-files --others --exclude-standard` 实测）。

## 4. 发布前置门禁（缺一不可）

- [x] 相关测试集：Codex 已于另一进程独立验证 **206 passed / 8 skipped**（该进程**不得终止，也不得重复启动全量 pytest**）。
- [ ] 全量 `python -m pytest` 的完整退出码由该独立进程跑完后记录（**在其回报前不得记为通过**）。
- [x] `npm --prefix apps/web run build` 已通过（已有证据：Web build 通过）。
- [x] `git diff --check` 通过（本轮 EXIT=0）。
- [ ] 目标 SHA 已提交且服务器可 `git fetch` 到该 SHA。
- [ ] 发布前镜像基线已按第 5 节从实际运行容器导出（不可变 image ID + 统一 stamp tag）。
- [ ] SSH 通道恢复，且能读到远端 sshd banner。

发布前只读快照（必须留档，作为回滚与验收基线）。三条硬性要求：**（a）所有 psql 必须在容器内用 `sh -c` 展开 `$POSTGRES_USER`/`$POSTGRES_DB`**（这两个变量在 compose 传入的容器环境里，宿主机 shell 没有；不得把宿主 shell 的字面量当作库身份）；**（b）实际运行镜像必须 `docker inspect` 实际容器取 `.Image`**，不能只 `docker images | grep`、更不能假设 `:local`；**（c）本地构建镜像通常没有 `RepoDigests`，`--digests` 不能作为基线**。

为避免跨两层（宿主 shell → docker compose → 容器 sh）的变量与引号转义，统一改用**服务器上落文件 + `sh -c` 读取**的方式（下例把库身份变量留在单引号内、SQL 单引号不被宿主吃掉）：
```bash
# 1) 在服务器写一个只读 SQL 文件（SQL 内的单引号原样落盘，不由宿主 shell 处理）
ssh dydata-production 'cat > /tmp/dydata-check.sql' <<'SQL'
SELECT version_num FROM alembic_version;
SQL
# 2) 在容器内展开变量并执行（SQL 文本经 stdin 传入，无需宿主转义）
ssh dydata-production 'cd /opt/dy-dashboard/repo && sudo docker compose --env-file /opt/dy-dashboard/env/production.env -f deploy/compose.yaml exec -T postgres sh -c '"'"'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -f - < /tmp/dydata-check.sql'"'"''
```
若坚持单行内联，等价的单行形式是 `... exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT version_num FROM alembic_version"'`——宿主外层用单引号、容器内用双引号，**执行前先用 `... exec -T postgres sh -c 'echo "$POSTGRES_USER/$POSTGRES_DB"'` 确认容器内变量名与取值**。

发布前只读快照命令：
```bash
# 线上代码状态（只用于解释差异，不用于证明实际运行镜像）
ssh dydata-production 'cd /opt/dy-dashboard/repo && git rev-parse HEAD && git status --porcelain | head'
ssh dydata-production 'cat /opt/dy-dashboard/logs/last-deploy.json'
# 实际运行容器与镜像：compose 配置镜像引用、不可变 image ID、状态
ssh dydata-production 'cd /opt/dy-dashboard/repo && \
  for s in postgres api migrate worker web browser ops-agent proxy; do \
    cid=$(sudo docker compose --env-file /opt/dy-dashboard/env/production.env -f deploy/compose.yaml ps -q "$s"); \
    [ -n "$cid" ] || { echo "$s: no-container"; continue; }; \
    echo "$s: $(sudo docker inspect -f "{{.Config.Image}} {{.Image}} {{.State.Status}}" "$cid")"; \
  done'
# 镜像 tag→ID 对照：用于把「实际运行容器的 image ID」与现有 tag 互相定位（本地构建镜像通常没有 RepoDigests，digest 不可作为基线）
ssh dydata-production 'sudo docker images --no-trunc --format "{{.Repository}}:{{.Tag}} {{.ID}} {{.CreatedAt}}" | grep -E "dy-dashboard-(api|web|worker|browser|ops-agent)"'
# 运行态
ssh dydata-production 'cd /opt/dy-dashboard/repo && sudo docker compose --env-file /opt/dy-dashboard/env/production.env -f deploy/compose.yaml ps -a'
# 迁移版本：用上面第 1/2 步的同一「落文件 + 容器内读取」方式执行
#   SQL 文件内容为： SELECT version_num FROM alembic_version;
```
**线上/checkout 一致性核对**：`git rev-parse HEAD` 与 `last-deploy.json.sha` 只反映 checkout 与部署脚本的记录，**不能证明容器里实际运行的镜像 SHA**（`SKIP_GIT_SYNC`、构建失败后回滚、手工 `docker tag`/`compose up` 都会让三者脱节）。三者不一致时以**实际容器 `.Image`（不可变 image ID）+ 其 tag→ID 对照**为准，先解释差异再发布。

## 5. 备份与回滚

备份（`deploy.sh` 已内置，发布前确认产物存在）：
- 环境文件：`$LOG_DIR/backups/pre-production-cutover-<UTC>.env`（原脚本 `BACKUP_DIR=$LOG_DIR/backups`）。该备份发生在 `compose build` **之前**，因此它记录的是**发布前的 `*_IMAGE` 取值**（含“这些键原本不存在”这一事实），是回滚环境覆盖的依据。
- 数据库：`$LOG_DIR/backups/pre-migrate-<UTC>.dump`（`pg_dump --format=custom`，`test -s` 非空校验）

**发布前镜像基线（必须 `inspect` 实际运行容器，不能假设 `:local`）**：脚本不保留旧镜像，缺此步无法快速回滚。先取每个服务**容器实际引用的不可变 image ID**，再把它统一打上 rollback stamp tag：
```bash
ssh dydata-production 'cd /opt/dy-dashboard/repo && stamp=$(date -u +%Y%m%dT%H%M%SZ) && echo "stamp=$stamp" && \
  for s in api web worker browser ops-agent; do \
    cid=$(sudo docker compose --env-file /opt/dy-dashboard/env/production.env -f deploy/compose.yaml ps -q "$s"); \
    ref=$(sudo docker inspect -f "{{.Config.Image}}" "$cid"); id=$(sudo docker inspect -f "{{.Image}}" "$cid"); \
    echo "$s container_ref=$ref image_id=$id"; \
    sudo docker tag "$id" "dy-dashboard-$s:rollback-$stamp"; \
  done && \
  sudo docker images --no-trunc --format "{{.Repository}}:{{.Tag}} {{.ID}}" | grep dy-dashboard'
```
- 打 tag 时**以 `inspect` 得到的 image ID 为源**（而不是 `dy-dashboard-<name>:local` 这个名字）；同时记录原容器 ref 与 image ID，作为“发布前实际运行镜像”的唯一证据。
- 被保留的 tag 命名统一为 `rollback-<stamp>`；**同步记录每个服务实际镜像的 `rollback-<stamp>` ↔ image ID 对照表**并留档。

**发布前把本次构建的 tag 也统一到同一个 stamp**（否则 `compose build` 会覆盖 `:local`，旧镜像只剩 rollback tag）：在环境文件里显式声明各服务镜像键（写入时机在 `backup_environment_file` 之后、`compose build` 之前；示例值需替换为真实 stamp）。**这是服务器生产环境文件的改动（属生产动作），不在本轮执行范围**：
```text
API_IMAGE=dy-dashboard-api:<stamp>
WEB_IMAGE=dy-dashboard-web:<stamp>
WORKER_IMAGE=dy-dashboard-worker:<stamp>
BROWSER_IMAGE=dy-dashboard-browser:<stamp>
OPS_AGENT_IMAGE=dy-dashboard-ops-agent:<stamp>
```
注意 `api` 与 `migrate` 共用 `API_IMAGE`：本次发布的 `compose run --rm migrate` 与实际 API 容器因此指向同一个 stamp 镜像。

回滚：
1. **镜像回滚（无 schema 变更时首选）**：按**原 compose 文件 + 原环境文件**执行，只对镜像做显式覆盖并加 `--no-build`，**不得重建**：
   ```bash
   ssh dydata-production 'cd /opt/dy-dashboard/repo && stamp=<发布前记录的回滚 stamp> && \
     sudo API_IMAGE=dy-dashboard-api:rollback-$stamp WEB_IMAGE=dy-dashboard-web:rollback-$stamp \
          WORKER_IMAGE=dy-dashboard-worker:rollback-$stamp BROWSER_IMAGE=dy-dashboard-browser:rollback-$stamp \
          OPS_AGENT_IMAGE=dy-dashboard-ops-agent:rollback-$stamp \
       docker compose --env-file /opt/dy-dashboard/env/production.env -f deploy/compose.yaml \
       up -d --no-build --no-deps --force-recreate api web browser ops-agent worker'
   ```
   （等价做法：先把被备份的 `pre-production-cutover-*.env` 还原回环境文件，再用同一组显式覆盖执行同一条 `up -d --no-build`。）回滚对象应是 `rollback-<stamp>` 解析到的 image ID，并与第 5 节记录的对照表一致。
2. **代码回滚**：以发布前记录的旧 SHA 重跑 `deploy.sh <OLD_SHA>`（服务器 `git reset --hard` 回旧 SHA + **重建**）。重建会覆盖 `:local`/stamp tag，故仍需第 1 步的 rollback tag 兜底。**`git rev-parse HEAD` 与实际运行镜像 SHA 是两件事**：发布前实际运行的镜像只能由“`inspect` 到的 image ID + rollback tag 对照表”证明，不能用 checkout 状态或 `last-deploy.json` 代替。
3. **数据库回滚（仅在本次确有迁移且失败时）**：在 postgres 容器内展开变量并执行 `pg_restore --clean --if-exists --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <pre-migrate-*.dump>`；恢复后必须重新执行 lineage 校验。因本次无新迁移，预期用不到。
4. 回滚后重跑 `deploy.sh` 内同款 smoke：`/`、`/api/v1/auth/me`、CLI device authorization、`/mcp` 401、agent manifest 含 `"environment":"production"`。

## 6. 失败日期定向恢复（连接与技术门禁满足后执行）

目标：2026-09 的 09-14、09-16、09-20、09-25、09-28 五天，外加先只读核对 2026-10-09 的当前状态。

只读步（先做，不改数据）。沿用第 4 节的“服务器落 SQL 文件 + 容器内 `sh -c` 读取”方式，避免跨层引号转义；**变量必须在容器内展开，SQL 的 `DATE` 单引号字面量不能被宿主 shell 吃掉**：
```bash
# 1) 落只读查询文件（此处单引号原样写入服务器，无需宿主转义）
ssh dydata-production 'cat > /tmp/dydata102-jobruns.sql' <<'SQL'
SELECT business_date, job_kind, status, attempt_count, max_attempts, config_version, error_code
  FROM job_runs
 WHERE business_date IN (DATE '2026-09-14', DATE '2026-09-16', DATE '2026-09-20',
                        DATE '2026-09-25', DATE '2026-09-28', DATE '2026-10-09')
 ORDER BY business_date, job_kind, config_version;
SQL
# 2) 容器内展开库身份变量并执行（只读）
ssh dydata-production 'cd /opt/dy-dashboard/repo && sudo docker compose --env-file /opt/dy-dashboard/env/production.env -f deploy/compose.yaml exec -T postgres sh -c '"'"'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -f - < /tmp/dydata102-jobruns.sql'"'"''
```
单行内联的等价形式（宿主外层单引号、容器内双引号、SQL 字面量按 `'\''` 转义）也可用，但**执行前必须先用 `... exec -T postgres sh -c 'echo "$POSTGRES_USER/$POSTGRES_DB"'` 确认容器内变量名与取值**，不得假设宿主机上存在这两个变量。
**字段核对（已按当前源码核实 `apps/api/dy_api/models.py` 的 `JobRun`/`job_runs`）**：`business_date`、`job_kind`、`status`、`attempt_count`、`max_attempts`、`config_version`、`error_code` 均为真实列；`parent_job_id`、`data_source`、`window_start`、`window_end`、`metadata_json`（JSON）也在同一模型内。`job_kind` 允许值为 `range_sync`/`parent_sync`/`date_sync`/`finalize`/`product_sync`；`status` 允许值含 `pending`/`queued`/`running`/`retry_wait`/`success`/`succeeded`/`partial`/`failed`/`cancelled`；`max_attempts` 约束在 1–3。若需改查语句，先按该模型核对列名，**不得凭猜测写列**。

核对要点：每日 `range_sync` 是否 `pending`（生产形态）、是否恰有 1 个 `date_sync` 且 `failed` 且 `attempt_count>=max_attempts`、`parent_sync` 是否已完成、是否已存在 `priority-daily-v1-recovery-%` 行（`config_version` 前缀来自 `day_recovery.RECOVERY_CONFIG_PREFIX`，基数 `PRIORITY_CONFIG_VERSION = "priority-daily-v1"`；存在则不得再建新代，每日最多 2 代）。

恢复调用（已按当前源码核实注册路径与鉴权）：路由为 `operations.router` 挂载在 `prefix="/api/v1/admin/operations"`，端点为 `POST /jobs/{job_id}/recover`，完整路径 **`/api/v1/admin/operations/jobs/{job_id}/recover`**；鉴权为 `Depends(get_current_super_admin)`（= 环境配置的最高管理员，非最高管理员返回 **403**），并额外执行 `_require_trusted_origin`（`Sec-Fetch-Site` 非 `same-origin`/`same-site`/`none` 时 403；`Origin` 非本站/非 `DY_API_CORS_ORIGINS` 时 403）。**请求体是 `AdminControlIntentRequest`，只接受 `reason` 一个字段（1–512 字符，`extra="forbid"`）**，响应包在 `{"data": ..., "meta": ...}` 内：
```bash
# 逐日一对一步骤，先取该日 all-target range parent 的 job_id，再调用 recover
curl -sS -X POST "https://<生产域名>/api/v1/admin/operations/jobs/<RANGE_PARENT_JOB_ID>/recover" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: dydata102-recover-2026-09-14-a" \
  -H "Origin: https://<生产域名>" \
  -d '{"reason":"repair 2026-09-14 date_sync 3/3 exhausted after window fix"}' \
  --cookie "<最高管理员会话 cookie>"
```
- 幂等：同一 `Idempotency-Key` 重复调用返回同一代（控制事件键为 `admin-recover:<sha256(Idempotency-Key)>`）；`Idempotency-Key` 长度需 16–128，否则 422。同一密钥指向另一天/另一计划行时返回 **409**（拒绝跨日复用证据）。
- 失败重试：换第二个密钥（最多 2 代）；第 3 次应返回 409（“recovery generation budget exhausted for this day”），不得绕过。
- 语义约束（均由 `day_recovery.DayRecoveryNotAllowed` → **409** 表达）：只允许恢复 **all-target 的 range parent**；被取消的计划、仍有 pending pause 请求的计划、仍持有活跃 lease 的计划、窗口不完整或缺 source identity 的计划一律拒绝；“pending 但 date child 已 3/3 失败且 parent_sync 已完成且无活跃 lease”的阻塞形态可恢复；`success`/仍在运行的计划被拒绝；**recovery 代本身不可再被恢复**。
- 调用后由 scheduler 真实 tick 领取新代并重跑；**恢复未完成或失败时月结必须继续 fail-closed**。
- 原始失败日志全文需脱敏后再留档（去除凭据、cookie、连接串、内网地址、个人路径）。

## 7. 九月验收（只读）

1. 月结 watermark：`month_close` 对 `2026-09` 的 readiness 由 `watermark_incomplete` 转为可派发；`ensure_month_close_job` 产出对应 watermark 版本化任务。
2. 单月口径：`/finance/promotion?month=2026-09` 的推广费总额、已确认、待开票、已开票、审核通过已结算，与来源冻结行数/金额逐项对齐。
3. 累计口径：正式账期累计额与单月之和一致（此前累计 ¥11,700.92 不能证明 9 月存在佣金来源）。
4. 明细与导出：`/finance/orders/promotion?month=2026-09` 行数、金额与导出行数/金额一致；导出与页面同源。
5. 保护不被绕过：已确认/锁账/发票/异议记录不得因恢复或月结被改写。
6. 证据留档：行数、金额、SQL/导出证据、排除项与异常记录原因（含 5 天恢复前后的对比）。

## 8. 当前阻塞点与解除条件

**真实阻塞点（技术门禁，非授权问题）**：本机到 `124.222.59.236:22` 收不到服务端 SSH banner，导致所有需要服务器或控制台的生产动作（只读核验、发布、补跑）都无法开始。已观测事实：TCP 连接可建立、12 秒内无服务端 banner、无认证/密钥交换报错、无驻留连接可复用。**同一路径上 `ssh.github.com:443` 能读到 banner 只能证明本机代理可承载 SSH over 443，不能排除 22 端口链路策略差异，因此既不构成“已排除本机侧原因”，也不构成远端 sshd 故障的证据**；用户无法访问云控制台，没有旁路通道可证伪任一方向。**根因未定；不再重复网络探测。**

解除条件（任一）：
- 运维/云控制台侧恢复该实例的 SSH 可达性（重启 sshd、安全组/网络策略、实例状态）；
- 开放一个可用的受控管理入口（云控制台或新的受控连接路径），由用户授权后使用，**不新建凭据**。

**授权状态**：用户已授权 DYDATA-102/103 的生产发布与 5 天定向恢复；**解除条件满足后即可执行生产动作，不需要用户再次验收**。当前唯一缺口是技术通道（SSH banner）与第 4 节的 pytest 记录。

解除后只读核验顺序：SSH banner → `/opt/dy-dashboard` 布局与 `last-deploy.json`（仅作说明性证据）→ 实际容器与镜像（`inspect` image ID + rollback tag 对照）→ `alembic_version` → 14/16/20/25/28 及 10-09 的 JobRun 行 → 5 天失败日志（脱敏）。

## 9. 发布范围与远端差异（2026-10-13 实测，已 fetch 后核对）

| 项 | 事实 |
| --- | --- |
| `origin/main`（fetch 后） | `9cb1363` `docs: record ranking retention deployment acceptance [skip ci]`（2026-10-09 20:59 +0800） |
| 生产已部署 SHA | `08cd321`（即 PR #49 磁盘/榜单保留合并；已在 main 上，晚于本 worktree 的分叉点） |
| 发布分支 HEAD | `937ea04`（2026-10-10 16:57 +0800）——**分叉点早于 main**：相对真实 main 为「领先 1、落后 15」 |
| 结论 | 交付只能是 `937ea04` **rebase/merge 到当前 main 之上**后的新 SHA；不得从旧分叉点直接发布，否则会回退榜单保留、0061/0062 迁移与 `deploy.sh` 备份保留逻辑 |
| 该提交内容 | 23 文件 / +2740−14：`settlement_audit_readonly.py`、`month_close.py`、`settlement*.py`、`queued_jobs.py`、`pipeline.py`、`scheduler.py` 及 8 个测试 |
| 未提交在途改动 | 25 个已跟踪文件 + 10 个未跟踪新增（含 `apps/worker/day_recovery.py`）。**关键耦合**：在途的 `operations.py`/`daily_task.py`/`priority_budget.py`/`priority_scheduler.py` 导入 `day_recovery`，而已提交的 937ea04 不导入；两者必须作为**一个原子发布包**，否则任一半都会使构建/运行失败 |
| 与 main 的冲突面 | 仅 `docs/plans/execution-plan.md`（`git merge-tree` 实测 CONFLICT）；其余文件族不重叠（main 侧为 ranking/retention/backup，本侧为 settlement/month-close）。合并时保留双方功能与迁移 0061/0062 及备份保留策略 |
| 已有正式入口 | 合并到 main 后由既有 `tencent-lighthouse-deploy.yml`（verify 全门禁 + deploy）发布；`08cd321` 携带的 `deploy.sh` 备份保留与 `pg_restore` 校验逻辑保持不动 |

## 10. 只读诊断入口（本分支新增，待 Codex 验收后 dispatch）

新增 `.github/workflows/dydata-102-103-readonly-diagnosis.yml`（单 job，**无 build/部署/写入/API 模式**），只读产出：实际运行容器不可变 image ID、`alembic_version`、六个固定日期（09-14/16/20/25/28 + 10-09）的 `job_runs`、已持久化的失败 attempt 字段（`exit_type`/`exit_code`/`error_code`/截断后的 `error_summary`）、已存在的 recovery 代、窗口内 range parent **候选**（资格仍需应用侧校验）、2026-09 有效源行数与费用分项（`settlement_statement` 当月 `is_current` 行、`settlement_fee_result` join `settlement_fee_result_current`、`raw_douyin_verify_records` 最新有效非取消 verify 行）。

安全约束：每条 SQL 都在 `BEGIN READ ONLY` 事务内；`set -euo pipefail` 且 psql 先落盘再判状态，失败不被掩码管道吞掉；`TENCENT_KNOWN_HOSTS` 为必需 secret 且 `StrictHostKeyChecking=yes`、启动前用 `ssh-keygen -F` 校验 pinned host key；错误文本在服务器侧脱敏后才进入日志；masking gate 失败只打印固定错误并扣留报告；不输出容器自由文本日志或任意 payload。

**当前状态：未 dispatch、未部署、未推送生产。** 等 Codex 对本文件的 diff 技术验收后，再由其在诊断分支 dispatch。
