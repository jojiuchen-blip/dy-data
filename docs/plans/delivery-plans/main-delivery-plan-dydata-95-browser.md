# DYDATA-95 虚拟浏览器连接可靠性

> **版本**：v1
> **发布日期**：2026-09-12
> **适用范围**：DYDATA-95
> **开发模式**：单任务串行

## 0. 本计划使用指南

用户已授权先恢复采集再修根因。13:39 绑定导出2956条成功；上游收集完成。需求权威为DYDATA-95，现有业务契约不变。

### 0.1 PRD 加载约束

读取 docs/prd/mainprd-dy-data.md 及基础索引，仅改部署运行时。

### 0.2 读前门禁 / AI 自检清单

基于生产6dde722a独立工作区。保留profile、密码、当前导出和其他任务代码。

### 0.3 完成前验证门禁

延迟就绪、进程退出、重试耗尽、健康检查故障测试；Linux容器验证。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Python | >=3.12 | `python --version` |
| Node | >=22 | `node --version` |

## 1. 差距基线

Xvfb未就绪即启动桌面；子进程退出无恢复；健康检查仅CDP端口。

## 2. 分工与边界

本任务串行执行。仅管理桌面子进程与探针，不修改登录认证策略、数据模型和业务规则。

## 3. 执行阶段

### Phase 0：浏览器运行可靠性

Entry Criteria：DYDATA-95授权且采集已恢复。Exit Criteria：针对性测试及运行验证通过。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T0.1 | [T0.1](sub-delivery-plan-dydata-95-browser-T0.1.md) | 进行中（已部署，待用户验收） |

## 4. 任务看板

[任务看板](task-kanban-dydata-95-browser.md)

## 5. 发布闸门

2026-09-12 发布验收：提交 `3d5ac35a` 已推送main，15:53:29（上海时间）部署完成。主CI [34679602345](https://github.com/jojiuchen-blip/dy-data/actions/runs/34679602345) 全部通过，3013 passed / 167 skipped，Web与四个镜像构建成功；81项本地相关回归及隔离Linux桌面退出恢复验证通过。

重复发布流水线34679602374的镜像构建耗时较长，在服务器部署前取消；复用同一SHA的完整绿色CI，使用项目现有 `deploy/tencent/deploy.sh` 发布。服务器日志 `deploy-dydata95-20260912.log`，退出码0，last-deploy.json SHA一致。源码上传后SHA256一致才解包执行。新runtime模块SHA256为 `9f972b34e4bd86f5702d905b0bfcb7095a57e06f032375a953903700ff3f09fa`，与线上相符。

浏览器、API、worker、ops-agent、Postgres健康；完整CDP/VNC/WebSocket探针通过；网站200。部署后受控绑定导出2956条、失败0，实际落库已核验。未修改密码或持久化profile。

保留五个服务的 `rollback-dydata95-20260912` 镜像；环境备份由部署脚本完成，数据库备份 `pre-migrate-20260912T074524Z.dump` 为829809883字节、0600。等待用户验收，交换内存保护恢复条件继续由DYDATA-90承接。

## 6. 风险与应对

桌面独立重启保留Chromium；反复失败停止快速重试并保持不健康；真实登录失效仍需用户登录。

## 7. AI 执行示例

模拟延迟显示器，验证桌面等待；杀死测试桌面子进程，验证有限重启及健康探针。

## 8. PRD → 任务反向索引

| PRD | Task | 子开发计划 |
|---|---|---|
| DYDATA-95；docs/prd/mainprd-dy-data.md | T0.1 | [T0.1](sub-delivery-plan-dydata-95-browser-T0.1.md) |
