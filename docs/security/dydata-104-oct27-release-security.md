# DYDATA-104 2026-10-27 发布前安全扫描

## 1. 扫描范围

- 扫描模式：`partial`，生产代码基线`9b1feb8`至发布集成`315bab141f5cfb6343f5cd7b6314e0f47491f30e`的增量审查，追加精确Web依赖修复`0096378d9e9d062903f9aa0193674f0caf468eb5`（主线程集成为`ff1b773`）的独立审计；四个默认域均实际执行：code、secrets、dependencies、api-input-validation。不是全仓历史安全认证或渗透测试。
- 稳定范围：财务四类导入/冻结预览及导出、月末资格/正式后台文件来源、历史更正及生命周期、受保护账单authority/只发布coordinator、SKU完整同步，以及同基线包含的商品类型/线索查询改动。相对基线共162个变更文件；Bandit扫描其中33个Python业务/脚本/迁移文件的当前完整内容，44519行。
- 本版追加集成基线 `19f65292d8026fd036d0ca7c2c91e2d37e30f030` 中的自动月结/bootstrap `4369a41780c960e2ac9ff9aae4b60f036a99ecf7` 窄增量安全复核；`342d4f8`仅接线既有CI证据门禁；追加 `81df66d914ac07eaa0b9dae234eb8c67b789439b` 重核销lineage守卫的精确Git对象复核。追加精确 `ba74d38275e74791752d28c5ee513134f8716ea9` missing-fee repair 与 `a97b19b8fa70cf9ed3c66df185049187f48376aa` browser双pin补丁；`031dde616b118b32fb028c8839a1289242ed7505`追加CLI提交/报告结果分类，不改财务service。browser文档补充 `e0e0727` / `98e5358` 不改运行代码。稳定44519行扫描不重复执行。
- 未覆盖：生产/API请求、生产写入/部署、云/网络/完整多用户授权审计、完整Git历史及熵秘密扫描、最终集成制品及完整OS漏洞/SBOM、运行时利用测试。不以本地Windows解析环境代替容器。
- 使用仓库`security-scan`及gate-contract、scan-scope、risk-rating-policy、report-template四份必需参考，另读standards-map。只写本报告及忽略目录证据，不修改业务、依赖、计划或共享索引。

## 2. 输入证据

- 本次PASS的精确集成代码快照：主线程 `8f6304b`，已包含CLI修复 `031dde6` 的cherry-pick。10个变更生产/依赖文件与对应已审查Git对象逐字节一致，收据 `.tmp/security-final/integrated-source-comparison.json`；此前62c427c加CLI的候选集合收据保留作过程轨迹，不再作为未集成状态。后续仅CI/test/doc变更若未改变这10个生产/依赖blob不扩大本安全快照，不代替最终RELEASE验证。
- 计划及完成标准：[当前T3.1](../plans/delivery-plans/sub-delivery-plan-dydata-104-followthrough-T3.1-release-acceptance.md)、[总验证台账](../verification/dydata-104-oct27-delivery.md)。功能测试通过不等于安全域全部通过。
- 最终追加秘密扫描覆盖23份精确Git文本快照、7类位置规则，0候选；只保存路径/行号/类别，不打印匹配值。不是历史/熵全扫描。
- 稳定基线证据复核：按原 `evidence-manifest.json` 重算全部78个证据文件SHA，0不一致；收据 `.tmp/security-final/baseline-integrity.json`。原始扫描结果为此前执行，本轮只独立核实其完整性。
- 输入代码及逐文件SHA：`.tmp/security-oct27/changed-files.json`；工具版本、原始审计/静态结果SHA：同目录`evidence-manifest.json`。比较使用`git diff 9b1feb8 HEAD`，不是与错误的旧开发基线比较。
- 依赖归因：原稳定扫描315bab1的`requirements.txt`、Web package/lock及`deploy/browser/Dockerfile`相对生产基线无修改，风险为基线原有；本版已追加精确Web/browser修复审计，不再把旧版本视为修复候选仍携带。
- 实际命令及收据如下。`python`为已安装Bandit/pip-audit的工具解释器；测试使用隔离的项目测试解释器。没有安装/升级共享环境包、运行audit fix、外传源码或输出凭据；依赖审计仅提交公开包名/版本及需求元数据。
- 工具版本：Python 3.12.10、Bandit 1.9.4、pip-audit 2.10.1、npm 11.6.2。追加窄扫描与定向独立检查使用现有工具Python解释器，没有安装或升级共享项目环境。

| 检查 / 可复现命令 | 结果 / 证据 |
|---|---|
| `python .tmp/security-oct27/run_static_scans.py` | wrapper exit0；内部`python -m bandit -f json -o <ignored-output> <33个文件>` exit1，0 High / 82 Medium / 26 Low，0解析错误；秘密位置分类扫描0候选。输入文件列表及SHA可复算 |
| `npm --prefix apps/web audit --package-lock-only --ignore-scripts --registry=https://registry.npmjs.org --json` | exit1；High2包、Low1包、Critical0；`npm-all.json` |
| 上述npm命令追加`--omit=dev` | exit0；生产npm依赖0已知漏洞；`npm-prod.json`。不覆盖开发/构建链 |
| `python .tmp/security-oct27/review_web_fix.py` | 从`0096378`精确Git对象读取package/lock至ignored目录，分别执行全锁及omit=dev审计；两次exit0、全部级别0，未修改业务树；`web-fixed-0096378/review-results.json` |
| `python -m pip_audit -r requirements.txt --progress-spinner off --format json` | exit0；当前Windows解析64依赖，0已知漏洞；`pip-requirements.json`。不覆盖Docker显式固定包或最终Linux实际安装清单 |
| `python -m pip_audit --no-deps --disable-pip -r .tmp/security-oct27/browser-fixed-pins.txt --format json --progress-spinner off` | exit1；Dockerfile5个精确pins，urllib3命中3公告、Pillow命中37公告；另3包无命中；`browser-fixed-pins-audit.json`。不是已构建镜像盘点 |
| `python .tmp/security-oct27/read_public_advisory_metadata.py` | 公开GitHub公告逐项回收severity/版本范围/修复版本及URL，保留每条JSON及汇总；不从pip-audit退出码推定严重性 |
| 项目测试解释器`-m pytest tests/test_dydata104_finance_state_matrix.py tests/test_historical_fee_correction.py tests/test_backend_aweme_proof.py -q --tb=short -k 'frozen_row_preview_uses_only_whitelisted_fields or invalid_management_scope_month_and_amount or direct_management_correction_rejects_unicode_digits or commit_rechecks_permission_after_preview or import_storage_limits or invalid_evidence_or_state_rejects_whole_batch or invalid_completed_task_metadata' --junitxml=.tmp/security-oct27/input-validation.xml` | exit0，42 passed / 95 deselected / 45 warnings，19.60秒；定界输入/状态验证，不是完整功能或安全测试 |
| 项目测试解释器执行`.tmp/security-oct27/probe_input_boundaries.py` | 本地纯helper、合成无害算式文本；CSV公式文本原样保留，未启动表格或访问数据库；`input-probe-results.json`、`csv-baseline-comparison.json` |

- 追加窄增量输入与收据均在 `.tmp/security-final/`：`review_commit_delta.py --commit 4369a41` 从精确Git对象提取7文件、逐文件SHA，3个业务Python完整内容运行Bandit：exit0，0 High / Medium / Low，0解析错误；5类秘密位置规则0候选。`bootstrap-manual-review.json`保留具体手工控制观察，不将0告警当作全部安全认证。
- `81df66d` 精确delta为3文件、1个业务Python，Bandit exit0/全部级别0/解析错误0，秘密模式候选0，收据 `.tmp/security-final/delta-81df66d914ac/`。只独立复核代码及静态证据；协作者266项回归/11项PG不冒充本单元重跑。
- 本执行单元独立运行 `python -m pytest tests/test_month_close_auto_bootstrap.py -q --tb=short --junitxml=.tmp/security-final/bootstrap-input.xml`：exit0，19 passed / 66.02秒；`tests/test_dydata104_ci_coverage.py`：exit0，56 passed / 3.41秒。前者覆盖摘要对相关来源变化敏感、忽略输出与无关月份、旧current退役不重置预算、排队后漂移拒绝、资格未pin回滚和末次持锁捕获阻断；后者只证明CI静态及收据守卫合同，没有远端执行收据。本安全单元没有独立重跑PG并发。

- 部署边界：本次未访问生产；当前生产版本及`0065`、目标`0066`未部署等事实由总验证台账承接。Web镜像只复制静态dist，开发依赖不随node_modules进入nginx；原High仍覆盖构建/Windows工具链，已由精确修复关闭，不以静态部署作口头豁免。
- 证据缺口：已回收最终业务delta及browser依赖兼容候选的Linux安装清单/导入路径/镜像身份。该候选上下文为315bab1加双pin，不能冒称最终集成HEAD；最终集成镜像/远端CI、SBOM/OS审计及生产验收仍由主线程独立回收，后两者未纳入本次默认四域认证。
- 文档门禁：suite2.0.1锁有效，global为0错误/0警告，S4可进入；治理9 passed / 7.80秒，exit0。链接诊断为validate-only、exit0、37条既有问题，本报告关联问题0；没有重写共享索引。固定8章节、相对本地链接、敏感路径/值模式及`git diff --check`通过。它们不代表安全阻断解除。

## 3. 发现项

### SEC-104-01：Web原High已独立复审消除，保留发现轨迹

`vite@7.3.5`、`source-map-js@1.2.1`、`esbuild@0.27.7`均与生产基线相同。官方npm审计为2个High包及1个Low包；一个包可对应多个公告，不把公告数当包数。

- `source-map-js`的indexed source-map offset可导致同步事件循环耗尽；受影响`>=1.0.0 <1.2.2`，修复1.2.2。依赖链为Vite→PostCSS→source-map-js。[公告](https://github.com/advisories/GHSA-68fv-2mgg-jv7q)
- Vite命中launch-editor系列公告，最高High；Windows文件路径检查绕过可结合命令参数问题形成注入。官方对Vite 7列修复7.3.7，不能只以Linux静态部署否定Windows开发/测试工具链风险；没有执行利用。[维护者公告](https://github.com/vitejs/launch-editor/security/advisories/GHSA-587h-7wmj-h5pm)
- esbuild是Windows开发服务器路径穿越Low，修复0.28.1。其条件与Vite构建风险分开记录；不将Low单独当阻断。[维护者公告](https://github.com/evanw/esbuild/security/advisories/GHSA-g7r4-m6w7-qqqr)

独立修复`0096378`已将精确版本升级为Vite7.3.7、source-map-js1.2.2、esbuild0.28.2；本执行单元从该commit取Git对象快照重新执行官方全锁及omit=dev审计，均exit0、0漏洞。主线程报告修复后5项真实API浏览器通过；本报告没有自行重跑这5项，也不将精确锁文件审计当npm ci/build或最终镜像已通过。此发现的依赖版本风险已在修复快照关闭，最终集成/制品验证仍独立承接。

### SEC-104-02：browser原Critical/High固定包已修复，保留原始发现与Linux供应商复核

原 `deploy/browser/Dockerfile` 额外强制安装`urllib3==2.7.0`、`Pillow==12.3.0`等5包，随后断言版本和`/usr/local/lib`实际导入。原requirements的64包Windows解析不会覆盖这些固定版本；本版已取得精确修复及实际Linux证据，下面先保留原始发现轨迹。精确pins审计40条公告；GitHub**聚合元数据快照**分布为4 Critical、24 High、12 Medium（单项有界重试后40条均取得），这不是逐条维护者口径已统一的风险总数。下表独立读取维护者原文发现两项分级差异，**以维护者原文优先**，并保留聚合记录，不武断改写任一原始来源。

| 组件 / 典型已核实公告 | 级别与条件 | 官方修复 |
|---|---|---|
| urllib3 `GHSA-vxq7-64xx-v4gw` | High；HTTPResponse流/分块读取可无界缓存chunk-size行 | 2.8.0；[维护者公告](https://github.com/urllib3/urllib3/security/advisories/GHSA-vxq7-64xx-v4gw) |
| Pillow `GHSA-w889-685w-c8fh` | **Moderate（维护者）/Critical（聚合）**；Ghostscript参数注入，需对应解释器、EPS处理及受控路径等条件 | 13.0.0；[维护者公告](https://github.com/python-pillow/Pillow/security/advisories/GHSA-w889-685w-c8fh) |
| Pillow `GHSA-332p-7hrc-92wf` | **High（维护者）/Critical（聚合）**；保存TIFF到BytesIO的原生缓冲区溢出；维护者未声称已证明代码执行 | 13.0.0；[维护者公告](https://github.com/python-pillow/Pillow/security/advisories/GHSA-332p-7hrc-92wf) |
| Pillow `GHSA-v9pv-5gc8-w2m6` | Critical；多帧加载器模式转换后的原生存储复用 | 13.0.0；[维护者公告](https://github.com/python-pillow/Pillow/security/advisories/GHSA-v9pv-5gc8-w2m6) |
| Pillow `GHSA-5x8w-8jj5-q52h` | Critical；安装可选olefile且打开特制FPX图像时的JPEG解码堆溢出 | 13.0.0；[维护者公告](https://github.com/python-pillow/Pillow/security/advisories/GHSA-5x8w-8jj5-q52h) |

其余公告、aliases去重、受影响范围和修复版本保留于`browser-advisory-severities.json`及每条原始公告；该文件保留聚合口径，维护者差异另见`maintainer-severity-comparison.json`。原报告据上表两项Critical及urllib3/TIFF的High阻断；不需要把聚合40条统一强行定级。未声称当前业务可以触发所有图像格式、Ghostscript/olefile已安装或漏洞已被利用；也没有据“未证明可达”自行waiver。最终镜像可能同时有apt与pip包，必须按实际metadata及模块导入路径核对，避免只升级一个未被导入的副本。

修复 `a97b19b` 仅将urllib3升为2.8.0、Pillow升为13.0.0并同步既有版本/导入断言；不删除依赖检查。安全单元独立执行 `python -m pip_audit --no-deps --disable-pip -r .tmp/security-final/browser-candidate/fixed-pins-after.txt --format json --progress-spinner off -o .tmp/security-final/fixed-pins-independent-audit.json`：exit0，五包0已知公告。精确Dockerfile Git blob SHA为 `773a7cb61408896b2088fc15368e9bed9f035dbb2580f5c565e1283ace89773d`；构建上下文CRLF字节SHA为 `cfe594b72ffda6a7656070296b29553bfb6a2d24afd7c6de6e6fe878e23ebf15`，LF归一后与Git blob一致，不能把两个原始字节SHA说成相同。

浏览器责任单元提供的实际Linux候选Image ID / manifest-list digest为 `sha256:6a1c23aff303ca92901d66a0a3556ecd887b9ebd2db459a456b3312df581ee41`；本单元独立读取并核对其manifest及文件SHA，没有自行启动容器。五包选中版本正确，六个实际模块均从 `/usr/local/lib/python3.11/dist-packages` 导入；APT副本仍存在，不能称已删除。离线about:blank/CDP/PNG-JPEG-TIFF smoke、pip check及镜像内3项pytest为责任单元收据，明确区别于本单元独立命令。候选只含315bab1及精确Dockerfile补丁，通过原已有 `APT_MIRROR` 参数使用HTTP APT镜像，未改Dockerfile内容；它证明依赖兼容，不覆盖后续业务集成镜像。

实际Linux99包清单审计**原始exit1保持不变**：setuptools7记录、zipp2记录，按CVE/GHSA别名去重为5个公告；python-novnc1.0.0无PyPI条目而跳过。`pip freeze`不带Debian修订号，不能仅用66.1.1/1.0.0判断供应商补丁未修复。本单元读取实际dpkg修订及被选中源码，重算4份源码SHA全部一致，核对维护者/发行版原始资料如下：

| 唯一公告 | 当前候选复核结论 |
|---|---|
| CVE-2024-6345，High | Debian `python3-setuptools` / `python3-pkg-resources 66.1.1-1+deb12u2` 满足发行版修复u1；选中的package_index源码已改用subprocess参数数组。[Debian修复记录](https://security-tracker.debian.org/tracker/CVE-2024-6345) |
| CVE-2025-47273，维护者Moderate | 同一Debianu2满足发行版修复，选中的_download_url包含tmpdir路径保护。不能沿用聚合High覆盖维护者口径。[维护者公告](https://github.com/pypa/setuptools/security/advisories/GHSA-5rjg-fvgr-3xxf)、[Debian修复记录](https://security-tracker.debian.org/tracker/CVE-2025-47273) |
| CVE-2024-5569，Moderate | `python3-zipp 1.0.0-6+deb12u1` 满足发行版修复，选中源码包含SanitizedNames回补。[Debian修复记录](https://security-tracker.debian.org/tracker/CVE-2024-5569) |
| GHSA-h35f-9h28-mq5c，维护者Moderate | sdist的Unicode规范化/排除匹配问题，受文件系统与打包操作影响；保留供应链观察，不宣称Linux服务RCE。审计称83.0.0修复而维护者页当前写None，差异原样保留。[维护者公告](https://github.com/pypa/setuptools/security/advisories/GHSA-h35f-9h28-mq5c) |
| GHSA-xmj3-9gf7-h52w，维护者Low | 明确为Windows legacy wheel安装元数据路径条件，当前Linux候选不符合Windows条件；维护者未声称RCE。[维护者公告](https://github.com/pypa/setuptools/security/advisories/GHSA-xmj3-9gf7-h52w) |

前3项依据发行版补丁证据分类，后2项依据已知级别/条件分类，**不是waiver**；未把raw audit改为exit0或99包全clean。Linux证据、供应商源码摘录、独立five-pin审计及公告差异保存在 `.tmp/security-final/`，无新High成立。python-novnc及未评估OS包保留覆盖缺口。

### SEC-104-03：财务CSV保留电子表格公式文本（既有Medium）

本地纯helper用无害`=1+1`验证：`dashboard.py::_finance_import_error_csv`的`originalValue`和`_finance_order_detail_csv`的文本字段读回仍以`=`开头。CSV引号只维护语法，不会禁用电子表格公式；这里没有执行公式或构造外带请求。三个相关CSV helper的AST与`9b1feb8`完全相同，属于既有导出边界，本轮未引入。

错误值来自上传文件；其他文本来自业务来源，下载者用支持公式的表格软件打开才进入风险路径。当前未提供“安全表格模式”与“原始证据值”的独立合同，不建议为消除扫描告警直接覆盖审计原值或打乱长ID/负金额。按Medium记录，主线程已将后续处理登记为 [DYDATA-107](https://linear.app/keith-lim/issue/DYDATA-107)；主线程指定跟进人为DYDATA-104 Codex集成人，目标2026-11-03前完成安全CSV/证据保真合同复核并提出交接。此为跟进安排，本执行单元未独立读取Linear字段，不声称用户已批准该票开发或业务方已接受；本轮不新增开发、不批准豁免。

### SEC-104-04：静态告警复核与输入控制

- Bandit的82个Medium中80为低置信B608；另两个是既有CDP环境配置URL读取及目标发布脚本临时备份路径。全文件扫描包含旧代码，未逐项认证旧模块安全。按新增行相交得到20条候选：13条B608及7条固定参数subprocess类Low；未发现新增High。
- 13条新增SQL候选来自0066固定表/操作枚举、固定商品类型SQL表达式及参数化查询的组合。表/列/语法不来自HTTP值，订单ID、类型、门店集合由`:name`绑定/生成占位符传入；未发现将新增用户值插为SQL结构的路径。转换CLI使用参数数组调用git、不使用shell。静态结果不是SQL注入的直接证明。
- 新冻结rows API在管理员、类型页权及整批门店scope校验后返回；page≥1、pageSize≤50，preview仅模板字段及相关状态，不返回完整raw或文件URL。React新预览用文本节点，不使用新innerHTML/eval。42项合成测试覆盖白名单、不漂移、权限重验、金额/月/scope、ASCII票号、存储边界、manifest/任务来源拒绝。
- 财务上传限制10MiB压缩/原始文件、5000行及CSV/XLSX类型；只读data_only解析不执行表格公式，文件名未作为服务器保存路径。此大小限制不等于已验证所有XLSX展开/解析资源上界；未进行解压炸弹/负载测试。后台任务文件以basename落私有临时目录，签名URL仅在内存，不进入永久proof；来源主机/运行权限完整加固不在本次默认四域的全面认证内。
- 新历史更正manifest严格字段集、16方向、分金额真整数（拒绝bool）、原费/来源SHA及月份/版本；默认只读preview，apply必须明确参数及匹配预演hash，来源/保护/事务失败关闭。审批字段由受控运维manifest承载，不声称它们是独立密码学审批系统。
- 秘密扫描仅保存路径/行号/分类，0候选；覆盖变更文件当前内容的私钥头、AWS/GitHub/service token、凭据URL、JWT及长秘密字面量规则。不是完整历史、熵、外部配置或运行日志安全认证。

### SEC-104-05：自动月结与重核销authority窄增量已复核

`4369a41`新增摘要查询只用固定model/列/JSON路径及ORM结构，月份、来源ID等值保留参数绑定；无新SQL文本拼接或shell执行。SHA绑定协议、完整日修订、冻结版本/内容及相关原始来源，metadata保存完整64 hex，既有短job key冲突时复核全值。不可变历史fee仅提供来源地址，避免current退役后摘要自变和重置重试预算。

month runner在费用重算前和提交前复核来源摘要；未pin/错误pin的任一current fee会阻断资格校验。full runner涉及10月经济输出时同样检查；refresh和publication-only在两轮持锁捕获前后检查实际月份闭包，保留job claim、active pointer和slot fence。19项独立合成回归支持这些边界；没有据此证明生产月底采集事实、实际大规模成本或全部并发来源路径。此delta未发现新阻断级安全项。`81df66d`将重核销身份按既有ID+UTC时间联合合同恢复：basis/anchor时间均非空，相同ID相同瞬间（含不同时区表示）仍拒绝，只有ID或时间不同才进入原保护条件；exact anchor、状态2、restoration、cancellation及原费用净额0均保留，无新增输入、SQL结构或写入入口。missing-fee与browser精确补丁复核如下。

### SEC-104-06：精确首次漏记费用工具的输入、事务与私有输出

`ba74d38`为6文件delta，3个业务/脚本Python完整内容Bandit：exit1，0 High / 0 Medium / 10 Low，0解析错误；5条既有assert不在新增行，新增5条为CLI的subprocess导入、git命令查忽略/跟踪状态的参数数组和PATH观察，无shell。秘密模式扫描0候选。安全单元在已提交实现树独立运行43项输入/只读/拒绝/CLI测试：43 passed / 15.37秒，exit0，禁用bytecode/cache，JUnit与basetemp全部留在本单元忽略目录。没有调用生产预演或apply。

- 请求固定8/9月、1..500精确券、正整数内部ID（拒绝bool）、带时区核销时间、重复身份拒绝、四组完整排除count/hash/交集；完整原manifest、排除文档、预算及业务quote均参与canonical SHA-256。`actor` / `approval_ref`是受控运维文档声明，不是独立密码学审批；排除清单是否完整仍需主线程与责任人按真实范围审阅。
- 默认预演使用fresh clean session、no-autoflush和PG REPEATABLE READ/READ ONLY；共享quote路径在原写入/锁定之前返回，拒绝任何费用历史/current指针，不创建DQ，不自动冻结10月资格。正常写入仍默认quote_only=False，复用原算法。
- apply仅PG，READ COMMITTED，重任务advisory事务锁、按名排序的关系写栅栏、券及账期锁；重读来源/config/保护事实并重新报价，精确预演hash不一致即整批拒绝。SQL结构来自固定代码/ORM或数据库catalog表名，catalog标识符双引号转义，业务ID数组绑定；剩余超时值来自内部整数预算，未拼接用户SQL。
- 费用输出必须恰好2*N、无调整/阻断，全部业务字段/current指针与quote一致；目标外财务/账单/票据/聚合/任务SHA不变，成功审计与费用同事务。重放校验原完整请求/排除/预演摘要及真实输出，不能用新预演绕过历史。
- CLI默认preview；输出只允许私有忽略/未跟踪或仓库外路径，先排他创建、0600再触库；stdout仅数量/hash/路径，SQLAlchemy异常不回显驱动原文。SQL锁等待1秒、语句5秒与应用事务30秒预算保留；前25秒不重复发送相同SET，末5秒逐SQL缩紧，超时回滚。该预算保护不等于373券当前能完成，不能绕过失败或自动拆批。

责任单元最终PG收据已回收并由本单元独立解析：38 tests / 0 failure / 0 error / 0 skipped；本单元没有重新执行PG，摘要及原XML保留于 `.tmp/security-final/`。373券应用预算停止且零新增，不以小样本通过冒称整体完成。`031dde6`补丁复核及独立CLI测试为7 passed / 40 deselected / 1.73秒，exit0；覆盖真实合成费用提交后的报告写入/关闭故障和提交响应丢失。补丁返回已提交true/exit4与不确定null/exit5，明确automatic_retry=false，给出hash审计定位，不暴露驱动消息，不把报告失败谎称业务回滚。最终范围、人工分区清单与每次真实预演/应用权限仍由主线程承接。

## 4. 风险分级

- Critical：原SEC-104-02的Pillow风险已在精确补丁与实际Linux选中版本关闭；本次覆盖范围未发现未解决Critical。
- High：原Web及browser固定包High已分别在精确锁/包审计关闭；实际Linuxsetuptools High按Debian修订及源码回补证据不再作为未修复项。没有把审计去重或发行版识别当作豁免。
- Medium：SEC-104-03既有CSV公式边界由DYDATA-107继续跟踪；setuptools sdist Unicode排除观察与供应商/审计修复口径差异保留，未宣称本Linux运行服务可利用。静态B608数量不是已证实Medium漏洞数量。
- Low：Windows限定setuptools legacy安装路径不符合Linux候选平台；CLI新git参数数组/PATH静态观察及既有assert告警保留，不作为独立阻断。

## 5. 阻断项

- 本报告限定快照集内无未解决Critical/High或新增阻断级代码、秘密、依赖、输入漏洞；原SEC-104-01/02已由精确修复、独立审计和实际Linux选中版本/供应商回补证据关闭。
- mandatory RELEASE门禁独立保留：精确最终集成HEAD的完整PG/远端CI、正式发布镜像与实际运行版本/部署回读必须对应，不得用本依赖兼容镜像、旧CI或局部测试代替。当前Linux候选是315bab1加双pin，而非最终业务集成镜像。
- 本报告不授权部署或执行真实费用修复，不放宽暂停券/保护账务、30秒预算、未来实际月底来源或业务验收。任何后续源码、解析包或导入路径变化须做对应delta复核。

## 6. 放行结论

- 最终结论：`PASS`，严格限定为本报告逐项列明的生产代码/依赖快照与已核对的browser依赖兼容候选之四域增量安全复核。
- 理由：请求的bootstrap、重核销authority、missing-fee及CLI结果分类、Web/browser依赖补丁均已复核；原Critical/High风险已修复，发行版误匹配已有实际修订与源码依据，未发现新增阻断项。现有Medium由DYDATA-107继续跟踪，无口头waiver。
- 边界：此PASS不等于DYDATA-104整票完成，不是最终集成镜像/CI/生产运行验收，不许可部署或真实数据应用。主线程保留并执行独立mandatory RELEASE门禁和最终发布判断。

## 7. 整改建议

- 立即整改：保留已完成的精确Web/browser修复与实际导入断言；无需仅为去除已回补的Debian版本告警额外升级setuptools/zipp。本报告没有执行audit fix、force升级或删除依赖检查。
- 完工前补齐：主线程对齐最终集成commit、PG/远端CI与发布镜像身份；最终重建若改变解析包或导入路径应重新复核依赖。SBOM/OS审计在独立制品门禁承接。安全复审不豁免阜阳应用、保护金额、月底事实或业务验收；373券超时必须按原预算停止，每份人工审阅的准确范围独立预演/审计，不新增自动拆批或循环。
- 完工后跟踪：SEC-104-03由 [DYDATA-107](https://linear.app/keith-lim/issue/DYDATA-107) 承接，主线程指定104 Codex集成人于2026-11-03前完成合同复核并提出交接；尚不代表用户批准开发/业务接受。本轮未将Medium关闭或作豁免。setuptools源分发条件/修复口径差异、python-novnc供应商审计缺口及XLSX展开预算测试为未分配跟进观察，责任/期限待主线程安排，不伪造已完成或新的风险接受。

## 8. Waiver 记录（如有）

- 无已批准waiver；未以“仅构建依赖”“来源可信”“未证明业务可达”作口头豁免。
- 若主线程后续收到正式豁免，须逐项附风险、责任人、批准依据、失效日期、临时缓解及补做事项后复审。本报告没有替用户批准任何风险接受或财务操作。
