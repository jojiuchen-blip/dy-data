# DYDATA-104 2026-10-27 发布前安全扫描

## 1. 扫描范围

- 扫描模式：`partial`，生产代码基线`9b1feb8`至发布集成`315bab141f5cfb6343f5cd7b6314e0f47491f30e`的增量审查，追加精确Web依赖修复`0096378d9e9d062903f9aa0193674f0caf468eb5`（主线程集成为`ff1b773`）的独立审计；四个默认域均实际执行：code、secrets、dependencies、api-input-validation。不是全仓历史安全认证或渗透测试。
- 稳定范围：财务四类导入/冻结预览及导出、月末资格/正式后台文件来源、历史更正及生命周期、受保护账单authority/只发布coordinator、SKU完整同步，以及同基线包含的商品类型/线索查询改动。相对基线共162个变更文件；Bandit扫描其中33个Python业务/脚本/迁移文件的当前完整内容，44519行。
- 最终自动月结/bootstrap、missing-fee repair新工具及browser固定包修复尚在其他隔离树，本报告此版**未覆盖这些后续commit**；收到最终提交后必须做窄delta复核，不能用当前基线报告放行后续代码。
- 未覆盖：生产/API请求、生产写入/部署、云/网络/完整多用户授权审计、完整Git历史及熵秘密扫描、最终Linux候选镜像全部安装包/OS漏洞及SBOM、运行时利用测试。不以本地Windows解析环境代替容器。
- 使用仓库`security-scan`及gate-contract、scan-scope、risk-rating-policy、report-template四份必需参考，另读standards-map。只写本报告及忽略目录证据，不修改业务、依赖、计划或共享索引。

## 2. 输入证据

- 计划及完成标准：[当前T3.1](../plans/delivery-plans/sub-delivery-plan-dydata-104-followthrough-T3.1-release-acceptance.md)、[总验证台账](../verification/dydata-104-oct27-delivery.md)。功能测试通过不等于安全域全部通过。
- 输入代码及逐文件SHA：`.tmp/security-oct27/changed-files.json`；工具版本、原始审计/静态结果SHA：同目录`evidence-manifest.json`。比较使用`git diff 9b1feb8 HEAD`，不是与错误的旧开发基线比较。
- 依赖归因：本扫描HEAD的`requirements.txt`、Web package/lock及`deploy/browser/Dockerfile`相对生产基线均无修改；本次发现的依赖风险为**基线原有而当前发布仍携带**，不能因本轮未引入就忽略。
- 实际命令及收据如下。`python`为已安装Bandit/pip-audit的工具解释器；测试使用隔离的项目测试解释器。没有安装/升级共享环境包、运行audit fix、外传源码或输出凭据；依赖审计仅提交公开包名/版本及需求元数据。
- 工具版本：Python 3.12.10、Bandit 1.9.4、pip-audit 2.10.1、npm 11.6.2。

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

- 部署边界：本次未访问生产；当前生产版本及`0065`、目标`0066`未部署等事实由总验证台账承接。Web最终镜像只复制静态dist，开发依赖不随node_modules进入nginx；但构建/Windows开发仍消费有漏洞工具链，不因此自动豁免High。
- 证据缺口：最终自动月结/依赖修复commit及复验、最终候选镜像digest/实际Python包清单与动态导入路径、SBOM/OS审计和部署后验收未取得。最终制品必须独立回收；当前运行镜像不能替代待发布镜像。
- 文档门禁：suite2.0.1锁有效，global为0错误/0警告，S4可进入；治理9 passed / 7.80秒，exit0。链接诊断为validate-only、exit0、37条既有问题，本报告关联问题0；没有重写共享索引。固定8章节、相对本地链接、敏感路径/值模式及`git diff --check`通过。它们不代表安全阻断解除。

## 3. 发现项

### SEC-104-01：Web原High已独立复审消除，保留发现轨迹

`vite@7.3.5`、`source-map-js@1.2.1`、`esbuild@0.27.7`均与生产基线相同。官方npm审计为2个High包及1个Low包；一个包可对应多个公告，不把公告数当包数。

- `source-map-js`的indexed source-map offset可导致同步事件循环耗尽；受影响`>=1.0.0 <1.2.2`，修复1.2.2。依赖链为Vite→PostCSS→source-map-js。[公告](https://github.com/advisories/GHSA-68fv-2mgg-jv7q)
- Vite命中launch-editor系列公告，最高High；Windows文件路径检查绕过可结合命令参数问题形成注入。官方对Vite 7列修复7.3.7，不能只以Linux静态部署否定Windows开发/测试工具链风险；没有执行利用。[维护者公告](https://github.com/vitejs/launch-editor/security/advisories/GHSA-587h-7wmj-h5pm)
- esbuild是Windows开发服务器路径穿越Low，修复0.28.1。其条件与Vite构建风险分开记录；不将Low单独当阻断。[维护者公告](https://github.com/evanw/esbuild/security/advisories/GHSA-g7r4-m6w7-qqqr)

独立修复`0096378`已将精确版本升级为Vite7.3.7、source-map-js1.2.2、esbuild0.28.2；本执行单元从该commit取Git对象快照重新执行官方全锁及omit=dev审计，均exit0、0漏洞。主线程报告修复后5项真实API浏览器通过；本报告没有自行重跑这5项，也不将精确锁文件审计当npm ci/build或最终镜像已通过。此发现的依赖版本风险已在修复快照关闭，最终集成/制品验证仍独立承接。

### SEC-104-02：browser显式固定包存在Critical/High，requirements零命中不足以放行

`deploy/browser/Dockerfile`额外强制安装`urllib3==2.7.0`、`Pillow==12.3.0`等5包，随后断言版本和`/usr/local/lib`实际导入。当前requirements的64包解析不会覆盖这些固定版本，不能用其0漏洞覆盖本发现。精确pins审计40条公告；GitHub**聚合元数据快照**分布为4 Critical、24 High、12 Medium（单项有界重试后40条均取得），这不是逐条维护者口径已统一的风险总数。下表独立读取维护者原文发现两项分级差异，**以维护者原文优先**，并保留聚合记录，不武断改写任一原始来源。

| 组件 / 典型已核实公告 | 级别与条件 | 官方修复 |
|---|---|---|
| urllib3 `GHSA-vxq7-64xx-v4gw` | High；HTTPResponse流/分块读取可无界缓存chunk-size行 | 2.8.0；[维护者公告](https://github.com/urllib3/urllib3/security/advisories/GHSA-vxq7-64xx-v4gw) |
| Pillow `GHSA-w889-685w-c8fh` | **Moderate（维护者）/Critical（聚合）**；Ghostscript参数注入，需对应解释器、EPS处理及受控路径等条件 | 13.0.0；[维护者公告](https://github.com/python-pillow/Pillow/security/advisories/GHSA-w889-685w-c8fh) |
| Pillow `GHSA-332p-7hrc-92wf` | **High（维护者）/Critical（聚合）**；保存TIFF到BytesIO的原生缓冲区溢出；维护者未声称已证明代码执行 | 13.0.0；[维护者公告](https://github.com/python-pillow/Pillow/security/advisories/GHSA-332p-7hrc-92wf) |
| Pillow `GHSA-v9pv-5gc8-w2m6` | Critical；多帧加载器模式转换后的原生存储复用 | 13.0.0；[维护者公告](https://github.com/python-pillow/Pillow/security/advisories/GHSA-v9pv-5gc8-w2m6) |
| Pillow `GHSA-5x8w-8jj5-q52h` | Critical；安装可选olefile且打开特制FPX图像时的JPEG解码堆溢出 | 13.0.0；[维护者公告](https://github.com/python-pillow/Pillow/security/advisories/GHSA-5x8w-8jj5-q52h) |

其余公告、aliases去重、受影响范围和修复版本保留于`browser-advisory-severities.json`及每条原始公告；该文件保留聚合口径，维护者差异另见`maintainer-severity-comparison.json`。至少上表两项Critical及urllib3/TIFF的High已按维护者原文确认，足以保持阻断；不需要把聚合40条统一强行定级。未声称当前业务可以触发所有图像格式、Ghostscript/olefile已安装或漏洞已被利用；也没有据“未证明可达”自行waiver。最终镜像可能同时有apt与pip包，必须按实际metadata及模块导入路径核对，避免只升级一个未被导入的副本。

### SEC-104-03：财务CSV保留电子表格公式文本（既有Medium）

本地纯helper用无害`=1+1`验证：`dashboard.py::_finance_import_error_csv`的`originalValue`和`_finance_order_detail_csv`的文本字段读回仍以`=`开头。CSV引号只维护语法，不会禁用电子表格公式；这里没有执行公式或构造外带请求。三个相关CSV helper的AST与`9b1feb8`完全相同，属于既有导出边界，本轮未引入。

错误值来自上传文件；其他文本来自业务来源，下载者用支持公式的表格软件打开才进入风险路径。当前未提供“安全表格模式”与“原始证据值”的独立合同，不建议为消除扫描告警直接覆盖审计原值或打乱长ID/负金额。按Medium记录，需由主线程登记责任与期限并选择安全呈现/导出方案；不是允许任意公式的业务验收。

### SEC-104-04：静态告警复核与输入控制

- Bandit的82个Medium中80为低置信B608；另两个是既有CDP环境配置URL读取及目标发布脚本临时备份路径。全文件扫描包含旧代码，未逐项认证旧模块安全。按新增行相交得到20条候选：13条B608及7条固定参数subprocess类Low；未发现新增High。
- 13条新增SQL候选来自0066固定表/操作枚举、固定商品类型SQL表达式及参数化查询的组合。表/列/语法不来自HTTP值，订单ID、类型、门店集合由`:name`绑定/生成占位符传入；未发现将新增用户值插为SQL结构的路径。转换CLI使用参数数组调用git、不使用shell。静态结果不是SQL注入的直接证明。
- 新冻结rows API在管理员、类型页权及整批门店scope校验后返回；page≥1、pageSize≤50，preview仅模板字段及相关状态，不返回完整raw或文件URL。React新预览用文本节点，不使用新innerHTML/eval。42项合成测试覆盖白名单、不漂移、权限重验、金额/月/scope、ASCII票号、存储边界、manifest/任务来源拒绝。
- 财务上传限制10MiB压缩/原始文件、5000行及CSV/XLSX类型；只读data_only解析不执行表格公式，文件名未作为服务器保存路径。此大小限制不等于已验证所有XLSX展开/解析资源上界；未进行解压炸弹/负载测试。后台任务文件以basename落私有临时目录，签名URL仅在内存，不进入永久proof；来源主机/运行权限完整加固不在本次默认四域的全面认证内。
- 新历史更正manifest严格字段集、16方向、分金额真整数（拒绝bool）、原费/来源SHA及月份/版本；默认只读preview，apply必须明确参数及匹配预演hash，来源/保护/事务失败关闭。审批字段由受控运维manifest承载，不声称它们是独立密码学审批系统。
- 秘密扫描仅保存路径/行号/分类，0候选；覆盖变更文件当前内容的私钥头、AWS/GitHub/service token、凭据URL、JWT及长秘密字面量规则。不是完整历史、熵、外部配置或运行日志安全认证。

## 4. 风险分级

- Critical：SEC-104-02至少两项Pillow维护者Critical；聚合快照的另两项Critical分别被维护者列为Moderate/High，按维护者记录，不能称为四项统一确定Critical。当前仍默认阻断，没有书面豁免。
- High：SEC-104-02维护者已核实urllib3及TIFF High；聚合快照另有24条High记录但未将全部维护者分级逐条统一。SEC-104-01原两个High包已在修复快照独立审计消除。按组件/公告分别记录条件，不将命中等同业务可利用。
- Medium：SEC-104-03既有CSV公式边界；Pillow Ghostscript维护者Moderate及聚合其他Medium记录保留。静态B608数量不是已证实Medium漏洞数量。
- Low：SEC-104-01原esbuild已在修复快照消除；其余旧静态观察及受限扫描覆盖在证据缺口中保留。

## 5. 阻断项

- SEC-104-01原版本阻断已由精确修复快照独立audit解除；最终HEAD仍须提供npm ci/TypeScript/Vite及相关浏览器/制品收据，不能仅提交lock或只跑omit=dev。
- SEC-104-02：移除候选browser的已知Critical/High固定版本，保留有效依赖/导入路径检查；逐项复审固定pins并对**新候选镜像**实际包清单复验。不得用当前生产镜像或Windows最新解析结果替代。
- SEC-104-05（证据门禁）：最终自动月结/bootstrap、missing-fee repair新工具及browser依赖修复尚未回收，当前315bab1加Web修复报告不覆盖它们；补差异扫描与关键输入/事务边界复核后才能给最终范围结论。
- 未满足条件由主线程集中承接；本扫描执行者不自行改依赖、操作生产或登记豁免。

## 6. 放行结论

- 最终结论：`BLOCK`。
- 理由：已知Critical/High仍在当前候选声明中，没有书面waiver；最终delta及实际制品依赖证据未齐。requirements/生产npm依赖0漏洞、42项测试或旧CI通过均不足以推翻这些事实。该结论不声称发现真实入侵或全部业务可利用路径。

## 7. 整改建议

- 立即整改：主线程已接收SEC-104-01/02，由独立责任单元最小修复；本报告只记录，不执行audit fix、force升级或删除依赖检查。公开公告所列修复版本须结合实际兼容构建审查。
- 完工前补齐：最终commit与窄delta、修复后审计/构建/浏览器回执，候选镜像digest及实际导入包/供应商修订核对、SBOM与独立部署闸门。安全报告复审通过也不豁免阜阳应用、保护金额、月底事实或业务验收。
- 完工后跟踪：SEC-104-03建议由主线程/财务维护者登记、目标2026-11-03前形成安全CSV与原始证据保真的处理合同（建议期限，尚未批准）；补充XLSX展开预算/资源测试。未登记期限前不将Medium事项记为已关闭。

## 8. Waiver 记录（如有）

- 无已批准waiver；未以“仅构建依赖”“来源可信”“未证明业务可达”作口头豁免。
- 若主线程后续收到正式豁免，须逐项附风险、责任人、批准依据、失效日期、临时缓解及补做事项后复审。本报告没有替用户批准任何风险接受或财务操作。
