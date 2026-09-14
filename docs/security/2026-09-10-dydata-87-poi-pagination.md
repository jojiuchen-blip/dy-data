# DYDATA-87 分页修复安全扫描

## 1. 扫描范围

- 扫描模式：partial，本次增量及直接边界。
- 覆盖域：代码、输入校验、秘密模式、依赖清单、CI 并发与现有权限边界。
- 未覆盖域：全历史秘密扫描、渗透测试与 OS 全量漏洞；候选镜像 Python 精确依赖已补证。

## 2. 输入证据

- 执行计划：docs/plans/execution-plan.md；DYDATA-87，用户授权继续修复。
- 代码：58413c5 到 bab2612 的客户端、采集器、映射仓储、测试及 CI 增量；未修改依赖、登录或财务确认接口。
- 验证：集成专项 96 passed / 2 skipped；POI 专项 13 passed / 2 skipped；Web build 通过。CI 34427668279 成功，全量 2736 passed / 157 skipped，真实 PostgreSQL、填充库、财务导入和含 POI 的账单并发门禁均单独通过。另有补映射保持已确认推广来源的两项局部测试通过。
- Bandit 三个生产 Python 文件 3659 行：High 0、Medium 0、Low 6；私钥头、常见 GitHub/AWS/live token 增量模式候选 0。
- pip-audit requirements 解析审计无已知漏洞，不替代 Linux 候选镜像审计。npm 锁文件审计 High/Moderate/Critical 0、Low 1。
- 生产服务器五个候选镜像构建通过，未启动替换业务服务。只读、无网络、无挂载的临时容器提取实际包清单：API/worker 清单完全一致，精确 pins 审计无命中；browser/ops 命中分类见下文。镜像 digest 和完整 pins 仅存被忽略的运行证据，不含凭证。
- 2026-09-10 13:22 复核：DYDATA-90 部署已完成，生产仍为 93ace560；候选 65ee07b 已合并其主线，CI [34433601182](https://github.com/jojiuchen-blip/dy-data/actions/runs/34433601182) completed/success，记录为 2767 passed / 159 skipped，真实 PostgreSQL 独立门禁通过。五个候选镜像摘要与先前清单一致，未重新构建；四个 Python 镜像有效包版本与同日审计清单无差异，未声称重新在线扫描。
- 生产备份 dump 为 681896902 字节、权限 600，TOC 为 93917 字节且可读取；SHA256 为 d95183ddaea750a9a0ae67f0e32d325730bf967610595270c5bd70425f9422c5。未做隔离恢复试验，不将 TOC 可读称为恢复验证。
- Compose 与 Nginx 在 93ace560..65ee07b 无差异；登录资料及导出数据使用既有命名卷，代理仍绑定现有部署配置。回滚须保留旧镜像，不删除卷、不重置会话、不用备份覆盖部署后真实业务写入。
- 13:55 部署证据：已持发布锁优雅停止旧 worker，五个旧镜像由运行 image ID 固定回滚 tag，使用原 Compose 无 build/pull/migrate 切换五服务并重建 proxy，最后恢复 worker。五个运行 image ID 与候选一致，四个根因文件 SHA256 与候选 release 一致；API/worker/browser/ops healthy，Web 经 HTTP 验证。
- 线上 smoke：首页、ranking、settlement、授权元数据为 200，未登录 auth/me 为 401；browser CDP 返回有效协议，worker SELECT 1、队列入口仅导入和 priority_daily 保持检查通过。最初手写 smoke 的模块路径错误已修正，该失败未出现在服务启动日志；未调用队列函数或创建设备授权。
- 部署记录为 runtime-only，运行候选 65ee07b，服务器 Git checkout 保持原 ba3976ca，五服务摘要已记入 last-deploy；不能拿旧源码 HEAD 当运行版本。未删除登录卷或变更 env；已有用户会话经 UI 的实际验收仍待后续，不以 401 smoke 代替。
- 剩余证据缺口：限定回填的完整发布/失败恢复测试及登录后三页面数据验收；尚未执行人工补算。

## 3. 发现项

- SEC-POI-01：esbuild 构建依赖存在 Windows 开发服务器条件性 Low；生产 Web 为静态构建，本次不启动该服务器。
- SEC-POI-02：Bandit 的五处既有 assert 与一处将公开 token endpoint URL 当密码的告警，未处于本次新增分支；不是发现生产凭证。
- SEC-POI-03：最终运行验收及发布协调缺口。旧版本扫描报告不作为本候选安全通过证据。
- SEC-POI-04：browser 的 setuptools/zipp 命中已核对实际 Debian 修订 66.1.1-1+deb12u2 / 1.0.0-6+deb12u1 和供应商记录；旧漏洞有回移修复，setuptools 的 macOS 文件名问题不适用于本 Linux 镜像。PyPI 不识别的 python-novnc 按实际 novnc 1:1.3.0-1 核验。来源：[setuptools](https://security-tracker.debian.org/tracker/source-package/setuptools)、[zipp](https://security-tracker.debian.org/tracker/source-package/python-zipp)、[novnc](https://security-tracker.debian.org/tracker/source-package/novnc)。未将原始审计退出 1 当作未经分类的阻断。
- SEC-POI-05：ops-agent 的 pip 25.0.1 命中去重后 5 Medium / 1 Low，均为安装/下载路径。通过 GitHub advisory API 逐项确认严重性；既有维护责任与 2026-09-16 截止继续有效，本次不在生产安装包。不是零风险，也不属于高危豁免。

## 4. 风险分级

- Critical / High：本次增量与候选 Python 审计未确认此级别未修问题。
- Medium：SEC-POI-05 的五项既有 pip 安装/下载风险，DYDATA-87 发布维护者在 2026-09-16 前跟踪升级；非业务接口直接使用 pip。
- Low：SEC-POI-01；维护者在后续依赖维护中处理。
- 输入证据不足独立阻断发布，不虚构漏洞等级。

## 5. 阻断项

- SEC-POI-03（代码切换前置已解除）：独立操作复审完成；从运行容器固定五个旧镜像回滚 tag 和摘要记录，备份齐备，无 running/queued 作业、迁移版本 0053、快照迁移异常 0。发布持有独占锁并再次核对版本；先让旧 worker 优雅退出，切换五镜像后检查真实 HTTP/CDP/数据库和实际摘要，最后恢复 worker。恢复后允许既有 priority_daily 正常任务，禁止额外启动本次人工全量重算。失败先停新 worker，恢复旧镜像再重建代理，不恢复数据库覆盖真实写入。
- 缺失映射回填与结算验收尚未执行，不可据此宣称页面修复完成。

## 6. 放行结论

- 最终结论：`PASS`，仅放行 65ee07b 已核验镜像的上述受控代码部署，不是问题完工或数据补算放行。若 worker 无法优雅退出、版本漂移或运行检查失败，停止切换/按旧镜像回滚。91 映射/120 券修复的完整发布及恢复保护仍未验收，保持独立 `BLOCK`，不得借本结论执行补算或宣称三页面修复完成。

## 7. 整改建议

- 使用已核验 65ee07b 制品进行受控切换，不在切换时重建镜像；先记录旧制品及配置回滚方式，重新检查运行任务，切换后回读版本和健康状态。
- 仅修复确认的 91 个映射及受影响结算，保留既有冲突、真实确认和财务历史；上线后回读三页面及金额。
- 后续跟踪开发依赖 Low 与既有 assert 告警；不扩大为全系统安全结论。

## 8. Waiver 记录（如有）

无。未以本地测试或旧 CI 豁免当前候选门禁。
