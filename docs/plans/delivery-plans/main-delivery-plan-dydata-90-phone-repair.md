# DYDATA-90 号码补偿交付计划

> **版本**：v1
> **发布日期**：2026-09-10
> **适用范围**：DYDATA-90 worker号码补偿
> **开发模式**：isolated-worktrees

## 0. 本计划使用指南

先读取主计划、任务看板及T0.5子计划。只修复worker号码派生缓存，不扩展API凭证、不改变正式分配与财务事实。

### 0.1 PRD 加载约束

读取mainprd §1、Foundation线索联系人接口与中心表、J01/J03。宿主源码及现行号码指纹契约优先。

### 0.2 读前门禁 / AI 自检清单

用户已授权修复，DYDATA-90保持In Progress；独立工作树；上游收集canProceed=true。

### 0.3 完成前验证门禁

真实PG验证号码字段提交与旧源保护；全仓pytest、Web构建、CI与生产号码读取成功后才声称修复。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Python | >=3.12 | `python --version` |
| Node | >=22 | `node --version` |

## 1. 差距基线

214条新分配没有号码缓存，另5条旧源指纹失效；API无抖音凭证，列表兜底不能解密。worker已有受治理客户端。

| 差距 | 影响 | 对应任务 | 状态 |
|---|---|---|---|
| 已分配线索缺可用号码缓存 | 列表和号码读取为空 | T0.5 | 进行中 |

## 2. 分工与边界

主代理负责计划、复核、整合、发布与生产验收；worker负责独立工作树内实现与测试。不得写原始号码到日志，不更改分配/状态/财务数据。

## 3. 执行阶段

### Phase 0：号码恢复

**Entry Criteria**：缺口已定位，用户授权修复。

**Exit Criteria**：有界补偿和失败恢复通过测试，生产219条缓存缺口已解释并处理。

| Task | 子开发计划 | 状态 | 完成日期 |
|---|---|---|---|
| T0.5 | [sub-delivery-plan-dydata-90-phone-repair-T0.5.md](sub-delivery-plan-dydata-90-phone-repair-T0.5.md) | 进行中 | - |

## 4. 任务看板

[任务看板](task-kanban-dydata-90-phone-repair.md)

## 5. 发布闸门

- [ ] 专项和真实PG回归通过。
- [ ] 全仓、构建、CI与备份门禁通过。
- [ ] 生产号码可用、无重复分配、自动超期关闭。

## 6. 风险与应对

| 风险 | 应对 |
|---|---|
| 解密等待阻塞业务 | 独立有界批次，短网络超时、单次重试、受治理限流 |
| 源变化后旧号码回写 | 回写前复核当前来源与轮次、条件更新 |
| 失败首行饥饿或频繁解密 | 持久旋转游标、失败冷却、有效缓存跳过 |
| 生产凭证扩散 | 仅worker解密，API不新增凭证 |

## 7. AI 执行示例

按T0.5先构造失败用例，再实现并回读验证；仅提交owned文件，主代理整合。

## 8. PRD → 任务反向索引

| PRD | Task | 子开发计划 |
|---|---|---|
| `docs/prd/mainprd-dy-data.md` §1 | T0.5 | [T0.5](sub-delivery-plan-dydata-90-phone-repair-T0.5.md) |
| `docs/prd/foundation/foundation-api-clue-center/lead-query-and-contact.md` | T0.5 | [T0.5](sub-delivery-plan-dydata-90-phone-repair-T0.5.md) |
