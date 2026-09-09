# 开发日志 — 2026-09-10

## DYDATA-90 采集修复发布

- 用户明确授权提交、部署；修复提交6d130598，生产提交8a753e9f094b1b7546127921949c19e28d04571a，本地及远端main已同步。
- 集成origin/main以保留生产已有财务与浏览器依赖修复；新增20260909_0052汇合两个0051，不修改历史迁移。
- 原结算指标视觉失败来自即时count断言抢在异步文案渲染前执行；改用等待式断言，保留全部文案与布局断言。
- 本地211项集成、2项分支升级、6项界面验证通过；独立合并复查无阻断。
- [发布流水线](https://github.com/jojiuchen-blip/dy-data/actions/runs/34370984418)成功：真实PostgreSQL门禁、2685 passed / 152 skipped、前端与全部发布镜像构建通过。
- 生产于北京时间00:10:52完成发布；API、worker、browser、ops-agent、PostgreSQL健康，Web和proxy运行。
- 7份运行源文件与发布Git对象SHA256完全一致，订单修改查询入口可调用；数据库为20260909_0052，新增可空phone_source_fingerprint字段存在。
- 公网首页200，未登录auth/me及MCP401，agent manifest200。
- auto_sync_enabled=false，未开启旧同步；本次未证明完整日数据采集或历史补齐成功。新日批、两小时维度刷新和动态预算由DYDATA-90继续承接。

## 备份与恢复

- 环境备份：/opt/dy-dashboard/logs/backups/pre-production-cutover-20260909T160757Z.env。
- 数据库备份：/opt/dy-dashboard/logs/backups/pre-migrate-20260909T160823Z.dump。
- 原api、worker、web、browser、ops-agent镜像保留rollback-dydata90-20260909标签。必要时用原release的compose与保留镜像重建应用服务，--no-deps避免触发迁移；本次新增字段兼容原应用，不通过删列回滚。
- 详细脱敏核验：output/dydata90-production-postflight.json、output/dydata90-deploy-run.txt。

## 后续

- 实施并验收新的调度机制后，再开启自动同步。
- 本次没有新增foundation契约，迁移汇合仅整合既有字段设计。
- 经验：发布前核对运行制品和最新主线，不能只依据服务器仓库HEAD。仅记录，不新增全局规则。
