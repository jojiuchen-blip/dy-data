# DYDATA-88 线索中心 F01–F11 修复控制器规格

状态：待最终验收。日期：2026-09-07。控制器：当前 Codex 主窗口。代码基线：`86a8171`。
需求与验收权威：[DYDATA-88](https://linear.app/keith-lim/issue/DYDATA-88/bug-修复线索中心代码审查-f01-f11)。

## 目标与授权

用户已明确要求修复审查中全部 F 项，且在 Linear 重连后继续执行。完成本地实现、回归、独立审查和证据回填；不将本地修复称为已上线。主仓库原有未跟踪的 8GB 规格文件保留。

本增量承接线索平台 S4 的问题回归，不改变 [主计划](delivery-plans/main-delivery-plan-dydata-clue-platform-completion.md)、[任务看板](delivery-plans/task-kanban-dydata-clue-platform-completion.md) 中其他任务的状态，也不据此宣布 T2.4 的全部资源/发布门禁完成。

## 范围与非目标

- 覆盖 F01–F11，以及必要的缓存来源列迁移、共享电话/权限合同、接口文档和回归测试。
- 不覆盖 R01/R02、泛化模块重构、自动正式分配/再分配启用、生产数据修复、部署、推送或其他 issue。
- 不改既有迁移历史。新列需要追加迁移并说明旧缓存处理与回滚。
- 子代理只在指定隔离工作树写入指定文件；主代理审查补丁后逐一集成，保留所有无关改动。

## 分工与验收台账

| 任务 | Owner | 写入范围 | 状态 | 必需验收 |
| --- | --- | --- | --- | --- |
| A / F01、F05 | collector worker | collectors/clues.py、collectors/types.py、repositories.py（仅必要的结果合同）、采集专用测试 | 已实现，规格/质量审查通过 | 更新/旧观测/重试统计；小时饱和递归拆分；最小窗口明确失败 |
| B / F02、F03、F04 | projection worker | clue_center.py、src/dy_data/phones.py、models.py 新电话来源指纹列、追加迁移、投影/电话/迁移专用测试（含 F06 投影锁） | 已实现，规格/质量审查通过 | alias→master 终态；明文/密文分类；来源变化缓存失效；同源缓存复用 |
| C / F09、F11 | frontend worker | client.ts、AdminClueAllocationPage.tsx、必要 demo/types、前端专用测试 | 已实现，规格/质量审查通过 | 真实详情异常可见；全部分页资源可翻页及真实总数；演示模式兼容 |
| D / F06、F07 | 主代理 | follow_up_state.py、routes/clues.py、共享权限 helper、状态/权限专用测试 | 已实现，专项审查通过 | 锁后重新校验、并发关闭不反转；全部/指定/空范围一致 |
| E / F03 API、F04 API、F08、F10 | 主代理 | routes/_data.py、API 专用测试及必要接口文档 | 已实现，专项审查通过 | 复用电话规则；缺失电话批量调用/受控缓存；订单聚合分子分母同口径 |
| D2 / F06 跨写入口 | allocation locks worker | clue_allocation.py、clue_allocation_engine.py、锁回归测试 | 已实现，规格/质量审查通过 | 物化/修复/显式分配与跟进统一锁序；旧 Session 不覆盖新指针 |
| V / 集成验收 | 主代理与独立只读 reviewer | 控制器记录、验证报告、开发日志 | 本地验收完成，待用户验收 | 逐项规格审查通过后做代码质量审查，再执行集成回归 |

## 必需行为

1. F01：collector 为实际观测传入时间、稳定观测键和 source_run_id；有修改时间优先用于防旧覆盖，无时间观测有确定规则；真实变化产生 JobImpact。统计不能把拒收或无变化解释成真实更新。
2. F02：投影通过权威来源关联找主线索；关闭、退款、核销等主状态不得因单个别名来源过滤而丢失。
3. F03：密文、掩码及任意混杂字符串不能通过明文电话校验；Worker/API 复用同一实现，保留合法格式化手机号和中国区号兼容。
4. F04：缓存有来源指纹，源变化清除旧明文/掩码；解析失败不能沿用失效号码。新列 nullable，旧缓存不能伪造为已验证来源。
5. F05：接近上限时继续缩小窗口；到最小粒度仍不能证明完整时，显式失败，调用链不能把它记录为完整成功。
6. F06：同一主线索的跟进/撤销等状态写入按固定顺序串行化并重新读取；不信任 identity map 的旧对象。冲突返回现有业务冲突响应。验证 SQLite 旧缓存场景及隔离 PostgreSQL 并发场景（环境不可用则明确记录）。
7. F07：操作 actor 保留 store_scope_mode。只有明确的全店范围可访问全店；指定范围按当前所属门店；空范围拒绝。缺失范围不得默认扩大普通管理员权限。所有电话、跟进与列表操作标记共用同一范围判断。
8. F08：一页多个缺失电话订单批量查询/批量解密并复用客户端；重复读取有来源绑定且有界的缓存策略。GET 不偷偷提交业务写事务，不缓存权限结论。
9. F09：真实详情请求失败进入现有错误展示；显式演示模式仍可用。
10. F10：overview 按筛选范围内唯一订单聚合；分子采用该订单在范围内轮次的布尔汇总，分母也是唯一订单；当前可跟进仍要求当前有效轮次。保留现有门店/时间/正式轮次筛选。
11. F11：候选、批次、决策、审计、规则、评分等分页资源保留 pagination，传 page/page_size；使用已有 TablePagination。当前页选择与翻页一致，禁止旧响应覆盖新页。

## 共享合同与集成边界

- B 新建 `src/dy_data/phones.py`：`normalize_phone(value) -> str`、`mask_phone(value) -> str`、`is_online_cipher(value) -> bool`、`phone_source_fingerprint(*, plain_phone=None, cipher_text=None) -> str | None`。指纹只表示选中的规范化联系方式来源，使用摘要，不记录原始密文日志。
- B 管理 `ClueCenterOrder.phone_source_fingerprint` 及唯一追加迁移；其他代理不得修改 models.py 或迁移文件。API 集成由主代理消费该字段和共享函数。
- `_data.py` 由主代理独占。B 若发现 API 需要调整，报告函数和合同，不修改该文件。
- `clue_follow_up_state.py`、`routes/clues.py` 由主代理独占。C 只处理前端 actor 消费，不定义后端权限真相。
- 主代理自有修改在当前仓库；A/B/C 从相同基线建立 detached worktree，以补丁顺序合入。

## 验证与审查顺序

1. 每组先建立失败回归，再实现；针对 F 编号报告前后结果。
2. 控制器核对规格覆盖和 scope，规格通过后独立审查代码正确性、权限、事务、迁移和兼容性。
3. 确认问题回到最小修复，再复查，不以 worker 自报成功作为最终验收。
4. 相关线索/权限/采集/迁移 pytest、前端生产构建、真实 API 成功/失败与前端分页/详情异常运行时验证。
5. 运行完整 pytest；若环境门禁导致跳过或失败，区分产品缺陷与环境问题并保留准确证据。
6. `git diff --check`、迁移单 head、套包锁与全局文档校验、改动范围审查。
7. 回填 Linear 为等待审查/验收状态，不自行 Done；更新本台账与开发日志，不更改其他 issue。

## 决策和验证记录

- 2026-09-07：Linear 重连成功，新建 DYDATA-88，用户既有开发授权继续有效。
- S4 路由与计划一致性通过；verify-task-context 环境与文件检查均通过。
- 开发前工作区只有既有未跟踪规格。生产状态和数据未访问。

- 独立 D/E 规格及质量复核通过：修正投影门店滞后授权差异、无分页导出参数上限，401 订单分块已验证。
- PostgreSQL 并发跟进/关闭/撤销 4 项通过；状态相关 29 项通过。迁移并发升级门禁通过，head=`20260907_0051`。
- 运行关联索引器时发现既有历史/忽略目录导致 702 条断链及大范围生成噪声；仅恢复本次生成的两个 index 文件，未纳入 F 修复。
- Foundation 新增待改请求见 [来源验证与概览合同](foundation-plans/foundation-change-requests-dydata-88-clue-fixes.md)，不直接改上游目标设计。


- 最终各组规格与代码质量审查通过。全仓回归 2427 passed / 129 skipped，迁移文件另计 58 项全部通过；最终历史轮次补丁再跑 27 项 PostgreSQL/电话/锁测试与 213 项线索/流水线测试，全部通过。Web build、11 项浏览器专项、唯一 migration head、套包锁及 git diff --check 通过。
- 最终实现增加共享历史轮次刷新 helper，仅按已锁 master 的数据库归属刷新会话 dirty rounds；不会提前锁 center。当前和较早历史轮次均经真实 lost 回归验收。
