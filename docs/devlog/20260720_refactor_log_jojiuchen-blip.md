# 开发日志 — 2026-07-20

> 主题：S2 Foundation Phase 6 交付
> 操作人：jojiuchen-blip
> 关联计划：docs/plans/execution-plan.md

---

## 一、执行概要

| # | 任务 | 关联 | 状态 |
|---|------|------|------|
| 1 | S2 Foundation Phase 6 交付 | 本轮推进 | ✅ |
| 2 | PRD Phase 2 功能列表 | 补充更新 | ✅ |
| 3 | PRD Phase 3 mainprd | 补充更新 | ✅ |
| 4 | PRD Phase 4：全国门店榜单 subprd | 补充更新 | ✅ |
| 5 | PRD Phase 4：确认全国门店榜单并生成单店分账 | 补充更新 | ✅ |
| 6 | 确认单店分账并生成订单费用明细子 PRD | 补充更新 | ✅ |
| 7 | 确认订单费用明细并生成开票流程引导子 PRD | 补充更新 | ✅ |
| 8 | PRD Phase 5 一致性检查与治理阻塞登记 | 补充更新 | ✅ |
| 9 | DYDATA-39 校验器修复与 Phase 5 真实缺口识别 | 补充更新 | ✅ |
| 10 | Foundation 增量补档与 PRD Phase 5 收敛 | 补充更新 | ✅ |
| 11 | PRD Phase 5 用户确认与 S3 阶段切换 | 补充更新 | ✅ |
| 12 | DYDATA 正式 S3 交付计划生成 | S3 | ✅ |
| 13 | S3 计划确认并进入 S4 T1.1 | S4 | ✅ |
| 14 | DYDATA-38 T1.1 兼容内部 ID 实装 | S4 | ✅ |
| 15 | T1.2 商品、双费率与导入 Schema 完成 | S4 | ✅ |
| 16 | T1.3 双费用结算与报表 Schema 完成 | S4 | ✅ |
| 17 | T2.1 商品同步内部链路完成 | S4 | ✅ |
| 18 | T2.2 SKU 双费率与原子导入 API 完成 | S4 | ✅ |
| 19 | 任务 21：T2.5 原始订单/券内部主键切换完成 | 补充更新 | ✅ |
| 20 | T3.1 结算报表查询 API 完成本地实现 | S4 / T3.1 | ✅ |

**本日关键结论**：foundationReadyForPrd.pass=true；3 张既有只读依赖表逐字段定义已补齐；PRD Phase 5 crosscheck 为 0 fail/0 warn/0 needs_ai_review，人工一致性复核全部闭合，当前只待用户确认 Phase 5

---

## 二、操作详情

### 任务 1：S2 Foundation Phase 6 交付
- **目标**：在用户确认 Phase 5 后完成 DYDATA Foundation 交付清单并建立进入完整版 PRD 的可追溯门禁
- **操作**：生成 foundation-delivery-dy-data.md，逐条声明术语表、Schema、API 及 7 个拆分子文件；运行 S2 route-check 和项目链接索引；回写 project-profile.md 与 docs/plans/execution-plan.md
- **结果**：foundationReadyForPrd.pass=true；页面 22/22、API 22/22、Schema 17/17、锁定语义和校验各 9/9；下一步由 prd-chief 调度 prd-writer，外部抖音样例与正式配置继续作为生产验收依赖
- **涉及文件**：无

<!-- 复杂决策型任务可展开分析：
### 任务 N：标题（决策类）
- **背景问题**：为什么要做这个决策
- **方案对比**：（表格或列表）
- **最终决策**：选了什么 + 为什么
- **涉及文件**：列表
-->

---

## 三、变更总览

### 文件变更清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建/修改/删除 | `path/to/file` | 一句话说明 |

> 收口时由 AI 从各任务「涉及文件」聚合去重生成。操作类型：新建 / 修改 / 删除。

### Git 提交记录

| 时间 | Commit | 内容 |
|------|--------|------|

---

## 四、发现的问题 / 缺陷

无

---

## 五、复盘

### 做得好的
- （列举）

### 遇到的问题
- **现象**：
- **根因**：
- **经验**：> 可执行的一句话
- **🔧 是否提炼为规则**：✅ 建议写入 `project-rules.md` / ⬜ 仅记录

### 今日经验总结
1. 经验 1 → 🔧 建议加入 project-rules.md
2. 经验 2 → 仅记录

---

## 五·附、方法论沉淀（可选）

> 当天工作中如果有可复用的方法论、设计原则、或跨项目通用的经验，在此抽象记录。
> 普通开发日不需要填写此章节。

---

## 六、待跟进事项

- [ ] 待补充
---

## 补充更新 1（12:50 · 窗口 1）

### 任务 2：PRD Phase 2 功能列表
- **目标**：基于已确认页面、交互语义和 Foundation 产物生成 dy-data 功能区块清单，并停在用户确认门
- **操作**：完整读取 BRD、四页交付与交互说明、术语表、Schema 和 API；按模板拆分 4 个页面区块；运行 prd-check structure；刷新项目链接索引；同步项目画像与执行驾驶舱
- **结果**：docs/prd/prd-feature-list-dy-data.md 已生成，structure 为 0 fail/0 warn/0 needs_ai_review；当前等待用户确认 4 个区块和管理端页面边界，确认后进入 Phase 3 mainprd。索引中 4 条 subprd 缺失链接为 Phase 4 尚未生成的预期状态，另有 2 条 DYDATA-22 历史坏链与本轮无关
- **涉及文件**：无
---

## 补充更新 2（13:13 · 窗口 2）

### 任务 3：PRD Phase 3 mainprd
- **目标**：在用户确认四个功能区块后生成 dy-data mainprd 索引枢纽，并停在 Phase 3 用户确认门
- **操作**：加载 Phase 3 模板；建立上游引用、4 行 subprd 索引、跨区块全局设计规则、Phase 5 自查占位和回溯缺口表；按校验提示修正标题格式；运行 prd-check structure；刷新项目链接索引；同步项目画像与执行驾驶舱
- **结果**：docs/prd/mainprd-dy-data.md 已生成，structure 为 0 fail/0 warn/0 needs_ai_review；Phase 2 功能列表已确认，Phase 3 mainprd 待用户确认，4 份 subprd 尚未生成。索引中的 8 条 subprd 缺失链接为 Phase 4 未开始的预期状态，另有 2 条 DYDATA-22 历史坏链与本轮无关
- **涉及文件**：无
---

## 补充更新 3（13:31 · 窗口 3）

### 任务 4：PRD Phase 4：全国门店榜单 subprd
- **目标**：确认 mainprd 后生成并校验第 1/4 份全国门店榜单 subprd
- **操作**：读取排名页面代码、用户流程、2 条 locked 交互语义、筛选元数据与榜单 API、SKU 产品维度和门店排名投影；生成筛选与口径、全国摘要指标、门店排名结果及接口引用章节；运行 structure；同步功能列表和 mainprd 第 1 行为待确认；刷新链接索引；回写画像与驾驶舱
- **结果**：docs/prd/subprd/01-subprd-store-ranking.md 已生成，structure 为 0 fail/0 warn/0 needs_ai_review；mainprd 已按用户连续继续确认进入 Phase 4，当前 subprd 已确认进度 0/4，第 1 份待用户确认。其余 3 份 subprd 未生成，在两份索引中形成 6 条预期坏链
- **涉及文件**：无
---

## 补充更新 4（13:48 · 窗口 4）

### 任务 5：PRD Phase 4：确认全国门店榜单并生成单店分账
- **目标**：同步第1份subprd用户确认状态，生成并校验第2份单店分账subprd
- **操作**：用prd-check将区块1回填为已确认；基于已锁定页面交互、术语、Schema与API生成02-subprd-store-settlement.md；结构校验后将区块2同步为待确认，刷新项目链接索引并更新项目画像和执行驾驶舱
- **结果**：Phase 4进度为1/4已确认；第2份单店分账subprd已生成，structure为0 fail/0 warn/0 needs_ai_review，当前等待用户确认
- **涉及文件**：无
---

## 补充更新 5（14:01 · 窗口 5）

### 任务 6：确认单店分账并生成订单费用明细子 PRD
- **目标**：确认第 2 份单店分账子 PRD，并继续生成全部未完成 PRD 中的第 3 份订单费用明细
- **操作**：将第 2 个 subprd 状态同步为已确认；依据页面原型、锁定交互、Foundation API/Schema/术语生成 03-subprd-order-fee-details.md；同步功能列表、mainprd、项目画像、执行计划与项目链接索引；执行结构校验
- **结果**：01、02 两份 subprd 已确认；03 订单费用明细已生成并通过结构校验，当前状态待确认；04 开票流程引导因逐份确认门尚待开始；项目索引仅剩 04 的两条预期坏链及两条与本轮无关的 DYDATA-22 历史坏链
- **涉及文件**：无
---

## 补充更新 6（14:13 · 窗口 6）

### 任务 7：确认订单费用明细并生成开票流程引导子 PRD
- **目标**：确认第 3 份订单费用明细子 PRD，并生成最后一份开票流程引导子 PRD
- **操作**：将第 3 个 subprd 状态同步为已确认；依据已确认原型、锁定交互、Foundation 术语与 API 写入边界生成 04-subprd-invoice-guide.md；同步功能列表、mainprd、项目画像、执行计划和项目链接索引
- **结果**：前 3 份 subprd 已确认；04 开票流程引导已生成并通过结构校验、当前待用户确认；页面保持静态只读，不新增发票、账单确认、锁账或财务审核接口；全部 4 份 subprd 已进入项目索引，PRD 断链为 0
- **涉及文件**：无
---

## 补充更新 7（14:25 · 窗口 7）

### 任务 8：PRD Phase 5 一致性检查与治理阻塞登记
- **目标**：确认第4份子PRD并进入Phase 5，定位一致性校验阻塞
- **操作**：同步4/4子PRD确认状态；运行crosscheck并定位拆分Schema二级标题漏检；创建Linear问题DYDATA-39；回写项目画像与执行计划
- **结果**：4/4子PRD已确认；Phase 5因107条schema字段误报暂停，DYDATA-39已登记并等待用户确认进入修复开发
- **涉及文件**：无
---

## 补充更新 8（14:42 · 窗口 8）

### 任务 9：DYDATA-39 校验器修复与 Phase 5 真实缺口识别
- **目标**：修复拆分 Schema 二级标题漏检并恢复 PRD Phase 5
- **操作**：在独立标准源新增失败回归测试并完成最小修复；运行120项套件测试；重新安装套件并刷新锁；重跑真实 crosscheck；回写项目画像和执行计划
- **结果**：DYDATA-39 修复已完成验证，误报由107条清零；当前剩余7条真实 Foundation 字段定义缺口，等待用户确认增量补档
- **涉及文件**：.agent/project-manager-suite/skills/04-03-prd-writer/scripts/prd-check.mjs、.agent/project-manager-suite/tests/prd-check.test.mjs、.agent/project-manager-suite.lock.json、project-profile.md、docs/plans/execution-plan.md

---

## 补充更新 9（15:03 · 窗口 9）

### 任务 10：Foundation 增量补档与 PRD Phase 5 收敛
- **目标**：按用户确认补齐 3 张既有只读依赖表的 Foundation 字段定义，并完成 prd-writer Phase 5 全量复核
- **操作**：新增既有依赖表 Schema 子文件，更新 Schema 主索引和 Foundation 交付清单；刷新项目链接索引；运行 S2 route-check、PRD crosscheck 和 progress；人工复核数据链路、接口、术语、功能索引、交互语义、用户流程及验收对应；将结论回填 mainprd、项目画像、执行计划和 Linear DYDATA-39
- **结果**：未修改数据库结构、迁移或业务口径；Foundation 门禁通过；Phase 5 为 P1 96/96、P2 5/5、P3 已复核、P4 4/4、P5 索引完整、P6 9/9、P8 已复核、P9 14/14，crosscheck 为 0 fail/0 warn/0 needs_ai_review；DYDATA-39 已转 In Review，等待用户确认 Phase 5
- **涉及文件**：docs/prd/foundation/foundation-schema-dy-data/existing-read-dependencies.md、docs/prd/foundation/foundation-schema-dy-data.md、docs/prd/foundation/foundation-delivery-dy-data.md、docs/prd/mainprd-dy-data.md、project-profile.md、docs/plans/execution-plan.md
---

## 补充更新 10（15:09 · 窗口 10）

### 任务 11：PRD Phase 5 用户确认与 S3 阶段切换
- **目标**：完成 prd-writer 收口并将项目从 S2 切换到 S3 开发计划阶段
- **操作**：记录用户确认；更新 mainprd、项目画像和执行驾驶舱；运行 S3 route-check；准备将 DYDATA-39 标记 Done 并交接 delivery-planner
- **结果**：prd-writer DONE；fullPrdReady 与 foundationReadyForDevelopmentPlan 均通过；当前阶段已回写为 S3，正式开发计划文件组待生成
- **涉及文件**：无
---

## 补充更新 11（15:27 · 窗口 11）

### 任务 12：DYDATA 正式 S3 交付计划生成
- **目标**：将已确认 PRD 转换为可审阅、可追踪的正式开发计划
- **操作**：基于 Foundation、主 PRD、四份子 PRD、页面说明与现有代码证据，生成 1 份主计划、1 份任务看板和 12 份子计划；同步执行摘要、项目画像与长期规则索引。
- **结果**：正式计划组已生成，12 个 Task 全部处于待审阅；计划结构校验 13/13 章节、12/12 任务通过，0 错误、0 警告。
- **涉及文件**：docs/plans/delivery-plans/main-delivery-plan-dy-data.md、docs/plans/delivery-plans/task-kanban-dy-data.md、docs/plans/execution-plan.md、project-profile.md、project-rules.md
---

## 补充更新 12（15:37 · 窗口 12）

### 任务 13：S3 计划确认并进入 S4 T1.1
- **目标**：按用户确认执行全部正式开发计划，并从 T1.1 开始代码实装
- **操作**：将全部计划从待审阅切换为已审阅状态；T1.1 在主计划、任务看板和子计划三处置为进行中，其余 11 个 Task 置为待开发；同步执行驾驶舱与项目画像。
- **结果**：计划结构校验通过；S4 开工前一致性校验通过，唯一活跃 Task 为 T1.1。
- **涉及文件**：docs/plans/delivery-plans/main-delivery-plan-dy-data.md、docs/plans/delivery-plans/task-kanban-dy-data.md、docs/plans/delivery-plans/sub-delivery-plan-dy-data-T1.1-raw-id-compat.md、docs/plans/execution-plan.md、project-profile.md
---

## 补充更新 13（15:54 · 窗口 13）

### 任务 14：DYDATA-38 T1.1 兼容内部 ID 实装
- **目标**：完成原始订单与券的阶段 1 内部 ID 扩展、历史回填和旧业务 ID 读写兼容
- **操作**：按 TDD 新增迁移与采集失败测试；新增 20260720_0019 Alembic 迁移；模型增加内部 id/raw_order_id；订单与券 upsert 改为按平台业务 ID 查询后更新或新增；补旧 ORM 直接写入兼容。
- **结果**：专项回归 38 passed；空库及既有 SQLite 升降级、2 行订单/2 行券回填、内部 ID 非空/不重复、孤儿和双关联不一致均为 0；PostgreSQL 离线 DDL 生成成功；git diff --check 和 compileall 通过。ruff 未安装；本机无 Docker/psql/PostgreSQL，目标 PostgreSQL 实库执行保留到发布闸门。
- **涉及文件**：apps/api/dy_api/models.py、apps/worker/repositories.py、alembic/versions/20260720_0019_raw_order_internal_ids.py、tests/test_alembic_migrations.py、tests/test_worker_order_collector.py
---

## 补充更新 14（16:16 · 窗口 14）

### 任务 15：T1.2 商品、双费率与导入 Schema 完成
- **目标**：建立商品当前事实、同步历史、结算范围、不可变日级双费率及原子导入批次和逐行结果数据地基
- **操作**：按 TDD 新增 5 张目标表并升级 dim_sku_product_rules 为内部 bigint 主键和 sku_id 业务唯一键；保留旧人工分类与 compatibility commission_rate；改造 SKU upsert 和结算读取按业务键查询；增加 SQLite 既有数据往返迁移、结构约束和旧 API 重复保存测试
- **结果**：目标测试 23 passed，受影响回归 54 passed；Alembic 单一 head 20260720_0020；PostgreSQL 离线 DDL 生成通过；真实 PostgreSQL 测试库当前不可用，实际 inspector 核验并入 T4.1
- **涉及文件**：apps/api/dy_api/models.py、apps/api/dy_api/routes/_data.py、apps/worker/repositories.py、apps/worker/settlement.py、alembic/versions/20260720_0020_product_rule_schema.py、tests/test_data_schema.py、tests/test_alembic_migrations.py、tests/test_api_admin_sku_rules.py
---

## 补充更新 15（16:39 · 窗口 15）

### 任务 16：T1.3 双费用结算与报表 Schema 完成
- **目标**：建立不可变费用结果、当前结果、调整记录、结算单与报表投影的数据基础
- **操作**：新增退款事件、费用结果、当前结果、费用调整、结算单头、结算单行和来源明细 7 张表；升级全国门店榜单与门店月度结算投影；保留旧接口兼容字段，但不把旧单一佣金金额映射为推广费或管理服务费
- **结果**：T1.3 定向测试 19 passed；受影响回归 29 passed；PostgreSQL 离线迁移 DDL 生成通过；真实 PostgreSQL 升降级与数据复制验证留至 T4.1
- **涉及文件**：apps/api/dy_api/models.py、apps/worker/settlement.py、alembic/versions/20260720_0021_settlement_reporting_schema.py、tests/test_data_schema.py、tests/test_alembic_migrations.py、tests/test_data_settlement.py、tests/test_api_admin_sku_rules.py
---

## 补充更新 16（17:01 · 窗口 16）

### 任务 17：T2.1 商品同步内部链路完成
- **目标**：建立商品同步的认证传输边界、白名单适配器、历史与当前快照写入、增量游标和管理接口
- **操作**：新增商品页认证重试传输方法与 product_sync worker；实现成功、空页、重复页、非法响应、未知状态、上游失败、人工字段保护、原始游标内部保存与 API 脱敏；新增运行列表、幂等触发、运行详情和 SKU 历史 4 个管理接口
- **结果**：目标测试 37 passed；受影响回归 47 passed；compileall 与 git diff --check 通过；外部正式 URL、鉴权参数、字段枚举及真实响应映射未猜测，生产验收继续依赖用户提供的脱敏样例
- **涉及文件**：src/dy_data/douyin_client.py、apps/worker/product_sync.py、apps/api/dy_api/routes/admin.py、apps/api/dy_api/schemas.py、tests/test_douyin_openapi_client.py、tests/test_worker_product_sync.py、tests/test_api_admin_sync.py
---

## 补充更新 17（17:39 · 窗口 17）

### 任务 18：T2.2 SKU 双费率与原子导入 API 完成
- **目标**：交付商品人工分类、不可变双费率、结算范围规则及 CSV/XLSX 整批原子导入管理契约
- **操作**：新增独立 fee-admin 路由和 13 个接口；实现 camelCase/请求 ID/结构化错误、管理员与高风险超级管理员权限、日级双费率版本、结算范围分渠道版本、10 MiB/5000 行 CSV/XLSX 全量校验、结果文件和幂等原子提交；保留旧 sku-rules 兼容入口
- **结果**：目标与权限测试 28 passed；受影响 API 回归 41 passed；5000 行边界、错误模板、名称-ID 不匹配、费率类型/范围、批内重复、数据库竞争和提交中唯一冲突整批回滚均通过；13 个目标方法在 OpenAPI 路由注册完整
- **涉及文件**：apps/api/dy_api/routes/fee_admin.py、apps/api/dy_api/main.py、apps/api/dy_api/schemas.py、tests/test_api_fee_admin.py、tests/test_api_account_permissions.py

---

## 补充更新 18（23:32 · 窗口 18）

### 任务 19：T2.3 不可变双费用结果与事件调整完成
- **目标**：按销售业务日/销售月和核销业务日/核销月分别生成推广服务费、管理服务费不可变结果，并以事件月份负向调整表达退款与取消核销
- **操作**：按 TDD 扩展订单/券标准化采集字段和 20260720_0022 兼容迁移；实现正式账期、有效商品、稳定归属账号、直播/短视频范围校验，按业务日匹配最新 ACTIVE 双费率；实现一券双方向当前指针、显式重算新版本、锁账指针冻结、部分/全额退款及取消核销不可变调整；保留旧 `settlement_order_details` 兼容投影
- **结果**：目标结算/采集测试 20 passed；受影响结算、采集、Schema、Alembic 和 Dashboard 回归 65 passed；商品主数据归属与订单销售归属独立、正常、同店/跨店、跨月、未支付关闭、未知 SKU/渠道/账号、日级费率边界、ROUND_HALF_UP、部分/全额退款、取消核销、重复运行、未锁账重算和锁账冻结均通过；compileall 与 git diff --check 通过，只有既有换行符警告
- **漂移结论**：Foundation 业务语义无漂移；补齐了 Foundation 已声明但旧 ORM/迁移未落地的原始订单/券标准化字段。真实商品 API 归属账号与渠道枚举仍保留为 T4.1 生产验收外部依赖
- **涉及文件**：apps/api/dy_api/models.py、apps/worker/collectors/orders.py、apps/worker/settlement.py、alembic/versions/20260720_0022_raw_order_settlement_fields.py、tests/test_data_settlement.py、tests/test_worker_order_collector.py、tests/test_alembic_migrations.py

---

## 补充更新 19（20:55 · 窗口 19）

### 任务 20：T2.4 三层账单、双费用投影与锁账边界完成
- **目标**：从当前双费用结果和不可变调整生成账单头、账单行、来源项、月度结算与月度/累计全国榜单投影，并保证锁账冻结、事件月归属、重跑和失败回滚一致
- **操作**：按 TDD 实现账单来源唯一性、头/行/来源金额恒等式、锁账后费率和门店映射冻结、后续退款事件月调整、按月分段投影与 processed/skipped/failed 统计；修复重算混用旧调整血缘、迟到退款/取消核销、空券 ID 退款、失败审计回滚丢失、锁账与重算竞态、锁账后迟到券和已锁事件月调整等边界；新增 successful_observed_at 不可变首次成功观察时间和 0023 迁移；最终代码复核无 Critical
- **结果**：目标结算与 Dashboard 测试 45 passed；受影响结算、Dashboard、Schema、Alembic、采集、费率管理回归 86 passed；Schema/Alembic 专项 13 passed；compileall 与 git diff --check 通过，仅有既有换行符警告。正式累计固定从 2026-08 开始，7 月销售/8 月核销继续按 Linear DYDATA-31 排除。已锁账月份的迟到新结果和缺少补充账单政策的已锁事件月调整均阻断并记录 DQ
- **漂移结论**：双费用、退款事件月和锁账口径无业务漂移；新增首次成功观察时间属于实现层幂等补强，已同步 Foundation Schema。PostgreSQL 双会话 advisory lock 竞态实测和生产级大数据量压力验证保留为 T4.1 发布门禁
- **涉及文件**：apps/api/dy_api/db.py、apps/api/dy_api/models.py、apps/worker/settlement.py、alembic/versions/20260720_0023_refund_success_observed_at.py、docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md、tests/test_data_schema.py、tests/test_data_settlement.py
---

## 补充更新 20（21:37 · 窗口 20）

### 任务 21：任务 21：T2.5 原始订单/券内部主键切换完成
- **目标**：完成 DYDATA-38 Stage 2 的内部 ID 应用关联、主键约束切换和安全迁移边界
- **操作**：按 TDD 完成 ORM、采集、结算与 Alembic 0024；覆盖并发唯一索引、两级短锁、USING INDEX 约束交换、双 Identity 序列同步、影子/孤儿校验和 API/CSV 内部 ID 隐藏；完成三轮代码审查并同步 Linear DYDATA-38
- **结果**：目标回归 66 passed；compileall、git diff --check、Alembic 单 head 和计划一致性检查通过；无 Critical/Important 审查问题；未执行生产迁移，真实 PostgreSQL 双会话、脱敏副本、锁时长、序列和升降级演练保留到 T4.1；Foundation 无漂移
- **涉及文件**：无
---

## 补充更新 21（22:27 · 窗口 21）

### 任务 22：T3.1 结算报表查询 API 完成本地实现
- **目标**：完成 DYDATA-33 后端筛选、榜单、单店、订单费用明细与导出契约
- **操作**：按 TDD 实现五个查询/导出入口，补齐 current 与 locked 来源、费率版本上下文、服务端权限、正式累计边界、稳定排名、商品可见性和 CSV；独立审查并修复六个边界问题
- **结果**：目标回归 30 passed；全 API 135 passed；compileall 与 scoped git diff --check 通过；独立审查 Critical 0、Important 0
- **涉及文件**：apps/api/dy_api/routes/meta.py、apps/api/dy_api/routes/dashboard.py、apps/api/dy_api/routes/_data.py、apps/api/dy_api/main.py、docs/api-contract.md、tests/test_api_dashboard.py、tests/test_api_account_permissions.py、tests/test_api_product_type_visibility.py
