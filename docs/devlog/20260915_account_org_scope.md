# 2026-09-15 账号组织权限与批量开通

## 需求与授权

用户要求五级组织账号数据范围、线索与结算统一权限、三项打榜全量开放，门店搜索多选与导入优化，合并主分支并部署；后续追加标准账号开通模板与批量账号创建。
Linear当前只能访问其他团队，用户知晓后再次要求直接执行；本轮保存本地需求LOCAL-ACCOUNT-SCOPE-001，不在其他团队建票。

## 设计与实现

复用角色和门店授权链，org_scope按请求动态解析有效下属门店。A03固定全员允许，仅排行与排行导出使用全局数据，业务明细维持权限隔离。迁移0059保留既有账号，组织绑定存在时阻止有损降级。
门店弹窗内关键词/部分ID搜索、复选和全选、跨搜索保持；xlsx/csv校验预览后应用。
标准账号开通表最高管理员批量上传、预览后整批创建，随机初始密码仅结果下载可见，审计无密码。

## 审查与修复

独立审查已修复XLSX维度膨胀、无维度Excel、CSV超长字段、标识归一化、用户名和外部账号标识冲突、矛盾范围字段、批次结果覆盖、事件循环阻塞。

## 实施期验证记录

- 账号、认证、CLI、结算、打榜与真实浏览器组合：79 passed。
- 迁移专项：61 passed。
- 项目套件：122 passed；结构、协议和锁检查通过。
- Web build通过。模板由本次应用生成器生成并回读校验表头/文本ID/下拉列表，并使用artifact-tool渲染核对填写说明。
- 全量视觉回归261 passed；相关回归331 passed；剩余CLI专项20 passed。
- 初次全仓运行2793 passed、169 skipped、13 failed、1 teardown error。13项失败已修正旧断言或切换正常Python运行时并在上述专项全部复验通过；Windows Vite退出超时需由Linux CI复核。未将初次运行报告为全绿。
- CI、主分支合并与生产部署待执行，未宣称上线。
- PR #33首轮Linux CI：3078 passed、169 skipped、1 failed，无Windows退出错误。失败为历史viewer映射全局管理员时D02被误拒绝；已与认证兼容规则对齐，64项相关测试通过，并补充区域管理员账号管理拒绝断言。

## Foundation漂移

新增账号org_scope及批量导入接口，已记录在docs/api-contract.md和长期账号规则；foundation正式回捞待后续治理同步。

## 证据入口

本地output/account-scope、output/账号开通模板.xlsx及测试JUnit为运行证据，不提交真实账号或密码文件。

## 最终发布结果（2026-09-15）

- [PR #33](https://github.com/jojiuchen-blip/dy-data/pull/33)已合并，代码提交35547e2，主分支发布提交eeca61e79a7ae9e78c56bc5026e85175d0e52846。
- [最终PR CI](https://github.com/jojiuchen-blip/dy-data/actions/runs/34926780000)与[主分支CI](https://github.com/jojiuchen-blip/dy-data/actions/runs/34928794337)成功，3079 passed、169 skipped；PostgreSQL闸门、治理校验、Web build与全部镜像构建通过。
- [腾讯云部署34928814248](https://github.com/jojiuchen-blip/dy-data/actions/runs/34928814248)成功；生产发布前复验3079 passed、169 skipped。
- 数据库备份完成：`/opt/dy-dashboard/logs/backups/pre-migrate-20260915T050131Z.dump`。生产迁移0058→0059成功，Worker队列smoke通过，部署完成时间2026-09-15 05:04:42 UTC。
- 线上首页200，资源更新为`index-DfRlddJp.js`；`auth/me`及新增账号模板接口未登录均401，Agent生产发现接口200。账号创建与范围授权已在真实API/浏览器测试环境验证；生产只读核验未创建测试账号。
- 账号模板由应用生成器生成并回读、渲染验证；SHA256：`9209EB2E477ED6010DE329C5D9DAE7DBC055F28EFA46E0C22EA251838A05ADD4`。后台下载模板会附带当前门店和组织名单。
- 正式计划、子计划及任务看板完成状态同步。后续建议：将已记录的org_scope和导入接口变化纳入正式foundation治理同步。
