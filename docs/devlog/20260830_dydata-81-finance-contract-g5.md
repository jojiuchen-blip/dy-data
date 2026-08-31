# DYDATA-81 G5 财务页面合同交付日志

## 当前状态

- 日期：2026-08-30 至 2026-08-31
- 阶段：S4 / T5.7 G5
- Linear：DYDATA-81（In Progress，不得由执行任务自行关闭）
- 分支：`codex/dydata-81-finance-contract`
- 基线：`origin/main@df617e7`
- 控制器规格：`docs/plans/2026-08-30-dydata-81-finance-contract-controller-spec.md`

## 本轮授权与范围

Owner 已书面授权完成六个财务页面的最小实现、自动化测试、隔离 UAT、受控生产部署和部署后验证。页面内部结构与交互以冻结原型 `codex/dydata-19-finance-mock@9a574fa` 为合同；视觉、Shell、权限和响应式使用主应用规范；数据逻辑只来自 Linear 与正式 API/Schema。

本轮固定业务裁决：推广费展示 5 张指标卡，“待开票金额 = 审核未通过金额 + 账期未开票金额”；财务导入 SAP 成为当前有效值，批量导入与单条矫正均保留门店原值、财务值、操作人、时间、版本和审计；账单异议检测必须是真实、持久化、刷新可追溯的异步流程，自动检测不替代财务业务裁决。

## 已通过门禁

- project-manager-suite 2.0.1 锁校验通过。
- 全局文件校验 0 error / 0 warning。
- S3 计划结构校验通过：19 个 Task、13 个必需章节、0 缺项、0 模糊验收。
- S4 计划一致性通过：唯一进行中 Task 为 T5.7，主计划/看板/子计划一致。
- coding-standards 环境自检 `envReady=true`，任务上下文 `canExecute=true`。
- 基线 Web production build 通过，仅保留既有 chunk-size warning。
- 财务高风险组合回归：167 passed，覆盖 API、权限、导入、G2、异步检测 Worker、部署合同和前端财务合同。
- 完整非视觉回归：1233 passed、2 skipped、0 failed；完整视觉/浏览器回归：242 passed、0 failed；总计 1477 项，1475 passed、2 skipped、0 failed。
- DYDATA-81 专项浏览器回归：7 passed，覆盖异步检测刷新追溯、SAP 单条矫正与审计、六页三档布局、导入展开和查询状态保留。
- 390×844、768×1024、1440×900 真实 FastAPI UAT：3 passed；32 张主系统截图与 18 张冻结原型同尺寸参考图已生成。
- Web production build：717 modules transformed，通过；仅保留既有 chunk-size warning。
- `git diff --check`、Python `compileall`、Alembic 单头检查通过；当前唯一 head 为 `20260830_0044`。

## 本轮实现

- 推广服务费固定为 5 张正式指标卡；待开票金额由审核未通过和账期未开票两部分组成，列表、汇总与导出共用筛选口径。
- 管理服务费查询从当前确认账单出发 LEFT JOIN 当前发票，未开票账单不再从列表消失；全额扣减才进入已结算。
- 推广/管理订单接口补齐冻结账单归属门店、服务店、有效 SAP 与结算日期字段别名；页面不读取当前门店主数据覆盖历史快照。
- 推广/管理导入入口改为页头按钮，展开后模块固定在指标卡下方；导入记录页保持只读，不增加上传入口。
- 财务门店基础信息与 SAP 差异页分离查询；差异页只返回不一致记录。批量最终 SAP 与单条矫正均写入 type-1 财务链，保留门店值、财务值、操作者、时间、版本、审计与历史账单快照。
- 账单异议检测落入持久化 `job_runs`，API 创建/读取任务，worker 负责原子 claim、陈旧任务恢复、有限重试与失败落盘；自动检测不改变异议业务状态。
- 生产部署工作流改为 fail-closed：`TENCENT_START_WORKER` 必须显式为 `true`，部署后验证 worker 处于 running。
- 导入撤销改为按正式 `batch_id` 查询批次，避免把外部批次标识误当数值主键；锁顺序测试会在路由提前返回时给出明确失败。
- 异步检测使用条件更新和版本围栏，陈旧 worker 不能覆盖已被重新领取的任务；部署先验证 worker 再切换 API/Web/代理。
- SAP 有效值把 type-1 控制版本（含 tombstone）与实际有效值分离，禁止历史 type-2 记录在 tombstone 后回退生效。
- 导入记录页在同一路径查询参数变化时保持筛选、分页与详情状态可追溯。

## UAT 证据

- 主系统：`output/playwright/dydata-81-g5/<viewport>/`。
- 冻结参考：`output/playwright/dydata-81-g5/reference-frozen-9a574fa/<viewport>/`。
- Linear 证据附件：`9d7814e9-3c55-4461-8e11-10a6575a8727`，50 张截图，SHA-256 `7593e531f73656e7395f81cb0a8cbb63bd5df0c5872dd1ace813c96b977f9059`。
- 4181 当前常驻进程实测为旧门店端构建且没有财务端角色切换，因此没有把它当作冻结证据；固定提交原型改在隔离端口启动后采集，采集完成即停止。
- UAT 使用真实 FastAPI 应用、ORM 与正式 API 路由；测试数据库隔离，不通过浏览器 route mock 提供财务数据，也不向正式环境写入演示金额、日期、门店、发票或状态。

## 基线回归

首次全量基线结果：`1415 passed, 2 skipped, 3 failed, 263 warnings`。失败均位于既有 `tests/test_visual_smoke.py`：

1. 390px 销售页未找到 `.sales-echart`。
2. 1440px 线索明细未找到预期数据工作区/分页组合。
3. 1440px 旧订单详情未找到预期数据工作区/分页组合。

这些失败发生在本轮业务代码修改前，未直接归因于 DYDATA-81；后续已独立复跑、定位并在最终完整视觉回归中归零，没有豁免。

根因核查确认三个失败均为视觉测试就绪条件不足：标题先于异步图表/表格/分页挂载。销售页 390px 旧断言复跑 6 次失败 3 次，1440px 冷启动也出现同类波动；旧订单页在内容节点就绪后布局指标为 `frameWidth=1332`、根页面垂直溢出 0、分页与内容区均在 900px 视口内。修复仅把测试等待目标改为实际图表数量、表格容器和分页节点，没有修改销售、线索或订单业务页面。聚焦 5 项随后连续 3 轮通过，共 15 次无失败。

最终完整视觉文件为 `242 passed, 0 failed`。财务 mock 管理员 fixture 补齐 FIN01～FIN06 后，六页不再因测试角色缺页权限停留在无权态；通用首屏就绪等待调整到 30 秒，销售指标卡改为等待异步数量稳定。业务断言、错误态、布局和溢出阈值未放宽。

## 独立审查

- 两轮独立复审确认四项 Important 已关闭：异步检测 CAS 竞争、worker 验证晚于流量切换、SAP tombstone 后旧类型回退、`/finance/imports` 同路径 query remount 状态丢失。
- `objectKey` 已先做 trim、大小写和 URL 形式的 fail-closed 校验，但这只关闭客户端 URL 绕过，不构成受控上传合同；对象存在性、归属、门店/账单绑定、读取和清理仍由 DYDATA-82 定义。
- 除已知 DYDATA-82 外，复审未发现新的 Critical/Important；这不替代目标 PostgreSQL、PR/CI、备份和线上 smoke 门禁。

## 当前发布阻塞

- DYDATA-82 于 2026-08-31 重新从 Linear 实时核查：仍为 Backlog / Needs Definition，0 条评论；证明材料受控上传仍缺存储、文件类型/大小/数量、留存、安全和审计合同。DYDATA-19 已把证明材料定义为新建异议必需项，因此生产发布保持 BLOCKED；不得用自由文本 `objectKey` 或前端假上传绕过。
- 任一正式字段来源、业务口径、迁移、权限、CI、备份、UAT 或线上 smoke 未通过时不得部署。
- 本机未安装 Docker 与 `psql`，目标 PostgreSQL 发布门禁必须由仓库 CI 服务容器执行；GitHub CLI 当前未登录，若发布阶段仍无可用 Git 凭据，则无法创建/观察 PR、CI 或触发受控生产流程，必须停止并报告，禁止绕过。

## 下一步

1. 将最终测试、UAT、独立审查、本地提交和发布阻塞回填 DYDATA-81，Issue 保持 In Progress。
2. 在 DYDATA-82 完成并通过安全门禁，或 Owner 明确书面批准排除“新建异议”且认可既有异议处理可独立发布之前，不创建生产发布。
3. 后续恢复发布时必须先取得 GitHub/CI 权限、目标 PostgreSQL门禁、worker 单实例归属、备份与回滚证据，再按既有腾讯云 workflow 部署。
