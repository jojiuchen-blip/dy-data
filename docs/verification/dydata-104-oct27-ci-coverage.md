# DYDATA-104 本轮 PostgreSQL CI 覆盖

2026-10-27，隔离基线 `cabc08f`。仅调整 CI/CD、Tencent Lighthouse 的 verify 工作流及相应静态验证；触发条件、权限、部署依赖和部署命令保持原样，没有 push、merge 或部署。

## 已核验的实际连接合同

| 测试 | 实际变量 / 数据库约束 | 工作流接线 |
|---|---|---|
| `test_dydata104_finance_state_matrix.py` | `DYDATA_FINANCE_TEST_DATABASE_URL`；loopback、DB以`_test`结尾 | 新建 `dydata_delivery_test`，整份矩阵以真实PG运行，含逐行冻结预览、状态保护和HTTP并发 |
| `test_historical_fee_correction_postgres.py` | `DYDATA_HISTORICAL_FEE_TEST_DATABASE_URL`；loopback、DB必须是`dydata_delivery_test` | 与财务共享专用测试DB，各fixture使用不同UUID schema，覆盖事务回滚/幂等/竞争和隔离级别拒绝 |
| `test_protected_billing_authority_postgres.py`（协作者增量依赖） | 财务worker确认只读`DYDATA_PROTECTED_TEST_DATABASE_URL`，loopback、DB以`_test`结尾 | 与财务/历史同`dydata_delivery_test`，每case为`protected_authority_<uuid>` schema；本CI树暂不包含该测试，实现与PG结果由财务worker交主线程合并 |
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
- protected-authority路径和变量已向财务worker确认并加入门禁。主线程必须同时合入对应测试；文件缺失时pytest收集会明确失败，不会静默跳过。本单元尚未读取该未交付源码或宣称其PG测试通过。
- 技能usage/audit仅写宿主规定的本机日志；工作流memory文件未更新。
