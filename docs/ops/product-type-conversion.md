# 精诚养车当前商品类型转换

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
