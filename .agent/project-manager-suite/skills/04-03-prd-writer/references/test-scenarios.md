# prd-writer 测试场景

本文件记录 prd-writer 升级后的开发调试场景。自动化覆盖位于 `tests/prd-check.test.mjs`，脚本入口为 `scripts/prd-check.mjs`。

## 1. Happy Path

- 2 个页面、3 个区块、3 份 subprd。
- feature-list、mainprd、foundation-schema、foundation-api、explainer-b-interaction 均齐备。
- `crosscheck --host-dir <host> --slug demo --json` 返回 exit code 0。

## 2. 结构缺失

| 场景 | 期望 ruleId | 通过标准 |
|---|---|---|
| feature-list 缺 `## 页面布局全景` | `feature-list.required-section` | exit code 2，输出 fixHint 和 nextCommand |
| 页面布局全景漏 page-delivery 页面 | `crosscheck.page-coverage-missing` | exit code 2 |
| 页面全景编号数量与功能总表不一致 | `feature-list.panorama-block-count` | exit code 2 |
| 区块详情缺固定锚点 | `feature-list.detail-anchor-missing` | exit code 2 |
| subprd 功能子区域缺 X.6 | `subprd.functional-subsection` | exit code 2 |

## 3. 索引和状态漂移

| 场景 | 期望 ruleId | 修复动作 |
|---|---|---|
| feature-list 与 mainprd 行级状态不同 | `crosscheck.index-row-drift` | 运行 `sync-index` 或 `set-status` |
| subprd 文件缺失 | `crosscheck.subprd-missing` | 补写缺失 subprd |
| 某行状态不是 `已确认` | `crosscheck.unconfirmed-row` | 用户确认后运行 `set-status` |

## 4. Foundation / Explainer 引用

| 场景 | 期望 ruleId | 处理 |
|---|---|---|
| X.3 引用不存在的 `表.字段` | `crosscheck.schema-field-missing` | 修正 subprd 或登记待回溯 foundation-builder |
| 接口引用不存在 | `crosscheck.api-path-missing` | 修正 subprd 或登记待回溯 foundation-builder |
| 交互语义 id 不存在或未 locked | `crosscheck.interaction-id-invalid` | 改为 locked id 或回溯 page-explainer |
| 缺 `**交互语义引用**：` | `crosscheck.interaction-id-missing` | 输出 needs_ai_review，补槽位或人工确认无交互 |

## 5. route-check 污染回归

| 场景 | 预期 |
|---|---|
| mainprd 使用安全的 `## 一致性自查结果` bullet 摘要和 `## 待回溯缺口` 表 | route-check 的 `fullPrdReady` 不受污染 |
| mainprd 出现 `| # | 区块 | subprd 文件 | 存在 |` | route-check 会误识别为索引表，fixture 保持失败以锁定避让规则 |

## 6. 交互协议

- `查看进度`：运行 `progress`，展示当前状态和缺口。
- `只看缺口`：运行 `progress` 或 `crosscheck`，只展示非 pass 项。
- 已确认产物变更：先 `set-status --status 待确认`，改完后 `structure` + `crosscheck`，重新确认再设为 `已确认`。
