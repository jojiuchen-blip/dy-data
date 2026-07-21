# dydata Agent 调用指南

## Transport and credential hardening

HTTPS is required for remote API URLs. The only cleartext exception is explicit loopback HTTP
(`127.0.0.1`, `localhost`, or `::1`) with an explicit port for local development.
URLs containing credentials, query strings, fragments, ambiguous
paths, or non-loopback HTTP hosts are rejected before any request is sent.

Only GET requests are retried automatically. All authentication POST requests are single-submission,
so a dropped response cannot silently duplicate a device
grant, refresh rotation, or revoke operation. Credential rotation and deletion
use a cross-process lock plus compare-and-swap semantics. A transient revoke
failure is handled so that transient revoke failure preserves the local credential;
successful or confirmed-invalid revoke
compare-deletes only the credential state observed by that logout invocation.
Expired credentials use refresh single-flight: the cross-process lock is held from
the second credential read through refresh rotation and keyring replacement. The
lock timeout bounds waiting, and the operating system releases the lock if the
owning process crashes. The lock file contains no credential material.

## 定位与前提

`dydata` 是面向已授权账号的只读业务查询 CLI。Agent 可调用的业务命令不会写入业务数据；`auth login` 与 `auth logout` 只改变远端认证授权和本机凭据状态，不修改业务数据。两条认证命令的 `agent_callable` 均为 `false`，不得作为 Agent 自主步骤执行。不要声称、尝试或暗示 CLI 可以写入订单、线索、门店或其他业务数据。

按安装后的入口使用 `dydata`。Windows 上如果提示找不到该命令，请确认 Python Scripts 目录已在 `PATH`；在开发环境可用 `python -m dydata_cli.main` 作为等价入口。

命令目录的运行时权威来源是 `dydata commands --json`。`docs/cli-command-reference.md` 只是从该目录自动生成的可读副本，不能替代发现命令或手工维护。部署后的 Agent 接入验证按 [Agent CLI 使用验收](cli-agent-acceptance.md) 执行。

## 登录与人工交接

Agent 可以在用户明确要求后启动 `dydata auth login`，前提是 Agent 的命令工具提供可由用户接管的真实安全交互 TTY。命令启动后，凭据输入和授权确认仅由人工执行；Agent 必须在 `Username:` 出现前停止代填并把输入权交给用户。`human_handoff.agent_may_launch` 是唯一窄例外：它只解除“不得启动”这一点，不把命令变成 Agent 可自主完成的调用，也不允许 Agent 提供任何凭据。

默认终端流程中，账号由用户输入，密码使用终端隐藏输入。不得把账号或密码粘贴到对话，也不得通过参数、环境变量、配置文件、脚本或管道把密码交给 CLI。Agent 不接收、读取、传递、保存或展示凭据，不得要求用户把 Token、Cookie、密码或密钥复制到聊天中。用户名、服务端确认的账号、角色和门店范围会显示在终端中；密码、Cookie 和 Token 不会显示。默认终端流程不显示内部 `device_code`。

如果命令返回 `INTERACTIVE_REQUIRED`，说明当前环境不能保证隐藏输入；停止终端登录，改由用户执行浏览器回退。回退命令是 `dydata auth login --browser`：

```powershell
dydata auth login --browser
```

浏览器回退会显示一次性 `user_code` 和验证地址，用户必须在浏览器中核验账号并批准。该 `user_code` 不是内部 `device_code` 或 Token，但 Agent 仍不得读取、转交、代用浏览器 Cookie 或代替用户确认。

检测到已有本地凭据时，登录是无网络、无覆盖的安全 no-op。需要切换账号时，先执行 `dydata auth logout`，确认本地凭据撤销后再重新登录；不得绕过这一顺序覆盖或删除并发进程写入的新凭据。

## 安全调用顺序

先发现，再核验身份和范围，最后做一次明确、只读的查询：

```powershell
dydata commands --json
dydata auth status --json
dydata stores list --json
dydata clues follow-up-stats --from 2026-07-14 --to 2026-07-20 --output json
```

1. **发现。** 每个新任务先执行 `dydata commands --json`，只使用返回目录中 `agent_callable: true` 的命令和参数；不能猜测、拼接或探测未声明的命令。
2. **认证。** 如果尚未登录，由 Agent 在用户明确要求且工具支持安全 TTY 时启动登录，并立即交给用户；否则使用浏览器回退。`auth status` 只用于确认本机登录状态，不输出凭据。
3. **范围。** 每次数据查询都以服务端的实时权限和当次 `stores list` 的可见门店为准。Agent 不得自动扩大门店范围；指定 `--store-id` 时也只能使用已授权范围内的门店。权限或范围失败时停止并如实报告。
4. **查询。** 只发起目录中明确声明的只读查询。一次请求失败时按全成全败处理：不得把部分结果当成完整答案，不得伪造、补全或跨门店重试。

## 线索跟进统计

默认对外展示 `system_follow_up_rate`：它代表系统认定的有效跟进率，是业务汇报的默认指标。`action_follow_rate` 仅用于回答“是否联系过”或解释两者差异，不能替代默认指标。

`clues follow-up-stats` 的日期必须成对提供 `--from` 和 `--to`，格式为 `YYYY-MM-DD`。未提供日期时按北京时间取含当天在内最近 7 天；开始日期不能晚于结束日期，区间最多 366 个自然日（含首尾）。结果为零时，如实报告零数据；不得为了产出结论而扩展日期、门店或补造数据。

## 错误与退出码

任何错误都要保留命令输出中的结构化错误信息并停止当前结论：`2` 是参数或安全交互终端错误，`3` 是登录失败、未登录或登录过期，`4` 是范围拒绝，`5` 是服务不可用或限流，`6` 是响应契约不匹配或内部错误。退出码为 `0` 才表示本次命令成功；成功也只代表该次只读查询完成，不代表拥有额外权限。`INTERACTIVE_REQUIRED` 不可通过自动重试或改用明文输入解决，只能切换到真正的 TTY 或浏览器回退。

限流与系统故障的语义不同：限流应等待或由人工决定稍后重试；系统错误应报告故障，不能自行切换账号、跨门店扩展查询或用旧数据填充。无论哪种错误，都不得伪造、补全或跨门店重试。

## 输出原则

只陈述命令实际返回的数据、日期范围和门店范围；无法取得数据时明确说明原因。不要把零数据解释为业务不存在，也不要从未返回的字段推导事实。需要了解参数、输出契约或支持范围时，重新执行 `dydata commands --json`，并以其返回内容为准。
