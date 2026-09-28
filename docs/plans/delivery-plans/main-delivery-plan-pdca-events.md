# PDCA 只读证据快照 Main Delivery Plan

> **版本**：v1
> **发布日期**：2026-09-28
> **适用范围**：PDCA只读事件证据
> **开发模式**：solo-local
> **上游发现结论**：canProceed=true
> 用户本次明确免建票并授权开发；不部署、不迁移、不回填、不改采集或指标。需求以本任务授权及 [接口规格](../../api/pdca-event-snapshot.md) 为准。

## 0. 本计划使用指南
先读规格、任务看板和子计划，按测试驱动完成本次独立 API。
### 0.1 PRD 加载约束
读取 mainprd-dy-data.md 的全局权限/整数分规则；本次增量以接口规格为验收依据。
### 0.2 读前门禁 / AI 自检清单
核实授权、只读边界、隔离工作区和真实模型，不推定源历史存在。
### 0.3 完成前验证门禁
执行子计划验证，保存真实输出，未运行的生产验收明确待办。

## 环境依赖声明
| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Node.js | >=18 | `node -v` |

Python 3.12 与 requirements.txt 安装到工作区 .venv；生产 PostgreSQL 验收不连接生产写库。

## 1. 差距基线
现有 observation-v1 不投影有效退款、质量问题或批次，且无一致快照。源码是可更新行而非完整历史日志，采集完整水位与订单实收通用等价尚未证明。
## 2. 分工与边界
本任务负责经营引擎源码与合成验收；原 PDCA 任务负责客户端、指标与实验。不得修改原任务目录。
## 3. 执行阶段
### Phase 0：独立证据契约
**Entry Criteria**：用户授权、治理锁有效、隔离工作区、源模型已核查。
**Exit Criteria**：合成测试通过，schema、映射、未知和失败语义可交接，生产验证仍单列。
| Task | 子开发计划 | 状态 |
|---|---|---|
| T0.1 | [sub-delivery-plan-pdca-events-T0.1-contract.md](sub-delivery-plan-pdca-events-T0.1-contract.md) | 进行中 |
## 4. 任务看板
[task-kanban-pdca-events.md](task-kanban-pdca-events.md)
## 5. 发布闸门
本任务仅本地开发。发布必须独立审核；完整采集、历史事件和实收语义未证明前 publishable=false。
## 6. 风险与应对
快照有内存/行数/有效期上限；源缺失返回未知或503，不伪造0。快照只在当前服务进程有效，多实例需要亲和路由或另行设计共享存储。
## 7. AI 执行示例
先运行失败测试，再实现新 route/service/schema/只读连接，运行专项与全仓回归，记录未具备的数据和发布项。
## 8. PRD → 任务反向索引
| PRD | Task | 子开发计划 |
|---|---|---|
| mainprd-dy-data.md 全局设计规则；增量接口规格 | T0.1 | [子计划](sub-delivery-plan-pdca-events-T0.1-contract.md) |
