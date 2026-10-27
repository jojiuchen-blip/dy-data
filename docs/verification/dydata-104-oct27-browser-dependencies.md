# DYDATA-104 2026-10-27 browser 固定依赖修复

## 范围与变更

承接 T3.1 / SEC-104-02，修改 browser Dockerfile 的 `urllib3 2.7.0 → 2.8.0`、`Pillow 12.3.0 → 13.0.0`，并同步构建断言与配置回归。保留 `msgpack 1.2.1`、`idna 3.19`、`jwcrypto 1.5.7` 三个原 pin，以及原有五包的实际版本和 `/usr/local/lib` 导入路径断言。未修改共享 Python 环境、Web、CI、生产或业务数据。本任务无 foundation 漂移。

新增合成兼容性测试覆盖 Pillow 的 RGB PNG/TIFF 内存保存、读取、缩放，以及 Requests / urllib3 的普通 JSON、分块流式 JSON 读取。测试不构造漏洞利用载荷，不访问真实业务账号。

## 风险来源口径

原五包审计有 40 条公告记录：urllib3 3 条、Pillow 37 条，其他三个固定包为 0。数量是审计公告记录，不等于 40 个已证实业务可利用路径。维护者公告与聚合分级存在差异时，以维护者记录为准：

| 公告 | 维护者分级 | 修复版本 |
|---|---|---|
| [GHSA-vxq7-64xx-v4gw](https://github.com/urllib3/urllib3/security/advisories/GHSA-vxq7-64xx-v4gw) | High | urllib3 2.8.0 |
| [GHSA-v9pv-5gc8-w2m6](https://github.com/python-pillow/Pillow/security/advisories/GHSA-v9pv-5gc8-w2m6) | Critical | Pillow 13.0.0 |
| [GHSA-5x8w-8jj5-q52h](https://github.com/python-pillow/Pillow/security/advisories/GHSA-5x8w-8jj5-q52h) | Critical | Pillow 13.0.0 |
| [GHSA-w889-685w-c8fh](https://github.com/python-pillow/Pillow/security/advisories/GHSA-w889-685w-c8fh) | Moderate（聚合快照曾列 Critical） | Pillow 13.0.0 |
| [GHSA-332p-7hrc-92wf](https://github.com/python-pillow/Pillow/security/advisories/GHSA-332p-7hrc-92wf) | High（聚合快照曾列 Critical） | Pillow 13.0.0 |

维护者元数据快照为 `.tmp/browser-deps/official-advisory-metadata.json`；原审计及复核归属见 [发布安全报告](../security/dydata-104-oct27-release-security.md)。本记录不宣称发生过漏洞利用或实际入侵。

## 本地验证

原始收据保存在忽略目录 `.tmp/browser-deps/`，用于本轮交接；不提交依赖安装产物、镜像或真实业务资料。

| 检查 | 结果 | 收据 |
|---|---|---|
| 套件锁、全局文件、S4 路由、计划一致性、T3.1 环境及任务上下文 | 全部通过；全局文件 0 error / 0 warning，`passed/envReady/canExecute=true` | 本轮命令回执 |
| 隔离 Python 3.12 专项 pytest | 90 passed，3 条既有 `ExportedWorkbook/PurePath` 弃用警告，exit 0 | `isolated-tests-final.log` |
| 新五包固定版本审计 | 5 包、0 已知公告，pip-audit 2.10.1，exit 0 | `fixed-pins-after-final-audit.json/.log` |
| 隔离 Windows 解析环境 | 原执行者的解析/安装收据：69 包、0 公告；`pip check` 通过。仅作补充，不能代替 Linux 镜像 | `resolved-environment-audit.json/.log`、`pip-check.log` |
| 原 Docker 构建 | 未产出候选镜像；BuildKit inspect 为 `canceled / context canceled`，日志停在共享依赖下载；接续时 Linux daemon named pipe 不存在 | `docker-build.log`、`docker-build-original-result.json` |
| 公共 PyPI 续建 | 元数据下载缓慢并出现超过 120 秒的停顿；本任务显式停止对应 buildx 客户端，保留收据后改用 Dockerfile 默认镜像源 | `docker-build-resumed.log`、`docker-build-stop.json` |
| 默认 Debian 源重试 | 首个包下载长时间停顿；独立本地容器探测 Debian HTTP 返回 `RemoteDisconnected`，停止本任务 buildx 客户端 | `docker-build-mirror.log`、`docker-build-mirror.exit.txt` |
| HTTPS APT 镜像尝试 | Debian slim 基础层未安装 CA 证书，APT 报 issuer unknown；停止重试，没有关闭证书校验 | `docker-build-https-mirror.log` |
| HTTP APT 清华镜像 + 原默认 pip 清华镜像 | 构建通过，exit 0；通过 Dockerfile 已有 `APT_MIRROR` 构建参数切源，源码未变 | `docker-build-http-mirror.log/.exit.txt` |
| 候选镜像实际安装包与导入路径 | Python 3.11；五包版本符合声明，六个模块全部从 `/usr/local/lib/python3.11/dist-packages` 导入；APT 元数据及文件保留，选中版本覆盖原版本 | `linux-image-smoke.json`、`linux-image-distributions.json` |
| 候选镜像依赖一致性 | `python3 -m pip check` exit 0，No broken requirements found | `linux-image-pip-check.log` |
| 候选镜像真实 Python 包审计 | 99 包清单，审计 exit 1：setuptools 66.1.1 命中 7 条、zipp 1.0.0 命中 2 条，去重为 5 个公告 ID；python-novnc 1.0.0 无 PyPI 记录而跳过。五个固定包仍为 0。发行版回补待复核，不将原始审计写为通过 | `linux-image-freeze.txt`、`linux-image-python-audit.json/.log/.exit.txt` |
| 无外网桌面 / CDP / 图像 smoke | `--network none`、不映射端口、不挂业务卷；初始及结束均 `about:blank`，Chromium 156.0.8078.47，CDP 截图 1050×837，Pillow PNG/JPEG/TIFF 处理通过，桌面/CDP/VNC/WebSocket 健康检查前后均 exit 0 | `linux-image-smoke.json`、`linux-image-healthcheck*.log`、`linux-container-startup.log` |
| 候选镜像兼容性 pytest | 3 passed / 0 skipped，exit 0 | `linux-image-pytest.log` |

专项命令：

```powershell
.tmp/browser-deps/venv/Scripts/python.exe -m pytest tests/test_browser_image_dependency_compat.py tests/test_deploy_compose_config.py tests/test_browser_runtime.py tests/test_backend_aweme_parser.py tests/test_backend_aweme_proof.py tests/test_backend_aweme_login_recovery.py tests/test_backend_aweme_export_job.py -q
python -m pip_audit --no-deps --disable-pip -r .tmp/browser-deps/fixed-pins-after.txt -f json -o .tmp/browser-deps/fixed-pins-after-final-audit.json
docker build --progress plain --build-arg APT_MIRROR=http://mirrors.tuna.tsinghua.edu.cn -f .tmp/browser-deps/build-context/deploy/browser/Dockerfile -t dydata104-browser-deps:oct27 .tmp/browser-deps/build-context
```

构建使用基于 `315bab141f5cfb6343f5cd7b6314e0f47491f30e`、只含 280 个跟踪源文件及本补丁 Dockerfile 的隔离上下文；Dockerfile 与当前改动文件 SHA-256 一致。它不覆盖其他工作树后续业务提交，最终发布集成树仍须重新构建。执行前本地 C 盘可用约 202 GiB；未清理其他镜像、容器、卷或构建缓存。

本地候选 tag 为 `dydata104-browser-deps:oct27`，Image ID / manifest-list digest 为 `sha256:6a1c23aff303ca92901d66a0a3556ecd887b9ebd2db459a456b3312df581ee41`；Linux 平台 manifest 为 `sha256:3fd68f05df3e5f2e46f3c3eeabcf27690ec87a4e0da26bd3495063cfd7d58826`。完整 inspect 为 `linux-image-inspect.json`。

APT 保留版本分别为 `python3-urllib3 1.26.12-1+deb12u4`、`python3-msgpack 1.0.3-2+b1`、`python3-pil 9.4.0-1.1+deb12u1`、`python3-idna 3.3-1+deb12u1`、`python3-jwcrypto 1.1.0-1+deb12u1`；选中的 pip 版本分别是 2.8.0、1.2.1、13.0.0、3.19、1.5.7。`importlib.metadata.distributions()` 可见两套元数据，`version()` 与模块导入实际选中本地覆盖层。

新增审计命中来自 APT 的 `python3-setuptools / python3-pkg-resources 66.1.1-1+deb12u2`、`python3-zipp 1.0.0-6+deb12u1`。`linux-image-vendor-source.json` 保存选中的 `setuptools`、`setuptools.package_index`、`pkg_resources`、`zipp` 实际 `/usr/lib/python3/dist-packages` 路径、完整源码及 SHA-256。已直接核对 `package_index` 中的参数数组调用和 `_download_url` 临时目录检查，以及 zipp 的 `SanitizedNames`；独立安全复核又重算四份源代码 SHA 并匹配成功。其供应商回补与条件判定如下，完整风险结论以 [安全报告](../security/dydata-104-oct27-release-security.md) 为准：

| 去重公告 | 选中包 / 条件复核 |
|---|---|
| [CVE-2024-6345](https://security-tracker.debian.org/tracker/CVE-2024-6345) | 上游 High；Debian `66.1.1-1+deb12u1` 已修复，实际为 u2，所选源码使用 subprocess 参数数组 |
| [CVE-2025-47273](https://security-tracker.debian.org/tracker/CVE-2025-47273) | 维护者 Moderate；Debian u2 已修复，实际源码保留下载目录检查 |
| [CVE-2024-5569](https://security-tracker.debian.org/tracker/CVE-2024-5569) | Moderate；实际 Debian zipp `1.0.0-6+deb12u1` 达到供应商修复版，源码包含名称净化回补 |
| [GHSA-h35f-9h28-mq5c](https://github.com/pypa/setuptools/security/advisories/GHSA-h35f-9h28-mq5c) | 维护者 Moderate，sdist 的 Unicode 规范化/排除规则及文件系统条件；保留供应链观察，不按原始版本命中直接判定本 Linux 服务 High。审计修复版与维护者当时 patched=None 的口径差异保留在安全报告 |
| [GHSA-xmj3-9gf7-h52w](https://github.com/pypa/setuptools/security/advisories/GHSA-xmj3-9gf7-h52w) | 维护者 Low，Windows 旧 wheel 安装路径条件；本候选为 Linux，不满足 Windows 条件 |

上游版本扫描丢失 Debian 修订号；上述是供应商证据与运行条件复核，不是将 `pip-audit` 的 exit 1 改为 0，也不是豁免所有告警。99 包审计中无法查询 PyPI 的 `python-novnc`、剩余供应链观察和未做 OS/Chromium 全量扫描均继续保留。

原始收据的本地 SHA-256 清单见 `evidence-manifest.json`。本地构建上下文 Dockerfile 与 Windows 工作区文件字节相同，SHA-256 为 `cfe594b72ffda6a7656070296b29553bfb6a2d24afd7c6de6e6fe878e23ebf15`。Git 将其 93 个 CRLF 规范化为 LF，提交 `a97b19b8fa70cf9ed3c66df185049187f48376aa` 的 blob SHA-256 为 `773a7cb61408896b2088fc15368e9bed9f035dbb2580f5c565e1283ace89773d`；归一 LF 后逐字节完全一致，断言与原始摘要保存在 `dockerfile-provenance.json`。仅通过原有 `APT_MIRROR` 参数修改容器内 APT 源地址；没有另改临时 Dockerfile 内容或关闭签名/证书检查。此兼容性候选不冒充最终发布集成镜像。

## 交付限制

本项不是整票验收、生产发布或完整 OS / Chromium 漏洞认证。最终集成树的完整测试、CI、安全 delta 复核、目标部署版本及生产回读由主线程统一完成。候选 browser 重新构建后才会携带新包；回滚使用上一已验证镜像，需同时保留其已知依赖风险，不将回滚称为安全修复。
