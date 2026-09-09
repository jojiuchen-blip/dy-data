# DYDATA-87 发布安全扫描报告

> 2026-09-09 候选镜像补证结论：`BLOCK`（partial Python 依赖门禁）。候选 `35eba477acf36ea3bc4e45d187e88f62900b0ff1` 的 CI 全绿由主控报告，但 browser 存在 3 个包、12 项未修 High，不能发布。先前补丁范围 PASS 仅保留为历史轨迹，不覆盖此镜像结论。无已批准 waiver；不以 pip-audit 非零退出自动判阻断。

## 1. 扫描范围

- 扫描模式：partial，2026-09-09 发布候选增量及其直接安全边界；不是全系统渗透测试。
- 覆盖域：code、secrets、dependencies、API input validation；按用户要求额外检查生产授权、门店/管理员权限及发布配置。
- 范围：API dashboard/_data/models、0051、worker settlement/capture/coordinator/generator、前端本次变更及依赖锁文件、相关 Dockerfile/compose/CI。包括未跟踪新增文件。
- 未覆盖域：生产写操作、互联网攻击测试、云账号策略、完整 Git 历史秘密扫描、最终镜像 OS/SBOM 漏洞扫描、全量历史 SQL 告警逐项验证。
- 使用 security-scan 技能及 gate-contract、scan-scope、risk-rating-policy、report-template 四份必需参考。未安装工具、修改依赖或运行 audit fix；仅公开 npm 包名/版本元数据发送到审计服务，源码与秘密不外传。
- 本次追加范围仅为候选 Python 依赖：全部 pip 命中、Debian 回移修订、两个 PyPI 无法识别项、实际导入路径、Brotli 条件，以及 Pillow 命中所关联的 libwebp 动态链接。不扩展全 OS；未做业务可达性/利用测试。

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

### SEC-05：精确候选 Python 依赖门禁（当前结论）

候选 tag 后缀为 `dydata87-35eba477acf36ea3bc4e45d187e88f62900b0ff1`。镜像 ID 已逐个核对；提取直接使用 digest，而非可变 tag：

| 镜像 | sha256 | Python 审计 |
|---|---|---|
| api | `1f5660bd2ec02e4553f70fc858929acf9a0e7d352ce517411bd4ae7fb1df9627` | 64 包，0 已知漏洞，退出 0 |
| worker | `9376fa2ca4f5690b06b87abe914dc14115e648f5060707920455ed333574ad0f` | 64 包，0 已知漏洞，退出 0 |
| ops-agent | `8f0195448c7422d4f753ab08c1b807fe53eb177356e3f7f467185047e5c290c0` | 64 包，仅 pip 命中；见 SEC-06 |
| browser | `20462457ff70b57589204d283ad4ea9c5972b898aa89090624a6a57e20329987` | 98 包，以下完整分类 |
| web | `f929cd4650ff1b0786674cc00fca57cd3bd2f10662d35b15ba0df7c63bc3adfa` | Python N/A：命令查找 python/python3/pip/pip3 及 /usr、/opt 路径搜索无匹配 |

生产 SSH 仅运行无挂载、`--network none --read-only --cap-drop ALL --security-opt no-new-privileges` 一次性容器，覆盖 entrypoint；Python 使用 `-B`。本机对完整 pins 使用 `pip-audit --no-deps --disable-pip`，不在 Windows 重新解析平台依赖。证据临时文件为 `logs/dydata87-image-audit-*-pins.txt`、`*-result.json` 及 `*-debian-verification.md`（运行日志非长期权威）。未安装生产包、改服务、触发结算或开票。

以下八个模块均已实际 import，路径为 `/usr/lib/python3/dist-packages/` 下的相应模块（zipp 为 `zipp.py`，Pillow 为 `PIL/`）；不是仅检查发行包元数据。requests 则从 `/usr/local/lib/python3.11/dist-packages/requests/` 导入。

| 包 | dpkg 完整版本 | 全部命中分类及依据 |
|---|---|---|
| urllib3 | `1.26.12-1+deb12u4` | **High CVE-2025-66471 未修**；2023-43804、2023-45803、2024-37891、2025-50181、2025-66418、2026-21441、2026-44431 在当前 Debian 修订已解决。[Debian](https://security-tracker.debian.org/tracker/source-package/python-urllib3) |
| msgpack | `1.0.3-2+b1`，source `1.0.3-2` | **High CVE-2026-57585 未修**：错误后重复使用 Unpacker 的越界读/崩溃。[Debian](https://security-tracker.debian.org/tracker/CVE-2026-57585)、[上游 High/修复 1.2.1](https://github.com/msgpack/msgpack-python/security/advisories/GHSA-6v7p-g79w-8964) |
| Pillow | `9.4.0-1.1+deb12u1` | **10 High 未修**，见下表；另 3 Medium：2026-42308、2026-42310、2026-59198。2023-50447（原 Critical）、2024-28219、2023-44271 已回移修复；2026-55798 仅 Windows，不适用于本 Linux 镜像。[Debian](https://security-tracker.debian.org/tracker/source-package/pillow) |
| idna | `3.3-1+deb12u1` | 2024-3651 已修；2026-45409 **Medium 未修**，超长特殊输入可绕过旧修复产生计算型 DoS。[Debian](https://security-tracker.debian.org/tracker/CVE-2026-45409)、[上游](https://github.com/kjd/idna/security/advisories/GHSA-65pc-fj4g-8rjx) |
| setuptools | `66.1.1-1+deb12u2` | 2024-6345、2025-47273 两项 High 已回移修复；2026-59890 为 macOS APFS/HFS+ 特定问题，本 Linux 不受影响，不能说此项由版本升级修复。[Debian](https://security-tracker.debian.org/tracker/source-package/setuptools) |
| zipp | `1.0.0-6+deb12u1` | 2024-5569 已修。[Debian](https://security-tracker.debian.org/tracker/source-package/python-zipp) |
| jwcrypto | `1.1.0-1+deb12u1` | PyPI 元数据 `1.1` 无法识别，改以 Debian source 及实际 import 核验；2023-6681、2026-39373 **均 Medium 未修**，分别为 PBES2 迭代次数与 JWE ZIP 解压 DoS；2024-28102 已回移修复。[Debian](https://security-tracker.debian.org/tracker/source-package/python-jwcrypto)、[PBES2 公告](https://github.com/advisories/GHSA-cw2r-4p82-qv79)、[ZIP 公告](https://github.com/latchset/jwcrypto/security/advisories/GHSA-fjrm-76x2-c4q4) |
| python-novnc | `1:1.3.0-1` | PyPI 元数据 `1.0.0` 不等于 Debian source 版本；source novnc 已核对，无当前 open issue，历史 2017-18635、2013-7436 不命中该版本。[Debian](https://security-tracker.debian.org/tracker/source-package/novnc) |

Pillow 未修 High 清单（Debian 将本 bookworm 修订列 vulnerable/no-DSA/postponed；不等同项目 waiver）。严重性取上游 GitHub 公告；均已查询公告元数据，不以 pip-audit 输出推断严重性：

| CVE | 条件性影响 | 上游公告 |
|---|---|---|
| 2026-55379 | BDF 字体加载绕过解压炸弹检查 | [GHSA-45hq-cxwh-f6vc](https://github.com/advisories/GHSA-45hq-cxwh-f6vc) |
| 2026-54060 | FontFile.compile 分配绕过尺寸检查 | [GHSA-5x94-69rx-g8h2](https://github.com/advisories/GHSA-5x94-69rx-g8h2) |
| 2026-54058 | McIdas mmap 行跨度导致越界读 | [GHSA-62p4-gmf7-7g93](https://github.com/advisories/GHSA-62p4-gmf7-7g93) |
| 2026-59199 | paste/crop 坐标溢出导致堆越界写 | [GHSA-6r8x-57c9-28j4](https://github.com/advisories/GHSA-6r8x-57c9-28j4) |
| 2026-54059 | PCF 字体位图加载绕过炸弹检查 | [GHSA-8v84-f9pq-wr9x](https://github.com/advisories/GHSA-8v84-f9pq-wr9x) |
| 2026-59205 | ImageCms 输出模式不匹配导致堆越界写 | [GHSA-9hw9-ch79-4vh6](https://github.com/advisories/GHSA-9hw9-ch79-4vh6) |
| 2026-59200 | PDF stream 解压资源耗尽 | [GHSA-jjj6-mw9f-p565](https://github.com/advisories/GHSA-jjj6-mw9f-p565) |
| 2026-55380 | GD 图像尺寸绕过炸弹检查 | [GHSA-phj9-mv4w-65pm](https://github.com/advisories/GHSA-phj9-mv4w-65pm) |
| 2026-59204 | JPEG2000 tiled decode 缓冲增长 DoS | [GHSA-vjc4-5qp5-m44j](https://github.com/advisories/GHSA-vjc4-5qp5-m44j) |
| 2026-59197 | RankFilter/ImagingExpand 溢出导致堆越界写 | [GHSA-xj96-63gp-2gmr](https://github.com/advisories/GHSA-xj96-63gp-2gmr) |

关联包与误报消歧：

- `PYSEC-2023-175` 无 aliases，但上游 YAML 的 related 明确指向 CVE-2023-4863/5129（wheel 内置 libwebp），与另一 Pillow 命中属于同一来源风险。实际 `PIL/_webp.cpython-311-x86_64-linux-gnu.so` 的 ldd 链接系统 `libwebp.so.7`，dpkg 为 `libwebp7 1.2.4-0.2+deb12u1`，Debian 明确 fixed；不能把上游 wheel 的旧版本号误报为本候选 Critical。[PYSEC 原记录](https://github.com/pypa/advisory-database/blob/main/vulns/pillow/PYSEC-2023-175.yaml)、[Debian 修复](https://security-tracker.debian.org/tracker/CVE-2023-4863)。本镜像 changelog 文件已裁剪，读取失败；用 dpkg/动态链接/供应商公告替代，不声称读到了镜像内补丁日志。
- `brotli`、`brotlicffi`、`_brotli`、`_brotlicffi` 的 find_spec 均为 null；`urllib3.response.brotli` 为 None；`python3-brotli` dpkg 状态 not-installed。只有原生 `libbrotli1 1.0.9-2+b6` installed，不等同 Python Brotli 被启用，不因此扩展 OS 扫描。后续候选若引入 Python Brotli，需验证 Brotli >=1.2.0 或 brotlicffi >=1.2.0.0；当前不存在这项 Python 修复依赖。[urllib3 公告](https://github.com/urllib3/urllib3/security/advisories/GHSA-2xpw-w6gg-jr37)。
- 所有原始重复 PYSEC/alias 按 CVE 去重；两项 PyPI skip 已有供应商证据，未跳过不报。

### SEC-06：ops-agent pip 非阻断残余

pip `25.0.1` 原始 7 条记录去重为 6 项：Moderate 2025-8869（缺 PEP706 的 Python fallback tar 解包才涉及该回退路径）、2026-8643（脚本入口路径处理）、2026-3219（tar/ZIP 混合归档解释）、2026-6357（安装后自更新检查导入新安装模块）、2026-13346（恶意包索引双编码 URL）；Low 2026-1703（恶意 wheel 的受限路径穿越）。不把完整命中列表等同业务远程可利用，不表述零风险；未发现需要将这些项升级为 High 的新证据。

责任：DYDATA-87 发布维护者／当前主控；整改截止：2026-09-16；后续维护升级 pip 26.2.1，主控已明确登记。Medium 默认不单独阻断，并非 waiver。公告分别为 [8869](https://github.com/advisories/GHSA-4xh5-x5gv-qwph)、[8643](https://github.com/advisories/GHSA-wf93-45jw-7689)、[3219](https://github.com/advisories/GHSA-58qw-9mgm-455v)、[6357](https://github.com/advisories/GHSA-jp4c-xjxw-mgf9)、[13346](https://github.com/advisories/GHSA-qwm4-qh6w-59xr)、[1703](https://github.com/advisories/GHSA-6vgw-5pg2-w6jp)。

以下 SEC-01～04 保留初次补丁审查轨迹；与候选相关的当前判定以 SEC-05/06 及第 4～8 节为准。

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
- High：SEC-05 browser 的 urllib3 1、msgpack 1、Pillow 10，共 12 项／3 包；SEC-01 已修复，不重复计入。
- Medium：browser 6 项（idna 1、Pillow 3、jwcrypto 2）；ops-agent pip 5 项。browser 残余需主控明确责任与期限，建议与本次镜像修复一并升级；不得假定 ops 的期限已自动覆盖 browser。Bandit B608 属待人工分类历史告警，不累加为已确认漏洞。
- Low：SEC-02 esbuild 条件性开发风险；SEC-03 测试常量/assert 工具告警按上下文记录。
- 证据缺口：SEC-04 及生产鉴权环境/最终制品验证不赋予虚构 CVSS，但影响放行判断。

## 5. 阻断项

- 阻断编号：SEC-05。
- 阻断原因：精确 browser 候选存在 12 项未修 High；没有书面 waiver。不是因为 pip-audit 退出 1。
- 尚未满足的生产放行条件：修复上述三个包并构建新候选，按新 digest 复核导入路径及漏洞；browser Medium 残余若保留，应登记责任、期限和影响。主控报告旧 SHA 35eba CI 全绿，但不得用于新修复候选，更不能覆盖安全 BLOCK。

## 6. 放行结论

- 最终结论：`BLOCK`（当前精确候选 partial Python 依赖门禁）。
- 结论理由：已实际取得候选包、dpkg 与导入证据，并核对全部命中及两项 skip，存在 SEC-05 明确 High。此前代码补丁 PASS、Windows 审计、旧候选 CI 成功均不能豁免。未做业务漏洞利用/可达性测试、未审全 OS，不声称整个系统风险清零。

## 7. 整改建议

- 立即整改：browser 在构建期一次性处理 urllib3、msgpack、Pillow 的 High。上游命中修复版本集合对应 urllib3 2.7.0、msgpack 1.2.1、Pillow 12.3.0；候选构建兼容性与实际导入必须测试，不能在生产 pip install。仅修 urllib3 不足以解除 BLOCK。
- 生产发布前补齐：主控记录新提交/镜像 digest 与完整包清单，复审候选和 CI/PG；采用 local 覆盖保留 apt 时，应验证默认 Python、服务解释器及相关扩展都导入修复版本，不以安装日志代替导入证据。未有新 digest，尚不能断言 Cicero 的修复已在镜像生效。
- Medium 跟踪：ops 按 SEC-06 的已指定责任/2026-09-16 期限执行；browser 6 项建议同时升级 idna 及 jwcrypto（上游已知修复 idna >=3.15、jwcrypto >=1.5.7），Pillow 12.3.0 可覆盖此轮其相关命中；如保留残余须单独登记而非强制 audit 全零。
- 完工后跟踪：维护者跟踪 esbuild Low、历史 B608 告警与依赖可复现性，不将本报告扩大为历史安全清零承诺。

## 8. Waiver 记录（如有）

- 风险项：无已批准 waiver。
- 豁免理由：不适用。
- 责任人：未指定批准者。
- 失效日期：不适用。
- 临时缓解措施：无可用于解除 SEC-05 的已批准措施。Debian no-DSA/ignored/postponed 不构成项目 waiver；CI 全绿不构成 waiver。
