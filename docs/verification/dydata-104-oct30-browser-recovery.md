# DYDATA-104 浏览器关键进程恢复

需求范围：[DYDATA-104](https://linear.app/keith-lim/issue/DYDATA-104)既有生产运行可靠性及月底采集前置；本补丁不改变月末资格、导出证明或财务规则。

## 已证实缺口与修复

旧入口后台启动Chromium、Xvfb和CDP代理后交给Python监督桌面；监督器只拥有fluxbox、x11vnc和websockify。Chromium退出后主进程仍可存活，容器不健康但不触发退出恢复；桌面重试耗尽也仅写失败标志继续循环。健康只探测内部9223，未覆盖Worker实际使用的9222代理。

新监督器统一拥有六个进程组：先启动Xvfb并等待真实连接，再启动Chromium、CDP代理及桌面。任一关键进程退出或持续健康失败，停止本代进程组并按1/2/4秒退避重建。健康检查同时覆盖内部CDP、外部CDP代理、VNC协议和WebSocket。正常停止时逆序清理全部进程组；browser专属停止宽限为30秒。

## 恢复预算及状态

- 现有`browser-runtime:/run/browser`卷保存`browser-runtime-recovery.json`；滚动15分钟最多4次整栈启动（首次与最多3次恢复）。容器重启不能清除账本；连续健康60秒只重置退避，不释放滚动额度。
- 第一次耗尽明确非零退出；替换容器看到相同账本后不启动Chrome，等待剩余冷却（最长15分钟），健康明确失败。窗口自然淘汰后再恢复，避免反复退出和无限快速拉起。系统时钟异常、损坏/超大/符号链接状态失败关闭。
- 预算和进程状态文件原子写入，大小上限4KiB、权限0600；每个子进程日志最多当前1MiB＋前一份1MiB，轮转不输出内容。失败标志只保存受控原因代码。
- 正常主动停止撤销本次正常启动占用，不删除此前失败记录。强制终止未能完成清理则保留记录。
- 管理员明确决定恢复时，先停止browser，再使用挂载同一个runtime卷的受控一次性容器运行`python3 /usr/local/bin/browser-runtime.py reset-recovery-budget`；只清监督预算和失败标志。不要在运行中的监督器旁并发重置，不修改Cookie、档案、月末采集身份/8次预算或已记录失败。

浏览器沿用原用户、`XDG_CONFIG_HOME/chromium`及profile命名卷；只在旧代进程已停止后清理已知Singleton进程锁，不删除登录资料。无法证明月底完整采集时，既有月底冻结保护继续拒绝，不用旧快照伪造成功。

## 验证

`tests/test_browser_runtime.py`覆盖外部代理失效、关键子进程退出、持久滚动预算/冷却、替换监督器、显式恢复、完整清理及档案保护；原显示、桌面重试及协议探测保持。

`tests/test_browser_process_recovery_image.py`通过`DY_BROWSER_RECOVERY_IMAGE`显式指定受测镜像。三个真实Docker场景分别杀Chromium、Xvfb、CDP代理，要求新一代恢复健康，再执行真实SIGTERM/容器重启并验证预算和虚构档案canary保留。每例使用唯一合成容器/自建runtime卷、`--network none`、`about:blank`及虚构VNC密码；finally只清理本例精确容器/卷，不挂载生产profile。每例恢复观察预算90秒。未配置镜像时跳过，正式CI须显式配置并要求三个场景全部执行。

本机Docker daemon未运行，真实镜像恢复证据待Root正式CI取得；本地单元/契约通过不能替代镜像或生产验收。未执行生产重启、profile写入或月底采集。

本地命令：`python -m pytest -q tests/test_browser_runtime.py tests/test_deploy_compose_config.py tests/test_account_qualification.py tests/test_browser_process_recovery_image.py`，结果110 passed / 3 skipped（仅未配置镜像的三个真实恢复场景），6.93秒。`git diff --check`通过。后续目标提交镜像及CI结果须独立回填。

## 生产待核验

核对实际runtime/entrypoint源码摘要、失败标志、六个受监督PID及CDP两端结果；读取有界脱敏子进程日志和可取得的OOM事件时间/受害进程。仅凭`OOMKilled=true`不能定位时间或原因。恢复前核对导出active marker及对应在途任务，恢复后验证真实登录与采集完整性。生产容量和正式部署门禁独立满足。

本任务无foundation漂移；未新增API、持久业务Schema或业务术语。
