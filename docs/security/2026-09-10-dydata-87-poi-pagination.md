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
- 证据缺口：生产备份、部署、回填及重算尚未执行。并行 DYDATA-90 正在部署 93ace56，必须协调后重新核对集成基线，不能覆盖它。

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

- SEC-POI-03：并行发布尚未协调，生产备份、最终版本集成与运行验证未完成。
- 缺失映射回填与结算验收尚未执行，不可据此宣称页面修复完成。

## 6. 放行结论

- 最终结论：`BLOCK`，生产发布协调和定向修复验收未齐；代码和本候选 Python 安全检查没有新增高危阻断项。

## 7. 整改建议

- 发布前先协调 DYDATA-90 的正在执行部署，重新确认最终基线、集成验证和备份。
- 仅修复确认的 91 个映射及受影响结算，保留既有冲突、真实确认和财务历史；上线后回读三页面及金额。
- 后续跟踪开发依赖 Low 与既有 assert 告警；不扩大为全系统安全结论。

## 8. Waiver 记录（如有）

无。未以本地测试或旧 CI 豁免当前候选门禁。
