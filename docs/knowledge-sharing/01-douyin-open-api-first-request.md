# 从零跑通抖音开放平台 API：准备、Token 与第一次请求

> 适合谁：第一次接触抖音开放平台 API 的产品、运营和初级开发。
>
> 读完能做什么：分清应用凭证和账号信息，获取一次 Token，完成一次小范围请求，并判断结果是否成功。

第一次接开放平台时，最容易卡住的地方通常不是代码，而是四样东西没对齐：应用、权限、账号和 Token。少一个，请求都可能失败。

这篇只完成一件事：让第一次请求成功。批量采集、完整分页和定时任务不在这里展开。

## 先看全流程

```mermaid
flowchart LR
    A["准备应用与账号信息"] --> B["请求 client_token"]
    B --> C["检查 Token 返回"]
    C --> D["携带 Token 请求业务接口"]
    D --> E["检查状态、错误码与数据"]
    E --> F["保存脱敏验证记录"]
```

## 第一次调用前，需要准备什么

先确认下面四项。不要等写完代码再补权限。

- 已完成抖音开放平台机构入驻，并创建应用。
- 应用详情中可以查看 Client Key 和 Client Secret。
- 应用已经申请目标接口需要的权限。生活服务能力与开发者类型、应用资质有关，不是创建应用后自动拥有。
- 已拿到要查询的生活服务账户标识。本文用 `account_id` 表示，本项目会把它放进账户级请求头。

抖音官方接入说明把开发者分为自研开发者、系统服务商等类型，不同类型可申请的权限不同。先根据业务选择类型，再申请应用和权限，通常比遇到“无权限”后倒查更省时间。

> 截图建议：开放平台应用详情中的凭证与权限区域；发布前遮盖全部真实值。

## 四个容易混淆的字段

| 字段 | 它是什么 | 用在哪里 | 能否公开 |
| --- | --- | --- | --- |
| `app_id` | 本项目对应用 Client Key 的命名 | 获取 Token 时作为 `client_key` | 不建议公开 |
| `app_secret` | 应用密钥，也就是 Client Secret | 获取 Token 时证明应用身份 | 绝对不能公开 |
| `account_id` | 要访问的生活服务账户标识 | 业务参数或账户级请求头 | 按内部业务标识保护 |
| `access_token` | 接口调用凭证 | 放在业务请求的 `access-token` 请求头 | 绝对不能公开 |

这里还有一个命名细节。抖音 Token 文档把返回凭证称为 `client_access_token`，响应样例中的字段名是 `access_token`。本项目内部统一把取到的值叫作 Token。不要只看变量名判断它是否需要用户授权，应回到具体接口文档确认。

## 第一步：安全保存应用凭证

不要把真实凭证直接写进代码、聊天记录或知识库。开发环境可以使用环境变量：

```text
DOUYIN_APP_ID=APP_ID_EXAMPLE
DOUYIN_APP_SECRET=APP_SECRET_EXAMPLE
DOUYIN_ACCOUNT_ID=ACCOUNT_ID_EXAMPLE
```

上面的值都是教学用假值。实际项目应通过环境变量、密钥管理服务或服务器上的未跟踪配置文件注入。日志里也不要打印完整请求头和响应。

## 第二步：获取 client_token

抖音开放平台当前文档给出的地址是：

```text
POST https://open.douyin.com/oauth/client_token/
```

官方页面写明请求头为 `multipart/form-data`，并说明 Token 的有效时间为 2 小时；重复获取会让上一个 Token 失效，但有 5 分钟缓冲。

本项目已经封装了这一步：

```python
from src.dy_data.douyin_client import DouyinClient, DouyinCredentials

credentials = DouyinCredentials(
    app_id="APP_ID_EXAMPLE",
    app_secret="APP_SECRET_EXAMPLE",
    account_id="ACCOUNT_ID_EXAMPLE",
)
client = DouyinClient(credentials)
token = client.get_client_token()
```

项目客户端会发送 `client_key`、`client_secret` 和 `grant_type`，并从响应中读取 Token。它当前使用 JSON 请求体，这与官方页面展示的 `multipart/form-data` 不同。

两者不要混着抄：

- 在本项目里，优先调用已经测试过的客户端封装。
- 在新项目里，按抖音开放平台当前接口文档和控制台示例接入。
- 平台升级后，先在测试环境验证请求格式，再调整封装。

一个脱敏后的成功响应大致如下：

```json
{
  "data": {
    "access_token": "TOKEN_EXAMPLE",
    "description": "",
    "error_code": "0",
    "expires_in": "7200"
  },
  "message": "<nil>"
}
```

先看 `error_code`，再读取 Token。不要因为 HTTP 返回 200 就直接认为认证成功。

## 第三步：携带 Token 发起业务请求

生活服务接口除了 Token，往往还需要账户信息。本项目统一生成下面两个请求头：

```text
access-token: TOKEN_EXAMPLE
Rpc-Transit-Life-Account: ACCOUNT_ID_EXAMPLE
```

下面用本项目已接入的门店查询做示意：

```python
result = client.query_shop_pois(relation_type=0)
print(result)
```

这是“本项目实践”，不代表每个抖音应用都默认拥有门店查询权限。换成订单、核销或线索接口时，还要核对对应权限、必填参数和账户归属。

第一次请求建议把范围压小：只查一个账户、一个短时间段或少量记录。目标是确认链路跑通，不是第一天就把所有历史数据拉完。

## 怎样判断接口真的跑通了

按三层检查，少看一层都可能误判。

1. HTTP 层：请求是否成功到达平台。`401`、`403` 或 `5xx` 先按网络、认证或平台异常排查。
2. 业务层：响应中的 `error_code` 是否为成功值。抖音通用状态码中，`0` 表示成功，`2100005` 表示参数不合法，`2100007` 表示无权限操作。
3. 数据层：返回里是否有你要的字段和记录。成功但列表为空，可能只是筛选条件下没有数据。

建议保存一份脱敏验证记录：

```text
请求时间：2026-07-28 10:00
应用：APP_ID_EXAMPLE
账户：ACCOUNT_ID_EXAMPLE
接口：门店查询示意
HTTP 状态：200
业务错误码：0
记录数：2
敏感字段：已遮盖
```

## 常见问题

### 提示 client_key 或 client_secret 错误

重新从应用详情复制凭证，检查是否多了空格、是否把别的应用凭证混了进来。不要在群里发完整密钥让别人帮忙看。

### Token 获取成功，业务接口仍提示无权限

Token 只证明应用身份，不会自动赋予业务权限。回到应用详情检查目标能力是否开通，再确认开发者类型和账户授权是否匹配。

### 提示 Token 无效或过期

重新获取 Token，并确认业务请求没有继续使用旧值。频繁重复获取也可能让上一个 Token 提前失效。

### HTTP 200，但没有数据

先看业务错误码，再看账户、时间范围和筛选条件。空列表和请求失败是两回事。

### 日志里出现完整 Token

立即停止传播日志，撤换受影响的凭证，并补上脱敏。当前项目会把已知密钥和 Token 替换为 `[redacted]`，但调用方仍要避免打印原始请求。

## 完成检查表

- [ ] 应用已通过审核，目标接口权限已确认。
- [ ] `app_id`、`app_secret` 和 `account_id` 来自同一套有效配置。
- [ ] 真实凭证没有写进代码、文档或聊天。
- [ ] 已成功获取 Token，并记录有效期。
- [ ] 业务请求携带了 Token 和需要的账户信息。
- [ ] 已分别检查 HTTP 状态、业务错误码和目标数据。
- [ ] 验证记录已经脱敏。

## 进阶实践：在项目中安全复用 Token

Token 有有效期，不要每次业务请求都重新获取。可以在服务端缓存 Token，在到期前刷新；收到明确的 Token 失效错误时再重试一次。缓存和日志都应放在受控环境中。

接下来如果要决定“持续用 API，还是临时从后台导出”，可阅读[《抖音后台有哪些数据获取方式：开放平台 API 与来客后台导出》](./02-douyin-data-acquisition-options.md)。

## 参考资料

- [抖音开放平台：平台入驻](https://open.douyin.com/platform/resource/docs/accession-guide/platform-accession/)
- [抖音开放平台：用户类型及权限说明](https://open.douyin.com/platform/resource/docs/accession-guide/type-and-permission)
- [抖音开放平台：生成 client_token](https://open.douyin.com/platform/resource/docs/openapi/account-permission/client-token/)
- [抖音开放平台：状态码](https://open.douyin.com/platform/resource/docs/develop/common-tools/status-code)
- 本项目实践：`src/dy_data/douyin_client.py`、`src/dy_data/config.py` 和 `docs/runbook.md`
