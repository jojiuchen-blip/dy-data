# Python 工程结构与异常日志规范

> 来源：PEP 8 + Google Python Style Guide §2.4 Exceptions / §3.10.1 Logging + 通用 Python 工程实践
> 适用：Python 项目的异常设计、日志输出、项目分层与依赖管理

---

## 异常处理

1. 【强制】禁止裸 `except:`，必须指明异常类型。
   ```python
   # 正例
   try:
       response = client.get(url)
   except requests.ConnectionError as e:
       logger.error("连接失败: url=%s, %s", url, e)
       raise

   # 反例
   try:
       response = client.get(url)
   except:
       pass
   ```
2. 【强制】禁止 `except Exception` 后静默吞掉异常（不处理也不重抛）。
3. 【强制】自定义业务异常必须继承 `Exception`（非 `BaseException`），且以 `Error` 结尾：
   ```python
   class OrderNotFoundError(Exception):
       """订单不存在时抛出。"""

       def __init__(self, order_id: str) -> None:
           self.order_id = order_id
           super().__init__(f"订单不存在: {order_id}")
   ```
4. 【强制】`try` 块中只包含可能抛出异常的最小代码段，不要将大段逻辑包在 try 里。
5. 【强制】需要清理资源（文件、连接）时，使用 `with` 语句（上下文管理器），不用 `try/finally`：
   ```python
   # 正例
   with open(filepath, "r", encoding="utf-8") as f:
       data = f.read()

   # 反例
   f = open(filepath, "r")
   try:
       data = f.read()
   finally:
       f.close()
   ```
6. 【推荐】使用 `raise ... from e` 保留异常链：
   ```python
   try:
       result = parse_config(raw)
   except json.JSONDecodeError as e:
       raise ConfigError(f"配置文件格式错误: {filepath}") from e
   ```
7. 【推荐】对外 API 接口层统一捕获异常，转为错误码 + 友好提示；内部模块间使用异常传递。

---

## 日志规范

8. 【强制】使用标准库 `logging` 模块，不用 `print()` 输出调试信息。
   ```python
   import logging

   logger = logging.getLogger(__name__)
   ```
9. 【强制】日志使用 `%s` 占位符（惰性求值），不用 f-string 拼接：
   ```python
   # 正例 — 仅在日志级别启用时才会格式化
   logger.info("处理订单: order_id=%s, user=%s", order_id, user_name)

   # 反例 — 即使日志级别关闭，f-string 也会执行格式化
   logger.info(f"处理订单: order_id={order_id}, user={user_name}")
   ```
10. 【强制】异常日志必须包含上下文信息 + 异常堆栈：
    ```python
    try:
        process_order(order)
    except Exception:
        logger.exception("订单处理失败: order_id=%s", order.id)
    ```
    > `logger.exception()` 自动附加堆栈，等效于 `logger.error(..., exc_info=True)`。

11. 【推荐】日志级别使用规则：

    | 级别 | 使用场景 |
    |------|---------|
    | `DEBUG` | 开发调试、变量值追踪（生产环境关闭） |
    | `INFO` | 关键业务流程节点（启动、完成、状态变化） |
    | `WARNING` | 用户输入错误、可恢复的降级情况 |
    | `ERROR` | 系统逻辑错误、外部服务异常 |
    | `CRITICAL` | 系统级致命错误，需要立即告警 |

12. 【推荐】生产环境日志级别不低于 `INFO`，禁止 `DEBUG`。

---

## 项目结构

13. 【强制】Python 项目推荐使用以下目录结构：
    ```text
    project-root/
    ├── pyproject.toml          # 项目元数据与工具配置（统一入口）
    ├── README.md
    ├── src/
    │   └── project_name/       # 源码包（使用 src layout）
    │       ├── __init__.py
    │       ├── main.py          # 入口
    │       ├── config.py        # 配置管理
    │       ├── models/          # 数据模型（Pydantic / dataclass）
    │       ├── services/        # 业务逻辑层
    │       ├── repositories/    # 数据访问层
    │       ├── api/             # API 路由层（FastAPI / Flask）
    │       ├── exceptions.py    # 自定义异常集中定义
    │       └── utils/           # 工具函数
    ├── tests/
    │   ├── conftest.py
    │   ├── test_services/
    │   └── test_api/
    └── scripts/                 # 运维脚本、一次性脚本
    ```

14. 【强制】使用 `src/` layout（即源码放在 `src/package_name/` 下），防止直接从项目根目录意外导入。
15. 【强制】自定义异常集中在 `exceptions.py`（或 `errors.py`）中定义，不分散在各业务模块里。
16. 【推荐】按"业务模块"而非"技术层"组织子包。当项目规模增长时：
    ```text
    src/project_name/
    ├── orders/
    │   ├── service.py
    │   ├── repository.py
    │   ├── models.py
    │   └── api.py
    └── users/
        ├── service.py
        ├── repository.py
        ├── models.py
        └── api.py
    ```

---

## 依赖管理

17. 【强制】使用 `pyproject.toml` 作为项目配置的唯一入口。不再新建 `setup.py`、`setup.cfg`。
18. 【强制】锁定生产依赖版本范围，开发依赖放在 `[project.optional-dependencies]` 中：
    ```toml
    [project]
    dependencies = [
        "fastapi>=0.100,<1.0",
        "pydantic>=2.0,<3.0",
    ]

    [project.optional-dependencies]
    dev = [
        "pytest>=7.0",
        "ruff>=0.4",
    ]
    ```
19. 【强制】工具链配置统一写在 `pyproject.toml`，不新建 `.flake8`、`mypy.ini` 等独立文件：
    ```toml
    [tool.ruff]
    line-length = 120
    target-version = "py311"

    [tool.ruff.lint]
    select = ["E", "F", "W", "I", "N", "UP", "B", "A", "SIM"]

    [tool.ruff.format]
    quote-style = "double"

    [tool.pytest.ini_options]
    testpaths = ["tests"]
    ```
20. 【推荐】使用虚拟环境隔离项目依赖，推荐 `uv` 或 `venv`。
21. 【参考】对于需要精确锁版本的生产部署，配合使用 `uv lock` 或 `pip-compile` 生成锁文件。
