# DYDATA-104：publication-only CLI 资源观察预算修复

## 问题与范围

基线 `d4285711`。本任务仅修复 [publication-only CLI](../../scripts/ops/publish_settlement_authority.py) 的观察等待预算，不改变资源策略、健康阈值、采样间隔、正式发布服务或来源预演 hash。任务承接 DYDATA-104 已登记的准入问题。

现有 `ResourceMonitor` 每个进程以 protected 开始，默认连续健康 recovery 180 秒，再连续 stable 600 秒，才允许历史重任务。CLI 原默认等待90秒、参数上限600秒，均短于完整780秒；即使持续健康也会先退出。反复启动新的CLI会重新观察，不能解决这个预算冲突。

## 候选行为

- 默认预算为 `max(900, ceil(recovery_duration_seconds + stable_duration_seconds + max(30, 3 * SAMPLE_SECONDS)))`。阈值通过正式 `PressureThresholds.from_env()` 读取，保留现有别名和合法性校验；不把配置写回环境。
- 默认配置预算900秒；例如 recovery240秒、stable960秒时预算1230秒，覆盖完整1200秒及采样裕量。
- `--admission-wait-seconds` 显式接受0至1800秒。短预算可提前拒绝，但不能提前允许；上界有界，未增加自动重试。
- 配置推导默认值超过1800秒时，在启动monitor前明确参数错误，不静默截成不足完整观察的预算。操作者仍可显式指定上界内预算进行一次受限尝试，未获ALLOW即拒绝。
- dry-run继续调用原正式预演，不读取本次压力窗口设置、不启动monitor。apply仍由本进程正式monitor给出真实ALLOW，再以原月份及精确preview hash调用原正式服务；成功或拒绝均保留原stop清理。
- 未修改 `initial_state`、恢复/稳定时间、资源guard开关、心跳归属、正式服务校验、数据库结构或SQL/事务预算，不从其他进程借用准入结论。

[正式契约](../prd/foundation/foundation-api-dy-data/settlement-authority.md)已由主入口按S4-FCR-020同步派生默认与0..1800秒显式范围，保留旧预算缺口和修前失败；没有新业务规则或DDL。合同和本地候选不代表生产已生效。

预算只覆盖正常连续采样的完整观察时间。持续压力、采样异常或正式服务重新校验发现来源变化仍须拒绝；扩大等待预算不保证发布成功。

## 回归与原失败证据

新增 [CLI资源等待测试](../../tests/test_settlement_publication_cli_resource_wait.py) 以真实 `ResourcePressurePolicy(initial_state="protected")` 和受控测试时钟，每5秒输入样本。未修改主机时间，不真实睡眠13分钟，不启动生产monitor或写入账务。该文件的正式服务入口由替身记录调用，既有 [publication-only测试](../../tests/test_settlement_publication_only.py) 继续验证隔离环境的正式服务及保护逻辑。

修前运行默认健康用例：**1 failed**。CLI返回`not_admitted`且服务调用0；原90秒无法达到780秒。修后同一用例在0秒为protected、180秒recovering、775秒仍recovering、780秒normal后才调用服务，月份及hash原样传递。

定向命令：

```text
python .tmp/run-repository-pytest.py tests/test_settlement_publication_cli_resource_wait.py tests/test_settlement_publication_only.py -q --junitxml=.tmp/cli-admission-after.xml
```

本地launcher仅为本仓库namespace覆盖机器上另一个已安装的`tests`包，不修改断言、删除测试或隐藏失败。干净环境可直接使用`python -m pytest`运行同两文件。

结果：**30 passed / 0 failed / 0 error / 0 skipped，17.31秒**，其中新增CLI17项、既有publication-only13项。仅现有Starlette/httpx弃用警告1条。

覆盖持续健康780秒、持续不健康900秒耗尽、显式0/90/600短预算、配置长窗口及别名、1800上界、负值/越界/非整数输入、超上界配置与显式受限尝试、非法策略及dry-run不启动monitor。`git diff --check`通过。

工作树忽略目录保留原始JUnit和日志，不覆盖失败收据：

| 收据 | SHA-256 |
|---|---|
| `.tmp/cli-admission-before.xml` | `c2be9946216641209fc1b88440dc4f0f8cbb6bacd2d3fa7347b10a7c7d87fefd` |
| `.tmp/cli-admission-before.log` | `7dc96e220eaeabf4cabd8f9ff941e78053931f481ee9432a80b3eedbbe2e0084` |
| `.tmp/cli-admission-after.xml` | `f10df5c355d70dde949251c1781b25a2651070a83370e2b6d7197e52beebe59c` |
| `.tmp/cli-admission-after.log` | `61df7f42c0f00eaa8253ee249b973fce9a3a4dc14c74d0cc55aa74f3d0c7eefb` |

## 交付边界

本定向修复提供候选代码、测试与本记录；整体PR、CI及生产交付以[主线程证据](dydata-104-oct30-delivery.md)为准。生产仍以Root实际983运行读回为准；Root正在执行的独立资源观察不受本地源码修改影响。真实准入、固定hash发布、独立只读回读及8/9月业务验收由Root串行执行，本测试不能替代这些证据。
