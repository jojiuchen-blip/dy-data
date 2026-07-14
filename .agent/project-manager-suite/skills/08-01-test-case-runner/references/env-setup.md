# 测试环境准备

配置来源分两处，职责明确：
- `application.yml`（项目根目录）：地址、端口、目录等**非敏感配置**
- `.env`（项目根目录）：密码、密钥等**敏感凭证**

不要硬编码任何值。

## 配置文件从哪来

这两个文件**不是流水线上游 skill 的产物**：由测试执行者（或宿主项目维护者）在首次执行测试前，按宿主项目的实际环境在项目根目录手工创建；已存在时直接复用，不要覆盖。可从下面的最小示例复制后填入真实值。

### `application.yml` 最小示例

```yaml
urls:
  api-base: http://127.0.0.1:8080   # API 基础地址，按宿主实际填写
  app: http://127.0.0.1:5173        # 系统页面地址，按宿主实际填写
server:
  host: 127.0.0.1                   # 应用服务主机；本地运行填 127.0.0.1
database:
  host: 127.0.0.1                   # 数据库主机
  port: 3306                        # 数据库端口
  name: <数据库名>                   # 按宿主实际填写
```

### `.env` 最小示例

```
DB_USERNAME=<数据库用户名>
DB_PASSWORD=<数据库密码>
# 仅在需要 SSH 隧道连数据库时配置：
SERVER_SSH_PASSWORD=<应用服务主机的 SSH 密码>
```

## 必需的配置项

### 来自 `application.yml`

| 配置路径 | 用途 |
|---------|------|
| `urls.api-base` | API 基础地址 |
| `urls.app` | 系统页面地址 |
| `server.host` | 应用服务主机（本地系统可填 `127.0.0.1`） |
| `database.host` | 数据库主机 |
| `database.port` | 数据库端口 |
| `database.name` | 数据库名 |

### 来自 `.env`

| 变量 | 用途 |
|------|------|
| `DB_USERNAME` | 数据库用户名 |
| `DB_PASSWORD` | 数据库密码 |
| `SERVER_SSH_PASSWORD` | 应用服务 SSH 密码（仅需要远程隧道时配置） |

## 一、读取配置

### 1. 读取 `application.yml`

```python
import yaml

with open('application.yml') as f:
    config = yaml.safe_load(f)

# 示例：config['urls']['api-base'], config['database']['host']
```

> 若 `pyyaml` 未安装：`pip install pyyaml`

### 2. 读取 `.env`（仅密码）

不要用 `source .env`（特殊字符会导致 shell 解析错误），用 Python 读取：

```python
import re

env_vars = {}
with open('.env') as f:
    for line in f:
        m = re.match(r'^([A-Z_][A-Z0-9_]*)=(.+)$', line.strip())
        if m:
            env_vars[m.group(1)] = m.group(2)
```

### 3. 组合使用

```python
# 地址从 yml
api_base = config['urls']['api-base']
app_url = config['urls']['app']
server_host = config.get('server', {}).get('host', '127.0.0.1')
db_host = config['database']['host']
db_port = config['database']['port']
db_name = config['database']['name']

# 密码从 .env
db_user = env_vars['DB_USERNAME']
db_pass = env_vars['DB_PASSWORD']
ssh_pass = env_vars.get('SERVER_SSH_PASSWORD')
```

## 二、API 验证

从 `foundation-api-<slug>.md`（foundation-builder 产出的 API 清单，位于 `<host>/docs/prd/foundation/`）中任选一个已知可用的 GET 接口做连通性检查；该接口需要参数时按 foundation-api 里的示例带上：

```bash
curl -s -o /dev/null -w "%{http_code}" "${API_BASE_URL}<从 foundation-api 选定的 GET 接口路径>"
# 应返回 200，表示应用服务可达；404/5xx 或连接失败都算未通过
```

其中 `${API_BASE_URL}` 替换为从 `application.yml` 的 `urls.api-base` 读到的实际值。宿主没有 foundation-api 文档时，向用户要一个已知可用的 GET 接口，不要凭空猜路径。

## 三、数据库连接

### 策略：先直连，需要时再走 SSH 隧道

**尝试 1：pymysql 直连**

```python
import pymysql

conn = pymysql.connect(
    host=db_host,
    port=int(db_port),
    user=db_user,
    password=db_pass,
    database=db_name
)
```

如果成功，记住"直连模式"，后续所有 SQL 操作都用直连，跳过隧道。

**尝试 2：直连失败且存在远程主机 → SSH 隧道**

直连失败如果是网络隔离或 IP 白名单限制，可通过 SSH 隧道让流量经过可访问数据库的应用服务主机中转。若系统完全在本机运行，不需要建立隧道：

```bash
expect -c "
spawn ssh -o StrictHostKeyChecking=no -f -N -L 3307:${db_host}:${db_port} root@${server_host}
expect \"password:\"
send \"${ssh_pass}\r\"
expect eof
"
```

其中变量分别来自 `application.yml`（host/port/server.host）和 `.env`（password）。

隧道建立后，pymysql 连本地转发端口：

```python
conn = pymysql.connect(
    host='127.0.0.1',
    port=3307,  # 本地转发端口，固定 3307
    user=db_user,
    password=db_pass,
    database=db_name
)
```

### 验证连接

```python
cur = conn.cursor()
cur.execute('SELECT 1')
assert cur.fetchone() == (1,)
conn.close()
```

### 执行 SQL

```python
conn = pymysql.connect(...)  # 用上面确定的连接方式
cur = conn.cursor()
for stmt in sql_content.split(';'):
    stmt = stmt.strip()
    if stmt:
        cur.execute(stmt)
conn.commit()
conn.close()
```

## 四、隧道管理（仅走隧道时适用）

- 隧道在整个测试会话期间保持打开，不需要每条用例重建
- 检查隧道是否存活：`lsof -i :3307`
- 隧道断开则重新建立
- 关闭隧道：`kill $(lsof -t -i :3307)`

## 五、常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| pymysql 直连 Access Denied | 数据库有 IP 白名单 | 走 SSH 隧道 |
| mysql CLI "using password: NO" | MySQL 9.x 移除了 `mysql_native_password` | 用 pymysql 代替 mysql CLI |
| `source .env` 报错 | 特殊字符导致 shell 解析错误 | 用 Python 读取 |
| SSH 连接超时 | 网络问题或密码变更 | 检查 `application.yml` 中 server.host 和 `.env` 中 SERVER_SSH_PASSWORD |
| `yaml` 模块未找到 | pyyaml 未安装 | `pip install pyyaml` |
