# DYDATA-104 本轮 PostgreSQL CI 覆盖

2026-10-27，隔离基线 `cabc08f`。仅调整 CI/CD、Tencent Lighthouse 的 verify 工作流及相应静态验证；触发条件、权限、部署依赖和部署命令保持原样，没有 push、merge 或部署。

## 已核验的实际连接合同

| 测试 | 实际变量 / 数据库约束 | 工作流接线 |
|---|---|---|
| `test_dydata104_finance_state_matrix.py` | `DYDATA_FINANCE_TEST_DATABASE_URL`；loopback、DB以`_test`结尾 | 新建 `dydata_delivery_test`，整份矩阵以真实PG运行，含逐行冻结预览、状态保护和HTTP并发 |
| `test_historical_fee_correction_postgres.py` | `DYDATA_HISTORICAL_FEE_TEST_DATABASE_URL`；loopback、DB必须是`dydata_delivery_test` | 与财务共享专用测试DB，各fixture使用不同UUID schema，覆盖事务回滚/幂等/竞争和隔离级别拒绝 |
| `test_protected_billing_authority_postgres.py` | 已读取源码：`DYDATA_PROTECTED_TEST_DATABASE_URL`，loopback、DB以`_test`结尾 | 与财务/历史同`dydata_delivery_test`，每case为`protected_authority_<uuid>` schema；整个文件运行，含core7例及publication-only coordinator4例 |
| `test_month_close_auto_bootstrap_postgres.py` | 复用 `test_protected_billing_authority_postgres.postgres_engine`，实际读取 `DYDATA_PROTECTED_TEST_DATABASE_URL` | 整文件加入同一 `dydata_delivery_test` 门禁；5 个执行场景各用 UUID schema，收据逐名要求成功 |
| `test_missing_fee_repair_postgres.py` | `DYDATA_MISSING_FEE_TEST_DATABASE_URL`；loopback、DB 以 `_test` 结尾 | 整文件加入现有 `dydata_delivery_test`；38 个实际收集场景均要求成功收据，各 fixture 使用独立 UUID Schema |
| `test_account_qualification_postgres.py` | 复用 `test_dashboard_publication_migration.full_pg_stack`，实际读取`DYDATA_PUBLICATION_TEST_DATABASE_URL` | 沿用先前创建的`dydata_publication_test`，显式运行Alembic、不可变证据、并发冻结和自动准入预算 |
| `test_product_sync_completeness_postgres.py`、`test_product_sync_sku_lookup_postgres.py` | 复用publication finance PG fixture，同样读取`DYDATA_PUBLICATION_TEST_DATABASE_URL` | 同一显式PG门禁覆盖新增完整性及既有精确SKU查询 |

本基线所有测试中不存在 `DYDATA_MONTHEND_TEST_DATABASE_URL`；不能仅设置该名字就声称月末PG测试已启用。如后续月末fixture改用专用变量，应随测试提交同步接线和本静态清单。

新增PG步骤在已有publication测试DB创建之后执行，30分钟限时。真实浏览器步骤在npm依赖和Chromium安装后执行，15分钟限时，显式运行`test_dydata104_finance_preview_browser.py`及`test_dydata105_buttons_browser.py`；成功响应仍使用这些测试原有的真实本地FastAPI/合成数据库。

## 防止静默跳过

两条显式门禁均输出JUnit，随后读取收据并拒绝：零测试、任何skip、failure或error。不依赖全量pytest的退出码推断opt-in PG已经执行，也不设置`continue-on-error`。日志只输出测试结果，不回显连接串或密钥。

`actions/upload-artifact@v4`以`always()`保存两份JUnit；若早期安装失败尚未生成文件，仅显示无收据提示，原失败保持。原全量pytest继续保留，显式门禁与全量扫描分开说明。

原publication静态测试改按其专有步骤名定位，避免新增合法publication消费者让旧“仅一个env步骤”假设误报。

## 本地证据与边界

- `python -m pytest -q tests/test_dydata104_ci_coverage.py tests/test_deploy_publications.py tests/test_deploy_compose_config.py tests/test_project_governance.py --tb=short`：69 passed，10.81秒，exit 0。
- 新静态测试实际执行工作流中的JUnit守卫，分别验证通过、空集合、跳过、失败和错误收据；同时校验数据库约束、前置顺序、显式测试清单、只读权限和deploy依赖。
- YAML通过PyYAML真实解析；shell `run`段另用Git Bash `bash -n`验证。没有把语法或静态检查表述为GitHub已执行。
- 未执行远端CI、容器服务启动或生产操作。本机PG额外烟测结果由主线程交接回执单列，不代替工作流在精确提交上的实际运行。
- protected-authority最终文件/变量和coordinator场景已读取`faf0ad6562c9430e7f639799b6f471cf20a36e3b`源码并与财务worker确认，收口增量见下节。本单元未重跑其11例真实PG，不把协作者证据写成独立执行。
- 技能usage/audit仅写宿主规定的本机日志；工作流memory文件未更新。

## Publication-only coordinator CI 收口

收口隔离基线为release树 `4f0f2a1`；原CI提交已由主线程分别合入`932f4d4`/`843ba4e`。同一CI工作目录切出独立分支继续，只改workflow、静态门禁和本文档，不改coordinator。

最终coordinator提交 `faf0ad6562c9430e7f639799b6f471cf20a36e3b` 沿用已显式接线的PG文件和变量，不重复添加另一份路径。两份workflow继续整文件运行、不加`-k/-m/--deselect/--ignore`，静态契约验证文件存在、精确清单及两份PG门禁完全等价。新SQLite文件 `test_settlement_publication_only.py` 由现有全量pytest自动发现。

在原非空/零skip收据守卫之后，新增coordinator场景存在性守卫，要求JUnit中确实包含：

- `test_postgres_publication_only_complete_apply[metadata]`
- `test_postgres_publication_only_complete_apply[migration]`
- `test_postgres_publication_only_atomic_billing_rollback`
- `test_postgres_publication_only_refuses_existing_heavy_claim_lock`

即使旧core7例通过，遗漏任一coordinator场景也会失败；同时保留原零skip/failure/error检查。静态测试执行精确内联守卫，分别构造完整收据和缺少每个场景的非空成功收据验证该行为。主线程须同时合入上述coordinator提交，不能用仅core的版本发布。

本次收口验证：`python -m pytest -q tests/test_dydata104_ci_coverage.py tests/test_deploy_publications.py --tb=short` 为 **45 passed，3.99秒，exit 0**；两份YAML解析、58段 `bash -n` 和 `git diff --check` 通过。与`4f0f2a1`逐字段比对，触发、权限、并发及deploy/railway release任务完全一致。未运行全仓或重跑coordinator真实PG；其最终集成PG由主线程独立回收。


## 自动建账 PostgreSQL CI 收口

2026-10-27，本增量从集成基线 `1eca0abe321fa594a9fd6c534cfcad7fc6151875` 新建隔离工作树和分支，未复用或重置旧 CI 工作树。写集仅为两份 workflow、本静态测试和本文档；本任务无 foundation 漂移。治理锁、全局文件校验（0 errors / 0 warnings）、S4 路由、T3.1 计划一致性、环境及执行上下文检查均通过。

两条 PostgreSQL 显式门禁保留原 6 个测试文件、非空且零 skip/failure/error 的 JUnit 守卫及 coordinator 的 4 个必需场景，新增整份 `tests/test_month_close_auto_bootstrap_postgres.py`，不添加选择性过滤。该文件直接复用受保护账单的 PostgreSQL fixture，因此沿用已接线的 `DYDATA_PROTECTED_TEST_DATABASE_URL` 和专用 `dydata_delivery_test` 数据库，不创建另一套变量或数据库。

独立的 bootstrap 收据守卫检查模块归属及成功执行，要求以下 5 个场景全部出现：

- `test_postgres_automatic_bootstrap_rebuilds_and_publishes_real_full_month[False]`
- `test_postgres_automatic_bootstrap_rebuilds_and_publishes_real_full_month[True]`
- `test_postgres_concurrent_ticks_share_frozen_input_job_without_resetting_attempts`
- `test_postgres_unqualified_legacy_current_rolls_back_month_economics`
- `test_postgres_full_without_active_rolls_back_unknown_october_aggregates`

静态测试执行 workflow 的原始内联代码：完整收据通过，分别缺少每个场景、同名但来自其他模块，以及场景含 skipped/failure/error 子节点的收据均拒绝。既有 coordinator 断言继续独立执行，后续新增 PG 文件及其场景合同可按同样方式追加，不修改或代替既有合同。尚在其他工作树开发的 missing-fee PG 服务未加入；待其实际文件、fixture 变量和场景落定后由集成负责人补齐，不预造测试名。

本次独立验证：

- `python -m pytest -q tests/test_dydata104_ci_coverage.py tests/test_deploy_publications.py tests/test_deploy_compose_config.py tests/test_project_governance.py --tb=short`：**100 passed，14.94 秒，exit 0**。
- `python -m pytest --collect-only -q tests/test_month_close_auto_bootstrap_postgres.py`：**5 tests collected，7.36 秒，exit 0**，名称与上列收据要求一致；此命令只证明收集，不冒充真实 PG 执行。
- PyYAML 解析两份工作流，Git Bash `bash -n` 验证全部 **58 段** run，exit 0；与基线解析对象逐字段比对，只有指定 PG 步骤的 run 字段改变，触发、权限、并发、verify 其余字段以及全部部署/release 任务保持一致。
- `git diff --check` 通过。未重跑真实 PG、全仓财务或前端构建；主线程已独立验证 bootstrap PG，本增量不将其结果冒充本工作树执行。最终集成提交的 GitHub CI、PG、镜像、部署与生产验收仍由主线程回收。
- 技能 usage/audit 按宿主规则写入本机日志；工作流 memory 文件未更新。


## 缺费修复 PostgreSQL 与真实浏览器镜像门禁

2026-10-27，本增量从集成提交 `62c427c` 新建隔离工作树，未改先前 CI 或重核销修复提交。仅修改两份工作流、静态契约测试与本文档；本任务无 foundation 漂移。

### 缺费修复 PostgreSQL

两份既有显式 PG 门禁新增整份 `tests/test_missing_fee_repair_postgres.py`，接线实际 fixture 读取的 `DYDATA_MISSING_FEE_TEST_DATABASE_URL`，沿用专用 `dydata_delivery_test`，不另建数据库。原 7 文件、5 个 bootstrap 场景、4 个 coordinator 场景及非空/零 skip/failure/error 守卫均保留。

本次从实际 pytest 收集结果建立 38 个必需成功场景的清单，涵盖：

- `test_postgres_apply_commit_readback_and_exact_idempotence[metadata]` / `[migration]` 的真实提交、独立连接回读、幂等重放和重放输入/输出漂移拒绝。
- `test_postgres_full_dependency_drift_rejects_zero_writes[...]` 的 9 类依赖漂移，以及 `test_postgres_unexpected_writer_outputs_roll_back_entire_batch[...]` 的 4 类全批回滚。
- 来源 writer、heavy claim、relation phantom、已有写事务超时、事务特征与固定超时、剩余 wall budget 限制，以及历史费用、确认/锁账/发票/异议等保护拒绝。
- 10/20/50/373 券的代表性预算收据；这些场景允许记录按合同预算拒绝，测试成功不代表相应规模已实际入账或生产预算已验收。

缺费收据守卫要求正确模块、完整场景名称及成功结果；即使其他 PG 文件通过，缺少任一场景也拒绝。本增量只核验源码与收集结果，没有并行重跑 PG；该文件最终真实 PG 运行由负责 worker 与主线程独立回收。

### 浏览器镜像兼容性

两份工作流在 `Build Browser Docker image` 后立即新增同一门禁，均使用刚构建的 `dy-dashboard-browser:ci`：

1. 在 `--network none` 的实际镜像内检查 `PIL` / `PIL.Image` 导入路径来自 `/usr/local/lib`，包元数据与运行时 Pillow 版本均为 `13.0.0`。
2. 通过 `--entrypoint python3` 离线执行整份 `test_browser_image_dependency_compat.py`。仅将该测试文件只读挂载到 `/tmp/`，将现有 `logs/ci` 挂载为收据输出目录；不挂载宿主源码或依赖，不加载宿主 conftest。
3. 要求 `dydata104-browser-image.xml` 恰好 3 tests，0 skipped / failures / errors，且 PNG、TIFF 与 Requests/urllib3 普通/分块响应测试三个成功 case 均存在。

宿主全仓扫描中 Pillow 可选导致的跳过不能满足该门禁。新收据通过独立 `always()` artifact 步骤持久保存，因为旧收据上传位于镜像构建之前；旧收据步骤保持原位置与内容。

### 本次独立验证

- `python -m pytest -q tests/test_dydata104_ci_coverage.py tests/test_deploy_publications.py tests/test_deploy_compose_config.py tests/test_project_governance.py --tb=short`：**219 passed，14.11 秒，exit 0**。测试实际执行内联守卫，覆盖缺少逐个 PG/镜像 case、错误模块、case skip/failure/error，以及镜像零/少/多测试、aggregate skip/failure/error 等拒绝路径。
- `python -m pytest --collect-only -q tests/test_missing_fee_repair_postgres.py tests/test_browser_image_dependency_compat.py`：**41 tests collected，1.35 秒，exit 0**（38 PG＋3 镜像兼容）。收集不代替真实 PG 执行。
- 两份 YAML 经 PyYAML 解析，全部 **60 段 run** 经 Git Bash `bash -n`，exit 0。与基线逐字段比对，只增加两项镜像验证/收据步骤及修改 PG 步骤的新增 env/run；触发、权限、并发、全部部署/release 任务和其余 verify 步骤保持一致。
- 将精确工作流 Docker 命令仅替换镜像 tag 为已存在本地候选 `dydata104-browser-deps:oct27`，镜像 ID 为 `sha256:6a1c23aff303ca92901d66a0a3556ecd887b9ebd2db459a456b3312df581ee41`：Pillow 13.0.0 版本/路径检查通过，**3 passed，0.78 秒，exit 0**；实际 JUnit 为 3/0 skipped/0 failures/0 errors，两个精确内联收据守卫均通过。挂载使用本工作树的实际测试文件及输出目录，外部网络关闭。
- 上项是已有本地候选镜像的命令与运行兼容验证，**不是本次最终 HEAD 镜像构建或 GitHub CI 证据**；没有声称重新构建、远端放行或生产发布。最终镜像构建、PG、CI 与部署由主线程在集成提交回收。
- 治理锁、全局文件（0 errors / 0 warnings）、S4 路由、T3.1 计划一致性、环境与执行上下文均通过；`git diff --check` 通过。未修改业务或依赖、未推送；工作流 memory 文件未更新。


2026-10-27，PR67 集成基线 `3d6e7db36f0dbfa2e427a51275d4d1fb3709bab7` 的运行 `40516359910` 在 `test_postgres_200_stores_12_months_build_budget` 因锁账 fixture 缺少不可变来源而失败（静态发布 PG 步骤 1 failed / 109 passed / 4 skipped；后续专用 PG、浏览器、全仓及四镜像均未执行，不计通过）。新隔离分支先独立真实 PG 红测 **1 failed，12.89 秒，exit 1**，随后仅为该性能测试的 96 个 status=4 header / 192 个 line 补齐 192 个准确 FeeResult、192 个 StatementEntry，以及计数/基数/费额/费率快照；不改业务保护、不降状态，200 店/12 月/2400 聚合与所有原预算、结果断言保留，其他测试/helper 函数内容一致。受控本地专用测试数据库仅映射 `DYDATA_PUBLICATION_TEST_DATABASE_URL`，整文件 `python -m pytest -q -s tests/test_dashboard_publication_finance_postgres.py --tb=short` 为 **22 passed / 0 skipped，195.64 秒，exit 0**；规模实测：结算构建 **3.032 秒 / 647 SQL / 7403 rows**、读取 **0.040 秒 / 14 SQL**，财务构建 **0.427 秒 / 95 SQL / 2603 rows**、读取 **0.021 秒 / 7 SQL**，峰值 **243.7 MiB**，均满足原 180 秒构建、1 秒读取、1000 SQL、768 MiB 断言。治理锁、全局文件、S4/T3.1 计划与上下文及 `git diff --check` 通过，本任务无 foundation 漂移；这是本地 PG 修复证据，PR 最终提交仍须重新通过完整 CI，未重跑/取消原 CI 或合并/部署。


2026-10-27，集成 `e31e52f0087dc0cadef2f1687809ff049f79ef07` / PR67 运行 `40518603262` 已结束为 failure：专用 PG 为 **147 passed / 1 failed / 0 skipped，317.70 秒**，唯一失败是 `test_account_qualification_postgres.py::test_real_postgres_migration_atomicity_immutability_and_concurrent_freeze` 在预期合成导出错误之前尝试写 `/run/browser`，触发非 root 宿主 `PermissionError(13)`；原始失败日志、artifact `12742026224` 及 148-case JUnit 已保存到忽略的观察目录。4 coordinator、5 bootstrap 与 38 missing-fee 成功收据均独立核对，但整体门禁不计通过，后续浏览器、全仓及四镜像未执行。本修复从该精确集成提交新建隔离分支，仅让该 PG 测试通过 `tmp_path` 同时 monkeypatch `active_marker.FIXED_BROWSER_EXPORT_ACTIVE_FILE` 和 `BROWSER_EXPORT_ACTIVE_FILE`，沿既有测试惯例执行真实 marker 协议，并增加异常与回滚成功后的清理断言；不改生产代码/固定路径/守卫，不提权、不跳过。已有本地候选镜像以 Linux UID 1000、外网关闭、只读挂载当前原始 marker 模块，独立复现默认路径 PermissionError 并验证临时路径的真实获取/清理成功；这仅证明 Linux marker 路径行为，不冒充整份 PG 在 Linux 执行。共享项目 Python 对专用 loopback PG 的该测试与 `tests/test_worker_resource_metrics.py` 合并运行 `python -m pytest -q -ra tests/test_account_qualification_postgres.py tests/test_worker_resource_metrics.py --tb=short` 为 **14 passed / 0 skipped，20.13 秒，exit 0**，实际 JUnit 14/0 failures/0 errors/0 skipped；其中 1 项真实 PG 完整执行原有四线程冻结、不可变证据、导出失败持久记录、调用者回滚、12 并发准入预算以及有数据迁移降级拒绝断言，原有全部 assert/raises 合同经 AST 比对保留，另 13 项 marker/资源测试通过。治理与 `git diff --check` 通过；本任务无 foundation 漂移，未重跑已通过的 147 项、未推送/重跑远端 CI/合并/部署，最终 CI 仍由主线程在新集成提交验证。
