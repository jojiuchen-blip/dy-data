# Python 命名风格与文档规范

> 来源：PEP 8 + Google Python Style Guide §3.16 Naming / §3.8 Docstrings / §2.2 Imports / §3.19 Type Annotations
> 适用：编写 Python 模块、类、函数、变量、常量时

---

## 命名风格

1. 【强制】模块名全小写，可用下划线：`data_loader.py`、`utils.py`。
2. 【强制】类名使用 **PascalCase**：`OrderProcessor`、`HttpClient`。
   - 异常类以 `Error` 结尾：`OrderNotFoundError`
3. 【强制】函数名、方法名、变量名使用 **snake_case**：`get_order_by_id()`、`total_count`。
4. 【强制】常量全大写，下划线分隔：`MAX_RETRY_COUNT = 3`、`DEFAULT_TIMEOUT = 30`。
5. 【强制】"内部使用"的名称用单下划线前缀：`_internal_cache`、`_validate_input()`。
6. 【强制】禁止使用双下划线前缀进行名称修饰（name mangling），除非确实需要避免子类属性冲突。
7. 【强制】禁止使用单字符变量名（`l`、`O`、`I`），循环变量 `i`、`j`、`k` 及推导式中的 `x` 除外。
8. 【推荐】布尔变量和返回布尔值的函数使用 `is_`、`has_`、`can_` 前缀：`is_valid`、`has_access()`。
9. 【推荐】命名使用完整单词，杜绝不规范缩写。`num` → `number`，`cnt` → `count` 可接受；`proc_mgr` 禁止。

### 方法命名前缀

| 操作 | 前缀 | 示例 |
|------|------|------|
| 获取单个对象 | `get_` | `get_order_by_id()` |
| 获取列表 | `list_` | `list_active_users()` |
| 获取统计值 | `count_` | `count_pending_orders()` |
| 创建 | `create_` | `create_order()` |
| 删除 | `delete_` / `remove_` | `delete_expired_cache()` |
| 更新 | `update_` | `update_status()` |
| 校验 | `validate_` / `check_` | `validate_input()` |
| 转换 | `to_` / `convert_` | `to_dict()`、`convert_to_dto()` |

---

## 导入规范

10. 【强制】导入按以下顺序分组，组间空一行：
    ```python
    # 1. 标准库
    import os
    import sys
    from pathlib import Path

    # 2. 第三方库
    import requests
    from pydantic import BaseModel

    # 3. 本项目模块
    from app.services.order_service import OrderService
    from app.models.order import Order
    ```
11. 【强制】禁止使用通配符导入：`from module import *`。
12. 【强制】禁止在函数或方法内部使用 import，除非为了避免循环导入或延迟加载重型依赖。
13. 【推荐】每个 import 语句只导入一个模块。从同一个包导入多个名称时可用单行：`from os.path import join, exists`。

---

## 类型注解

14. 【强制】所有公开函数和方法必须添加参数和返回值类型注解。
    ```python
    # 正例
    def get_order_by_id(order_id: str) -> Order | None:
        ...

    # 反例
    def get_order_by_id(order_id):
        ...
    ```
15. 【强制】使用 Python 3.10+ 内置语法，不再从 `typing` 导入基础类型：
    - 用 `str | None` 替代 `Optional[str]`
    - 用 `list[str]` 替代 `List[str]`
    - 用 `dict[str, int]` 替代 `Dict[str, int]`
16. 【强制】可变默认参数必须用 `None` 代替：
    ```python
    # 正例
    def process(items: list[str] | None = None) -> None:
        items = items or []

    # 反例 — 可变默认值是经典 Python 陷阱
    def process(items: list[str] = []) -> None:
        ...
    ```
17. 【推荐】内部工具函数（`_` 前缀）可省略类型注解，但鼓励添加。
18. 【推荐】复杂类型使用 `TypeAlias` 提升可读性：
    ```python
    from typing import TypeAlias

    OrderMap: TypeAlias = dict[str, list[Order]]
    ```

---

## Docstring 规范（Google 风格）

19. 【强制】所有公开模块、类、函数必须有 Docstring。
20. 【强制】Docstring 使用三双引号 `"""`，不使用三单引号。
21. 【强制】函数 Docstring 格式：

    ```python
    def fetch_orders(user_id: str, status: str | None = None) -> list[Order]:
        """根据用户 ID 查询订单列表。

        Args:
            user_id: 用户唯一标识。
            status: 可选，按订单状态筛选。默认返回全部状态。

        Returns:
            匹配条件的订单列表，无结果时返回空列表。

        Raises:
            UserNotFoundError: 用户不存在时抛出。
            DatabaseError: 数据库连接异常时抛出。
        """
    ```

22. 【强制】类 Docstring 放在 `class` 语句下一行，描述类的职责：
    ```python
    class OrderService:
        """订单服务层，封装订单的增删改查业务逻辑。

        Attributes:
            repository: 订单数据访问层实例。
            cache_ttl: 缓存过期时间（秒）。
        """
    ```

23. 【强制】单行 Docstring 的三引号在同一行：
    ```python
    def is_valid(self) -> bool:
        """校验订单数据完整性。"""
    ```

24. 【推荐】模块级 Docstring 说明模块的职责和典型用法。
25. 【参考】重写父类方法时，如行为不变可省略 Docstring 或写 `"""See base class."""`。
