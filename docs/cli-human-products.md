# 交互式商品管理 CLI

DYDATA-115 的专用命令 `dydata-products` 随 `apps/cli` 同一 Python 包安装：

```powershell
python -m pip install -e apps/cli
dydata-products manage --product-scope jingcheng --q 保养 --input change.json --audit receipt.json
dydata-products shared-rule --input rule.json --audit shared-receipt.json
dydata-products shared-rule-grants --input maintainers.json --audit maintainer-receipt.json
```

命令仅供本人在交互终端执行。每次显示固定环境及服务地址，由本人输入系统账号，密码通过 `getpass` 隐藏输入；不能关闭回显时停止。命令通过现有 Web 登录接口创建仅存在内存的临时 Cookie，退出时注销并清除，不读取浏览器文件，不保存或获取 CLI/Agent 令牌。没有账号、密码、Cookie、token、URL 或 `--yes` 参数。`DYDATA_ENV` 仅选择包内已登记的环境；不接受任意地址覆盖。

`dydata` 原通用只读命令、凭据、API 白名单和 MCP 工具保持原有契约。`dydata-products` 不进入该注册表，不是 Agent 自主调用能力。商品范围、规则发布、启停和授权均由与后台共用的服务端接口实时验证。没有商品授权的账号无法通过输入 ID 绕过权限。

`manage` 展示搜索结果。输入已展示的商品 ID（逗号分隔）可累计多选，`n`/`p` 翻页，`done` 确认；`all` 选中当前有权限筛选结果的全部分页，`q` 退出。`--page-size` 范围为 1–200，`--product-scope` 可为 `all`、`jingcheng`、`byd`。选择后可发布名单、按字段发布规则、开启、关闭；全范围管理员还可替换商品管理授权。

每项操作逐商品显示服务端 `before`/`after` 预览、失败原因，然后要求本人输入精确的 `PUBLISH N`。全选先在服务端完整筛选预览，实际发布冻结为已预览成功的明确商品 ID，防止确认后扩大范围。失败商品保留原版；可只对失败 ID 重新预览并再次确认。没有输入精确确认语句不发布。预览不创建正式版本，实际发布版本及逐商品结果以服务端回执为准。

发布名单或规则不会自动开启流转。开启还必须由本人填写业务负责人已确认有效名单并明确授权的说明；命令无法替业务负责人作出授权。启停仅影响此后首次入库的线索，已入库未分配及在途线索继续绑定原规则。

开启正式提交同时锁定本人已预览的逐商品名单版本（`expected_list_versions`）。名单在预览后被他人发布新版时，服务端返回 `LIST_VERSION_CHANGED` 并拒绝该商品本次开启；缺少版本确认返回 `PREVIEW_REQUIRED`。重试必须重新获取预览、展示当前名单版本并再次输入 `PUBLISH N`，不能沿用旧确认。关闭商品不要求名单版本。

比亚迪本品首次开启会继承开启当时的精诚养车共享基座；此前不接受独立规则发布，返回 `PRODUCT_NOT_ENABLED`。请先按已确认名单正式开启，再发布独立规则。曾开启后关闭的本品仍可调整独立规则；精诚养车商品可提前配置规则。

`--input` 是不大于 1 MiB 的本地 UTF-8 JSON 文件，只允许当前操作的字段。可省略文件并在终端输入共享名单或规则字段。请勿在文件或命令行放入凭据。

同一名单应用到所选多个商品：

```json
{"store_ids":["store-a","store-b"]}
```

按商品导入不同名单；显式多选时文件商品集须与所选集一致：

```json
{"lists":[{"product_id":"product-a","store_ids":["store-a"]},{"product_id":"product-b","store_ids":["store-b"]}]}
```

按字段变更规则。省略字段保留原值；既支持如下嵌套 `follow_up_policy`，也支持将其字段平铺在 `rules` 内：

```json
{"rules":{"first_follow_up_sla_hours":48,"follow_up_policy":{"appointment_hours":72,"further_follow_up_hours":168,"unreachable_hours":168,"pending_action":"next","appointment_action":"next","further_follow_up_action":"next","unreachable_action":"close"}}}
```

首触期限为 1–168 小时；其他期限为 1–8760 小时；到期动作只可为 `next` 或 `close`。规则输入只包含实际需要变更的字段。`shared-rule` 使用同一规则文件，服务端逐字段合并；要求 `PUBLISH SHARED` 确认。发布精诚养车共享基座供后续本品首次开启复制，不切换已发布商品独立版本或已入库线索。

精诚养车项目组通过独立的共享基座维护授权使用 `shared-rule`；普通账号获此授权后也可预览和发布基座。商品发现接口以 `can_manage_shared_rule` 提示该入口，即使本人没有可管理商品，仍可发现并使用共享基座。共享维护授权不会赋予任何未授权商品的管理权，也不授予维护人或商品管理者的授权分发能力。

全范围管理员使用 `shared-rule-grants` 列出可授权用户、读取当前维护人，输入新的完整 `user_ids` 集合（同下方 JSON 格式），逐项预览前后集合后输入 `AUTHORIZE SHARED` 发布；可增补、移除或以 `[]`/交互输入 `none` 明确清空维护人。其他输入取消且不提交。维护人账号不能读取或分发这组授权；全范围管理员权限仍由服务端逐请求复核。

全范围管理员可选择“替换商品管理授权”，查看服务端返回的可授权用户 ID，再填写目标集合。以下文件对所选每个商品替换全部显式管理者；`[]` 明确清空：

```json
{"user_ids":["user-id-a","user-id-b"]}
```

终端逐商品展示原集合和目标集合，要求 `AUTHORIZE N` 后提交。只有服务器声明 `can_manage_grants` 的全范围管理员可使用；普通商品负责人无法查看或更改授权。无文件时输入 `none` 明确清空，其余输入为用户 ID。

每次命令输出不含凭据的 JSON 审计回执，包含环境、操作者、时间、预览、每商品结果、发布版本和失败 ID。`--audit` 将其保存到**新文件**，拒绝覆盖现有文件。服务端另记录发布人、时间、商品、版本及授权变更。

写请求不自动重试。批量发布携带幂等键；连接中断或响应损坏时回执标为 `unknown`，保留请求编号及幂等键，必须先核对实际商品状态，避免把无回执当作未发布。已得到明确失败结果时，只重试失败项，每轮重新预览并确认。

退出码：成功或确认前取消为 0；存在未解决的逐商品失败为 1；输入/非交互终端为 2；登录/会话为 3；权限为 4；服务连接/限流为 5；契约或内部错误为 6；交互中断为 130。预览与代码测试均不代表生产开启；生产交付默认关闭，正式开启需另有明确业务授权。
