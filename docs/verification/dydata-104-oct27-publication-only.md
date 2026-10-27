# DYDATA-104：只发布既有费用 authority 的受控入口

## 实现范围

`apps/worker/settlement_publication_only.py` 提供只读 preview 与 reviewed apply；`scripts/ops/publish_settlement_authority.py` 默认 dry-run。没有调用 `rebuild_settlement`、`rebuild_dual_fee_results`、月度 materialize 或普通 month rebuild。费用结果、current pointers、调整、确认、票据及受保护 bill/entries/lines 保持原值；未保护 bill 仍按现有 `generate_pending_statements` 合同创建/追加版本。

此入口目前明确拒绝任何触及 status4 的请求/闭包月份，未新增锁账绕过参数。支持 status2 但已有单方向确认的整单保护。没有执行生产预览或 apply，不能将合成通过当作实际 379 entries 的生产恢复验收。

## Preview / apply 合同

- `--month YYYY-MM` 可重复；必须显式指定正式月份。请求月先通过共同 authority 月份闭包，再同时用于 capture、build、hash。
- 默认返回全月每店 `expected_headers`：双方 original/adjustment/net 金额、source_count、当前 bill ID/version、是否受保护、action（protected/unchanged/version/create）、expected_version。`will_version_unprotected` 明确将创建或版本化的未保护 bill。
- `preview_hash` 绑定协议、active published base、请求及闭包月份、全量 authority sources 的所有冻结展示/经济字段、bill ID/version/status/保护状态/金额/快照、确认/争议/票据依赖的受控字段。来源明细和票据文件不写 stdout；内部 hash 不读取文件正文。
- Preview 仅加事务读锁，session 关闭释放，不创建 job、bundle、fee、bill 或 audit。
- `--apply --preview-hash <exact hash>` 必须引用已审阅 preview。正常 heavy claim advisory lock、其他 heavy job、cooldown、资源准入及 claim/lease 均复用；申请、claim 与第一次 hash 重验处于同一事务，拒绝会回滚新 job。资源 monitor 启动时最多等 90 秒获得真实 ALLOW，未就绪不绕过门禁。
- apply 直接使用 `refresh_active_settlement_lineage`：首 capture 锁后重验 hash→冻结新 job/generation bundle→build→ready→再次 job/active/slot/bill 锁后 capture 与 hash 重验→正常 audited publish + pending bill generation 同一事务。任一 billing blocked 或晚到确认/源变化均不切换 active pointer，不提交 bill 版本切换。
- 完成后正常 finish job。失败保留受控失败/新 preview 要求，不允许恢复 worker 将 publication-only job 路由至费用重算；普通 full/month worker 都识别元数据并分派同一专用 publication runner。
- 旧 preview 在发布后或任何相关状态变化后失效；再次 apply 旧 hash 不创建第二个 job。

## 操作示例

仅在主线程完成实际来源、金额、版本与维护窗口审批后使用配置好的目标数据库环境；示例不包含连接字符串。

```powershell
python scripts/ops/publish_settlement_authority.py --month 2026-08 --month 2026-09
python scripts/ops/publish_settlement_authority.py --month 2026-08 --month 2026-09 --apply --preview-hash <reviewed-preview-hash>
```

Dry-run 输出的是完整闭包月份金额，不能只审阅 128 个漂移目标；保护账单其余 entries 同样属于 authority。此入口不会修复 359 分差额或改变其归属。

## 合成验证

`tests/test_settlement_publication_only.py`：真实 preview 无写入；完整 apply 不调用 fee rebuild；仅未保护 bill 追加版本；保护 financial rows、fee/current/adjustment/票据全行指纹不变；monthly/monthly ranking/cumulative ranking 金额与保护账单一致；实际 FIN03 list 与 CSV 路由 ID/金额/行类型及冻结 product/SKU/NULL rate 一致；旧 preview/source/确认/base 改变拒绝；ready 后确认变化在最终锁后重验拒绝；billing blocked 原子回滚；status4 拒绝；heavy/resource 门禁；默认 CLI dry-run、apply 缺 hash 与资源尚未就绪不写 job；普通 worker 恢复分派。

`tests/test_protected_billing_authority_postgres.py` 新增四项：真实 PostgreSQL metadata/full Alembic migration 的完整 apply、billing blocked 原子回滚、另连接持有 heavy advisory lock 时拒绝。数据库为专用 loopback 测试库，每 test UUID schema，未接触生产。

已执行相关 authority/month/generation/publication-only 合计 **140 passed**；新增 PostgreSQL 四项 **4 passed / 87.72s**。追加真实 HTTP CSV 与全金融底层表指纹后，PostgreSQL metadata/full-migration 完整 apply 重验 **2 passed / 57.08s**；capture/billing/month-scope/publication-only 最终集 **53 passed, 2 skipped / 22.15s**；普通 worker/API 的 `-k 'settlement and rebuild'` 针对性回归 **15 passed / 102.79s**；最终独立 publication-only **13 passed / 13.63s**。命令均为共享 venv `python -m pytest <对应路径> -q --tb=short`，退出码 0。`git diff --check`、Python 编译检查通过。
