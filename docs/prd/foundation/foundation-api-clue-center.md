# API 接口设计 - 线索中心 V1.0

> 生成时间: 2026-07-22
> 来源: foundation-builder Phase 4
> 业务基线: [BRD](../../brd/BRD-clue-center-20260721-2134.md)
> 关联: [术语表](foundation-glossary-clue-center.md) · [Schema](foundation-schema-clue-center.md)

## 1. 设计结论

- 线索中心沿用宿主项目统一前缀 `/api/v1`、`snake_case` JSON、`data/meta` 成功包络和 `page/page_size` 分页，不在本专项内改造全站接口风格。
- 本文件定义目标契约，不代表当前代码已经全部实现。接口状态分为：`保留`、`变更`、`新增`、`删除`。
- 用户可见接口按页面权限键和账号数据范围双重鉴权；拥有页面权限不等于拥有完整手机号、跟进写入或高风险管理权限。
- 明文手机号只可由当前有效轮次所属门店的获授权用户按需读取；查看、复制和明文导出分别审计。
- 规则发布、试运行、正式分配、受控重建、跟进删除和联系方式访问必须留痕；审计记录不保存手机号明文、令牌或密钥。
- 试运行只写试运行证据，不创建正式轮次、不改变池位置、不进入经营指标。
- 正式状态只能由跟进命令、订单终态事件或受控内部任务迁移，不提供“任意修改线索状态”的通用接口。
- 旧 `execution_mode=legacy`、旧轮次重建和旧分配引擎接口在 DYDATA-34 中直接删除，不保留双写或长期兼容路由。

## 2. 专题文件

| 专题 | 内容 | 文件 |
|------|------|------|
| 公共契约 | 包络、分页、枚举、日期、权限、幂等、错误和审计 | [common-contract.md](foundation-api-clue-center/common-contract.md) |
| 线索查询与联系方式 | 看板、明细、详情、指标、导出和手机号访问 | [lead-query-and-contact.md](foundation-api-clue-center/lead-query-and-contact.md) |
| 跟进与轮次 | 五类动作、软删除、轮次状态迁移和并发边界 | [follow-up-and-rounds.md](foundation-api-clue-center/follow-up-and-rounds.md) |
| 规则与门店组 | 规则范围、草稿版本、发布、退役、固定策略和门店组 | [rules-and-store-groups.md](foundation-api-clue-center/rules-and-store-groups.md) |
| 分配运行与总部池 | 预览、试运行、批次、决策、候选、评分、总部池和审计 | [allocation-runtime-and-headquarters.md](foundation-api-clue-center/allocation-runtime-and-headquarters.md) |
| 任务、安全与迁移 | 正式分配任务、状态任务、物化、重建、外部接口和一次性切换 | [jobs-security-and-migration.md](foundation-api-clue-center/jobs-security-and-migration.md) |

## 3. 业务接口总览

### 3.1 线索看板、明细与详情

| # | 方法 | 路径 | 页面权限 | 状态 | 用途 |
|---|------|------|----------|------|------|
| Q01 | GET | `/api/v1/clues/filters` | A01/A02 | 保留 | 返回当前账号可见的组织、状态和商品筛选项 |
| Q02 | GET | `/api/v1/clues/overview` | A01 | 变更 | 返回完整主池、门店池、总部池、跟进和核销摘要 |
| Q03 | GET | `/api/v1/clues/metrics/monthly` | A01 | 新增 | 返回基线、过渡月、成熟月和总体核销率趋势 |
| Q04 | GET | `/api/v1/clues/metrics/stores` | A01 | 新增 | 返回授权范围内门店诊断指标 |
| Q05 | GET | `/api/v1/clues/assignment-rounds` | A02 | 变更 | 分页返回当前账号可见的真实轮次明细 |
| Q06 | GET | `/api/v1/clues/orders/{order_id}` | A02 | 变更 | 返回订单摘要、全部真实轮次和每轮跟进历史 |
| Q07 | POST | `/api/v1/clues/assignment-round-exports` | A02 | 新增 | 按账号范围与筛选同步导出，明文手机号逐行授权并审计 |
| Q08 | POST | `/api/v1/clues/orders/{order_id}/phone-access` | A02 | 新增 | 按查看或复制目的读取当前有效轮次完整手机号 |
| Q09 | GET | `/api/v1/clues/assignment-rounds/export` | A02 | 删除 | 被 Q07 替代，避免 GET 触发审计写入 |
| Q10 | GET | `/api/v1/clues/orders/{order_id}/phone` | A02 | 删除 | 被 Q08 替代，明确查看与复制两类审计目的 |

### 3.2 跟进与轮次

| # | 方法 | 路径 | 页面权限 | 状态 | 用途 |
|---|------|------|----------|------|------|
| F01 | POST | `/api/v1/clues/orders/{order_id}/follow-ups` | A02 | 新增 | 在当前有效轮次保存五类跟进动作之一 |
| F02 | DELETE | `/api/v1/clues/follow-up-records/{follow_up_record_id}` | A02 | 变更 | 最高管理员软删除错误跟进记录并重算轮次摘要 |
| F03 | POST | `/api/v1/clues/orders/{order_id}/follow-up` | A02 | 删除 | 被资源化的 F01 替代 |

### 3.3 规则与门店组

| # | 方法 | 路径 | 页面权限 | 状态 | 用途 |
|---|------|------|----------|------|------|
| R01 | GET | `/api/v1/admin/clue-allocation/rule-options` | D05 | 新增 | 返回城市、锚点门店和门店组候选 |
| R02 | GET | `/api/v1/admin/clue-allocation/rules` | D05 | 保留 | 查询规则列表和当前发布版本摘要 |
| R03 | POST | `/api/v1/admin/clue-allocation/rules` | D05 | 变更 | 最高管理员创建规则身份 |
| R04 | GET | `/api/v1/admin/clue-allocation/rules/{rule_id}` | D05 | 变更 | 查询规则、全部版本及绑定数量 |
| R05 | PUT | `/api/v1/admin/clue-allocation/rules/{rule_id}` | D05 | 新增 | 修改规则名称、说明或启用状态 |
| R06 | POST | `/api/v1/admin/clue-allocation/rules/{rule_id}/versions` | D05 | 变更 | 创建包含三类固定策略的完整草稿版本 |
| R07 | PUT | `/api/v1/admin/clue-allocation/rule-versions/{rule_version_id}` | D05 | 变更 | 全量覆盖尚未发布的草稿版本 |
| R08 | DELETE | `/api/v1/admin/clue-allocation/rule-versions/{rule_version_id}` | D05 | 保留 | 删除从未发布且未绑定的草稿 |
| R09 | POST | `/api/v1/admin/clue-allocation/rule-versions/{rule_version_id}/publish` | D05 | 变更 | 发布不可变版本并退役同范围旧发布版本 |
| R10 | POST | `/api/v1/admin/clue-allocation/rule-versions/{rule_version_id}/retire` | D05 | 变更 | 退役发布版本，不切换已绑定线索 |
| R11 | GET | `/api/v1/admin/clue-allocation/store-groups` | D05 | 变更 | 分页查询门店组及活动成员数 |
| R12 | POST | `/api/v1/admin/clue-allocation/store-groups` | D05 | 变更 | 创建门店组 |
| R13 | GET | `/api/v1/admin/clue-allocation/store-groups/{store_group_id}` | D05 | 新增 | 查询门店组与成员历史 |
| R14 | PUT | `/api/v1/admin/clue-allocation/store-groups/{store_group_id}` | D05 | 新增 | 修改门店组名称、说明、排序或启用状态 |
| R15 | PUT | `/api/v1/admin/clue-allocation/store-groups/{store_group_id}/members` | D05 | 变更 | 全量替换当前活动成员并保留成员历史 |

### 3.4 分配运行、评分、总部池和审计

| # | 方法 | 路径 | 页面权限 | 状态 | 用途 |
|---|------|------|----------|------|------|
| A01 | GET | `/api/v1/admin/clue-allocation/eligible-leads` | D06 | 变更 | 查询可进入试运行的活跃线索 |
| A02 | POST | `/api/v1/admin/clue-allocation/cycle-previews` | D06 | 新增 | 对试运行或重建范围生成短时预览令牌 |
| A03 | POST | `/api/v1/admin/clue-allocation/trial-cycles` | D06 | 新增 | 按有效预览创建试运行批次 |
| A04 | POST | `/api/v1/admin/clue-allocation/rebuild-cycles` | D06 | 新增 | 按有效预览创建受控重建批次 |
| A05 | GET | `/api/v1/admin/clue-allocation/cycles` | D06/D07 | 变更 | 分页查询试运行、正式运行和重建批次 |
| A06 | GET | `/api/v1/admin/clue-allocation/cycles/{cycle_id}` | D06/D07 | 新增 | 查询批次摘要和逐线索执行项 |
| A07 | GET | `/api/v1/admin/clue-allocation/decisions` | D07 | 变更 | 分页查询分配决策 |
| A08 | GET | `/api/v1/admin/clue-allocation/decisions/{decision_id}` | D07 | 新增 | 查询决策上下文和结构化候选证据 |
| A09 | GET | `/api/v1/admin/clue-allocation/store-scores` | D07 | 变更 | 查询评分运行和门店快照 |
| A10 | POST | `/api/v1/admin/clue-allocation/store-score-snapshot-runs` | D07 | 新增 | 最高管理员触发新评分运行 |
| A11 | GET | `/api/v1/admin/clue-allocation/master-leads` | D07 | 变更 | 查询完整主池和数据质量状态 |
| A12 | GET | `/api/v1/admin/clue-allocation/data-quality` | D07 | 新增 | 汇总源映射、锚点、地理和状态异常 |
| A13 | GET | `/api/v1/admin/clue-allocation/audit-logs` | D07 | 变更 | 最高管理员或审计权限查询脱敏审计日志 |
| H01 | GET | `/api/v1/admin/clue-allocation/headquarters-pool` | D08 | 变更 | 分页查询总部池库存与进入原因，V1 只读 |
| A14 | POST | `/api/v1/admin/clue-allocation/cycles/preview` | D06 | 删除 | 被 A02 替代 |
| A15 | POST | `/api/v1/admin/clue-allocation/cycles/trial` | D06 | 删除 | 被 A03 替代 |
| A16 | POST | `/api/v1/admin/clue-allocation/cycles/rebuild` | D06 | 删除 | 被 A04 替代 |
| A17 | POST | `/api/v1/admin/clue-allocation/store-scores/refresh` | D07 | 删除 | 被 A10 替代 |

## 4. 内部任务与外部依赖总览

| # | 类型 | 标识 | 状态 | 用途 |
|---|------|------|------|------|
| J01 | 内部 HTTP | `POST /api/v1/internal/clue-center/materializations` | 新增 | 原始证据物化为主池、联系方式和查询投影 |
| J02 | 内部 HTTP | `POST /api/v1/internal/clue-center/order-status-transitions` | 新增 | 消费订单、核销、退款事件并执行终态优先迁移 |
| J03 | 内部 HTTP | `POST /api/v1/internal/clue-allocation/formal-cycles` | 新增 | 对待分配线索执行唯一正式分配引擎 |
| J04 | 内部 HTTP | `POST /api/v1/internal/clue-allocation/round-expirations` | 新增 | 扫描 SLA 与保护期到期并推动下一策略 |
| J05 | 内部 HTTP | `POST /api/v1/internal/clue-allocation/metric-refreshes` | 新增 | 刷新评分、订单指标事实和读模型 |
| J06 | 内部 HTTP | `POST /api/v1/internal/clue-allocation/data-quality-checks` | 新增 | 生成源映射、锚点、门店地理和状态一致性报告 |
| J07 | 管理接口 | `POST /api/v1/admin/sync/clue-center/rebuild-previews` | 新增 | 预览一次性或受控全量重建影响 |
| J08 | 管理接口 | `POST /api/v1/admin/sync/clue-center/rebuilds` | 新增 | 最高管理员按确认令牌提交重建 |
| E01 | 外部引用 | 抖音线索查询 | 保留 | 采集原始线索和 `follow_poi_id` 锚点 |
| E02 | 外部引用 | 抖音订单查询 | 保留 | 补齐下单时间、销售店和订单状态 |
| E03 | 外部引用 | 抖音核销记录查询 | 保留 | 形成已核销终态证据 |
| E04 | 外部引用 | 抖音售后退款查询 | 变更 | 建立独立退款原始事实和已退款终态证据 |
| E05 | 外部引用 | 抖音密文解密 | 保留 | 后台静默写入集中联系方式表 |

## 5. 页面覆盖检查

| 页面/工作流 | 覆盖接口 |
|-------------|----------|
| 线索看板 `/clues` | Q01-Q04 |
| 线索明细 `/clues/details` | Q01、Q05、Q07 |
| 线索跟进详情浮层 | Q06、Q08、F01、F02 |
| 分配规则 | R01-R15 |
| 分配试运行 | A01-A06 |
| 分配记录 | A05-A13 |
| 总部线索池 | H01 |
| 数据同步与受控重建 | J07-J08 |
| 自动采集、正式分配和状态推进 | J01-J06、E01-E05 |

## 6. Phase 4 确认重点

1. 是否接受沿用宿主项目现有 `/api/v1`、`snake_case`、`data/meta` 契约，而不在本专项引入全站破坏性改名。
2. 是否接受把手机号和导出改为 POST 资源命令，以便准确审计查看、复制和明文导出。
3. 是否接受总部池 V1 只有查询接口，不设计再次投放写接口。
4. 是否接受普通管理员只读、最高管理员执行规则和批次管理、门店仅操作当前有效轮次的权限分层。
5. 是否接受正式分配仅由唯一内部任务 J03 触发，试运行和重建不能写正式轮次或经营指标。
