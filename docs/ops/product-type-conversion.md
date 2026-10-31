# 参与分佣 SKU 的当前商品类型转换

## 2026-10-30 当前执行口径

本节承接 DYDATA-104 新确认，优先于下文旧 scope 转换流程。当前参与分佣 SKU 中，明确属于“售后官方”的保留；其余参与分佣 SKU 统一为“精诚养车”。内部 scope、独立打榜成员、费率和历史财务事实不变。

使用既有入口并显式传入 `--participating-skus`。不带此参数仍是旧 scope 兼容操作，不能据旧“10条已完成”宣布新范围完成。

```bash
python scripts/convert_jingcheng_product_types.py \
  --participating-skus \
  --actor ops:catalog-maintainer \
  --change-reason DYDATA-104-Oct30-commission-types \
  --idempotency-key DYDATA-104-commission-types-v1 \
  --report /secure-output/commission-types-preview.json
```

选择依据是精确 SKU ID 对应已发布、已到生效时间、有效且至少一个方向费率大于零的正式规则。保留所有满足条件的历史规则证据，后续停用、零费率或商品下架不抹掉此前的参与事实；未来规则不当作当前或过去资格。商品名称、商品 ID 或旧 scope 均不能替代 SKU 证据。当前类型或正式参与规则快照明确为“售后官方”的目标保留官方类型。

预演报告包含完整目标前后清单、保留与转换数量、规则版本和生效日期、`missing_catalog_sku_ids` 及 `unproven_skus`。缺档与没有正式参与依据的项不自动归类；后者不能直接等同“永久不分佣”，必须保留原因供后续核查。报告含业务 ID，仅保存在受控私有位置。

应用命令使用同一参数、同一身份、原因及幂等键，另加 `--apply --preview-hash <原始64位摘要>` 并换一个新报告路径。PostgreSQL 下锁住商品目录和正式费率表，重新核对完整目录与规则证据后才写入。集合、档案、规则或资格变化使摘要失效，必须重新预演。目录类型与审计同事务，重复应用重放原收据；不触发费用重建。

商品同步、商品分类编辑/导入和新正式规则发布维持此口径。同步按精确 SKU 读取历史参与依据，不因同一 Product ID 下其他 SKU 参与而扩展集合。

### 新分析版本、历史快照与未覆盖项

目录转换本身不会修改旧费用、旧规则、账单行/分录、确认和发票。新版结算分析合同为 `commission-product-type-v3`，API 切换前须由正式发布 worker 预热完整版本；不能把旧分析版本仅换一个标签当成新结果。销售/线索分析仍为其现有 `product-type-v2`，独立打榜合同不变。

新结算分析按每条正式费用或保护账单冻结分录的准确 SKU 建立展示分类，重新聚合 all 与各类型，避免把多个旧类型相加造成同订单重复计数。展示行和相应分佣/财务订单明细的 `productType` 使用当前精确 SKU 类别，`snapshotProductType` 保留原财务类型。冻结账单权威、费用金额、实收、费率和发票资格均保持原合同，不用目录金额覆盖原账务。

发布统计 `commission_type_coverage` 按原因返回事实数和 SKU 数；缺 SKU、缺档、目录尚未归一保持明确异常，不伪装精诚养车。无法追到逐条费用来源的旧聚合继续保留，分别计入 `legacy_uncovered_ranking_rows`、`legacy_uncovered_monthly_rows`。这些数是聚合分区行数，不是缺失订单、券或 SKU 数；非零时必须逐项核查和解释，不能以筛选只剩两个名称宣称全量完成。

应用后分别核对8月、9月和当前适用账期：全国月榜、单店、分页、下钻和导出命中一致；all 无漏行/重复，两类别费用之和与其全量集合一致。同单多SKU的订单数按订单去重，不能把类型订单数机械相加作为全量订单数。独立打榜、原费用/规则/确认/发票指纹及后续同步均独立回归。

## 旧 scope 操作（保留兼容，不代表10月30日范围）

适用 DYDATA-104 的当前目录分类功能，不涉及历史归属补录、费用补记、账单确认或重建。执行入口为 `scripts/convert_jingcheng_product_types.py`；数据库连接沿用受控环境配置，不在命令、报告摘要或仓库保存凭据。

## 预演

使用新会话、已部署的代码以及一个新的受控输出文件。报告应放在仓库外，或已被 Git 忽略且从未追踪的目录；文件已存在会拒绝覆盖。示例中的执行身份须替换为当前有效全国管理员用户名，或实际受控执行者的 `ops:<标识>`。

```bash
python scripts/convert_jingcheng_product_types.py \
  --actor ops:catalog-maintainer \
  --change-reason DYDATA-104-product-type-conversion \
  --idempotency-key DYDATA-104-catalog-types-v1 \
  --report /secure-output/catalog-types-preview.json
```

省略 `--apply` 永远仅预演。核查 `target_count`、`changed_count`、`unchanged_count`、`before_groups`、`after_groups` 和逐 SKU `diff`：目标必须全部且仅为内部精确 scope `精诚养车`，不得凭商品名称扩大。已有其他类型的目标也应列入变更，其他 scope 的已核验类型保留。记录非目标目录和受保护财务事实的基线指纹，真实清单留在受控环境，不提交仓库。

`preview_hash` 绑定执行者、原因和完整目标目录快照，包括无须修改的目标。预演与应用之间任一目标字段或目标集合变化均需重新预演，不能伪造摘要。先协调商品同步及正在处理数据的协作者，避免执行窗口冲突。

## 应用与回读

应用仅支持 PostgreSQL，沿用同一执行身份、原因和幂等键，并传入已核查的原始摘要；应用报告使用另一个新文件：

```bash
python scripts/convert_jingcheng_product_types.py \
  --actor ops:catalog-maintainer \
  --change-reason DYDATA-104-product-type-conversion \
  --idempotency-key DYDATA-104-catalog-types-v1 \
  --preview-hash <预演得到的完整64位摘要> \
  --apply \
  --report /secure-output/catalog-types-applied.json
```

工具检查重型来源任务和共享锁，取得目录表写入栅栏及目标行锁后重新核对摘要。锁等待 5 秒、语句 30 秒，冲突或来源忙直接停止，不加大超时绕过。目录更新、结构化前后审计和提交前回读在同一事务；失败全部回滚。同一幂等键及原始摘要可重放，返回 `replayed=true`，不会重复修改。

应用后独立查询目录类型、数量和审计记录，并核对内部 scope、费率、非目标 SKU、历史费用/账单/确认/发票指纹。正常并行业务变化须单独解释，不能用旧静态数量宣称未变。分析更新由独立发布 worker 处理；读取同版筛选与导出验收，不调用历史费用重建来刷新类型。

## 发布和回退

无 schema 迁移或历史费用回填。API/web 切换前先让后台发布核销与线索的 `product-type-v2` 完整版本，确认五个模块读取就绪。独立打榜的版本、来源条件和 scope 集合须保持可验证。

代码回退保留旧镜像；新旧财务事实兼容。目录类型是明确的业务配置，回退代码不自动反向改目录。若需要撤销分类转换，先依据原审计生成精确差异并核对后续人工改动，再执行受控修正；不得恢复整库备份覆盖其他协作者的新事实。

本文件提供可执行流程，不表示已经对生产运行预演、应用或发布。实际证据登记在[本轮验证记录](../verification/dydata-104-product-types.md)。
