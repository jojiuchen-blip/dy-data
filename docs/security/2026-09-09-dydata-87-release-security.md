# DYDATA-87 发布安全扫描报告

> 2026-09-09 最终补证结论：本次补丁范围安全检查 `PASS`，不是 CI、最终制品或部署通过。完整 npm 锁文件审计 High/Medium 为 0，仅 esbuild Low 1；主控补交 Windows 解析环境 Python 63 依赖审计零已知漏洞。最终 Linux candidate image 依赖审计由主控发布硬门禁继续承接，未通过不得发布。下文初次结果仅为整改轨迹。

## 1. 扫描范围

- 扫描模式：partial，2026-09-09 发布候选增量及其直接安全边界；不是全系统渗透测试。
- 覆盖域：code、secrets、dependencies、API input validation；按用户要求额外检查生产授权、门店/管理员权限及发布配置。
- 范围：API dashboard/_data/models、0051、worker settlement/capture/coordinator/generator、前端本次变更及依赖锁文件、相关 Dockerfile/compose/CI。包括未跟踪新增文件。
- 未覆盖域：生产写操作、互联网攻击测试、云账号策略、完整 Git 历史秘密扫描、最终镜像 OS/SBOM 漏洞扫描、全量历史 SQL 告警逐项验证。
- 使用 security-scan 技能及 gate-contract、scan-scope、risk-rating-policy、report-template 四份必需参考。未安装工具、修改依赖或运行 audit fix；仅公开 npm 包名/版本元数据发送到审计服务，源码与秘密不外传。

## 2. 输入证据

- 执行计划：`docs/plans/execution-plan.md` T5.7、`docs/plans/2026-09-09-dydata-87-settlement-invoice-controller-spec.md`。最新用户已确认两费共同核销月份/日费率/核销实收并授权主控交付；不授权代理替用户确认真实账单、开票或操作资金。
- 基线：HEAD `e401ce443168b339352338a35b5518b8c29071ab`，HEAD 到 working tree；扫描期间其他代理继续修改 worker，故不是不可变发布制品认证。
- 套件检查：本轮 `verify-suite-lock.mjs` 通过，2.0.1。
- 依赖差异：首次扫描时上述依赖文件相对 HEAD 无修改；随后主控修改 Web 锁文件消除 High/Medium，本代理已独立复跑审计。无依赖改动不等于无漏洞。
- 本轮命令证据：
  - `npm --prefix apps/web audit --package-lock-only --ignore-scripts --json`：默认镜像端点 404/NOT_IMPLEMENTED，不能作为安全通过。
  - 同命令加 `--registry=https://registry.npmjs.org`：退出 1；3 个受影响包，High 1、Moderate 1、Low 1、Critical 0。
  - 同命令加 `--omit=dev`：退出 0，生产 npm 依赖 0 已知漏洞。
  - `npm --prefix apps/web ls browserslist baseline-browser-mapping esbuild --all`：确认本地版本和构建依赖路径，见发现项。
  - 对变更及未跟踪文本文件进行私钥头、AWS/GitHub/live token、带密码 PostgreSQL URL 模式匹配：0 候选；不输出秘密值。仅有限模式，不是全历史/熵扫描。
  - 本轮 Bandit 扫描上述八个 Python 文件：28,365 行，High 0、Medium 59、Low 6；所有 Medium 为低置信 B608。工具结果未直接当作已证实漏洞。
- 测试与验收材料：本会话此前门店/财务 104 passed、后续锁补丁定向 30 passed/2 skipped、固定版本锁 2 passed，仅为先前树的局部参考；本轮安全扫描未重跑，不能算最终树或新 CI 证据。
- 部署信息：Web 多阶段构建，最终 nginx 静态制品；构建阶段执行 npm ci/build。API 镜像从带版本下界的 requirements 安装依赖。CI 基础权限 contents:read；所读部署 job 限 main 且非 PR。compose HTTP 默认 loopback，Secure cookie 默认 true；腾讯部署脚本拒绝渲染配置中的 CHANGE_ME 占位符。
- 证据缺口：最终提交 SHA/镜像 digest/SBOM、Python 生产镜像精确包清单及本轮审计、OS 镜像扫描、真实生产 test-mode/secret/cookie/CORS 设置、最终 CI 和 PG 并发结果均未取得。检测到本机 pip-audit 可用，但本轮未安装/解析无锁 requirements，不能拿本机环境代替最终镜像依赖。既有安全报告及旧 CI 不计为本次通过。
- 后续补证（主控提供的只读生产核验，不是本代理执行）：实际 API 容器 `DY_API_TEST_MODE=false`、`DY_TEST_MODE=false`、`agent_environment=production`、`secure_cookie=true`、`session_secret_configured=true`。仅布尔/模式值，无秘密内容；不据此推断密钥强度或最终待构建镜像设置。上述对应环境证据缺口已部分补齐，CORS及最终制品仍待核验。
- 后续独立复核：重跑 `npm --prefix apps/web audit --package-lock-only --ignore-scripts --registry=https://registry.npmjs.org --json`，High 0、Moderate 0、Low 1（esbuild）。主控正在 npm ci，build 待复测；不将锁文件审计当作安装/build通过。最终镜像依赖审计必须针对本次构建制品，不得用当前运行镜像代替。
- 最终补证（主控新提供，非本代理重新执行）：六模块 **295 passed、2 skipped，199.72 秒**，包含 retained-originals guard、合法 anchor、生成 pending 后 coordinator blocked 整事务回滚；治理 **122 passed**；锁文件更新后 Web build passed。两项 skipped 不计通过，最终 CI/PG 仍另行承接。
- Python 新证据（主控提供）：`pip_audit -r requirements.txt --progress-spinner off --format json` 退出 0，**63 依赖、0 已知漏洞**。这是 Windows 解析环境，不是最终 Linux image；不能覆盖平台条件依赖及实际镜像版本。此证据补齐补丁依赖扫描范围，最终 candidate image 精确依赖审计仍是发布硬门禁，不以当前运行容器替代。
- 本代理最终静态复审：共同核销日/月份/实收、旧账期保护、无反向 statement 锁、跨整批 retained_originals 与 blocked 原子回滚路径均已核对；规格先行、质量随后，均未发现新的可证实 P1/P2。此结论不宣称最终 CI 成功。

## 3. 发现项

### SEC-01：构建依赖 Browserslist 已知 High

- 影响面：`@vitejs/plugin-react → @babel/core → @babel/helper-compilation-targets → browserslist@4.28.2`，开发/构建链；未证明公开业务 API 可触达。
- 证据：本轮官方 npm audit 命中版本范围 `<=4.28.6`，报告存在修复版本。
- 公告：[无界查询缓存导致 OOM](https://github.com/advisories/GHSA-c83g-rgw3-j3cx)、[不可信 stats 导致崩溃/原型写入](https://github.com/advisories/GHSA-73wf-gq98-2v4g)。一个包、两个公告，不重复计包数。
- 最终 Web 镜像不复制 node_modules，可降低运行时暴露面，但构建阶段仍使用该依赖；没有书面 waiver，按技能 High 默认阻断。

### SEC-02：其他构建依赖公告

- Medium：`baseline-browser-mapping@2.10.35`，无效输入导致进程终止，受影响范围 `>=2.0.0 <2.11.0`。[公告](https://github.com/advisories/GHSA-w5vr-8v7q-w6rv)。修复责任建议主控/依赖维护者，期限不晚于 2026-09-16；若随 SEC-01 升级，发布前一并复测。
- Low：`esbuild@0.27.7`，Windows 开发服务器任意文件读取条件，受影响范围 `>=0.27.3 <0.28.1`。[公告](https://github.com/advisories/GHSA-g7r4-m6w7-qqqr)。本次生产不是 Windows 开发服务器，记录为开发环境风险，不单独阻断。

### SEC-03：代码、输入与权限检查结果及边界

- 新增 API 锁和幂等校验保留 get_current_user、门店 scope 与管理员/页面权限检查；未见新增匿名财务写入口。幂等结果绑定账单/异议目标，异议等待锁后版本变化失败关闭。
- 输入保留整数分并拒绝 bool、正版本校验、发票号码/税率/完整账期校验；财务导入限制扩展名、分块字节累计和 5,000 行，导出限制 100,000 行。未对全历史文件解析器进行模糊测试。
- 新增 SQL 使用 ORM/绑定条件；本次累计查询范围取授权门店，未见将新用户输入作为 SQL 结构执行。Bandit 的 59 个 B608 位于完整 `_data.py` 的历史/现有动态查询，未全部逐项清除或证实；不得宣称 59 个 SQL 注入或零历史风险。
- Bandit B105 为测试模式条件下的 PII 测试常量；其余 5 个 B101 为 worker assert 告警。未发现新增生产秘密；仍需生产确认 test mode 关闭，不把静态条件当作环境证据。
- capture 私有表承载来源明细，JobEvent 仅包含摘要指纹/计数；generator 无自动确认、无自动开票、无独立 commit。前端 pendingRequestKey 仅组件内存保留，不写持久存储。
- 生产配置风险边界：auth 接受非空 session secret；compose 有 CHANGE_ME 默认值，但腾讯部署脚本拒绝占位符。未检查实际渲染配置，不能确认其他部署路径和生产 secret 已安全设置，亦未将占位符误判为真实凭据泄露。

### SEC-04：由发布阶段承接的证据边界

- Windows 解析的 Python 审计已补齐，最终 Linux candidate image 精确依赖审计仍未取得；requirements 使用版本下界，不能从旧构建推断新制品版本。责任人：主控；截止：生产发布前；失败必须阻断发布。
- 前轮跨月保护/并发问题经补丁及本代理最终静态复审，未留存可证实 P1/P2；主控新交 guard/anchor/原子回滚回归证据。最终 CI/PG 不是本报告已通过项。
- 全 OS/云安全扫描不属于本次补丁审查范围，不额外扩张为该 partial 检查的通过条件；也不宣称已扫描这些域。

## 4. 风险分级

当前分级以最终补证为准：

- Critical：本次范围未发现；不代表未覆盖域不存在。
- High：0，SEC-01 已修复并独立复查。
- Medium：0 个当前已证实项，SEC-02 baseline-browser-mapping 已消除；Bandit B608 属待人工分类历史告警，不累加为已确认漏洞。
- Low：SEC-02 esbuild 条件性开发风险；SEC-03 测试常量/assert 工具告警按上下文记录。
- 证据缺口：SEC-04 及生产鉴权环境/最终制品验证不赋予虚构 CVSS，但影响放行判断。

## 5. 阻断项

- 阻断编号：本次补丁安全范围无剩余阻断项；SEC-01 已解除，无需 waiver。
- 阻断原因：不适用。最终 candidate image 审计与 CI/PG 属明确保留的发布硬门禁，不因本报告 PASS 被免除。
- 尚未满足的生产放行条件：主控锁定最终提交/镜像 digest，完成 candidate image 依赖审计、最终 CI/PG 与部署验证；本报告不批准跳过这些步骤。

## 6. 放行结论

- 最终结论：`PASS`（仅第 1 节定义的补丁安全范围）。
- 结论理由：High/Medium 依赖项已消除，Windows 解析的 Python 依赖扫描与当前补丁回归、静态复审证据已补齐；本范围未发现剩余阻断项，Low 按风险规则不单独阻断。最终 Linux 制品审计作为后续发布硬门禁保留，不能解释为已完成或被豁免。用户授权已确认，不重复请求。

## 7. 整改建议

- 立即整改：本补丁无剩余安全立即整改项；SEC-01、SEC-02 Medium 已消除，主控报告安装后 build 通过。
- 生产发布前补齐：主控记录最终提交/镜像 digest 与包清单，执行 candidate image 精确依赖审计及最终 CI/PG、部署核验；任一失败阻断生产发布。
- 完工后跟踪：维护者跟踪 esbuild Low、历史 B608 告警与依赖可复现性，不将本报告扩大为历史安全清零承诺。

## 8. Waiver 记录（如有）

- 风险项：无已批准 waiver。
- 豁免理由：不适用。
- 责任人：未指定批准者。
- 失效日期：不适用。
- 临时缓解措施：不适用，无需豁免。Web 多阶段镜像不携带构建 node_modules 为暴露面事实；最终制品审计门禁未被豁免。
