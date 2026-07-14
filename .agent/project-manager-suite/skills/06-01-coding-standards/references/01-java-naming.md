# Java 命名与常量规范

> 来源：阿里巴巴 Java 开发手册 §1.1 命名风格 + §1.2 常量定义
> 适用：编写 Java 类、方法、变量、常量时

---

## 命名风格

1. 【强制】命名不以下划线或美元符号开始/结束。
2. 【强制】禁止拼音与英文混合命名，禁止中文命名。
3. 【强制】类名使用 **UpperCamelCase**，以下例外：DO / BO / DTO / VO / AO。
   - 正例：`UserDO`、`OrderServiceImpl`
   - 反例：`UserDo`、`XMLService`
4. 【强制】方法名、参数名、成员变量、局部变量统一 **lowerCamelCase**。
5. 【强制】常量全大写，下划线分隔：`MAX_STOCK_COUNT`。
6. 【强制】抽象类用 `Abstract` 或 `Base` 开头；异常类用 `Exception` 结尾；测试类用被测类名 + `Test`。
7. 【强制】布尔属性**不加 `is` 前缀**（框架序列化会出错）。
   - 反例：`Boolean isDeleted` → 方法 `isDeleted()`，框架误认属性名为 `deleted`
8. 【强制】包名全小写，单数形式：`com.primetrace.toc.service`。
9. 【推荐】命名使用完整单词组合，杜绝不规范缩写。
10. 【推荐】设计模式体现在命名中：`OrderFactory`、`LoginProxy`。

## Service / DAO 接口与实现

11. 【强制】Service 接口 + `Impl` 后缀实现类：`BasicInfoService` → `BasicInfoServiceImpl`。
12. 【推荐】枚举类名带 `Enum` 后缀，成员全大写：`ProcessStatusEnum.SUCCESS`。

## 方法命名前缀

| 操作 | 前缀 | 示例 |
|------|------|------|
| 获取单个对象 | `get` | `getOrderById()` |
| 获取多个对象 | `list` | `listOrdersByVin()` |
| 获取统计值 | `count` | `countActiveOrders()` |
| 插入 | `save` / `insert` | `saveOrder()` |
| 删除 | `remove` / `delete` | `removeExpiredCache()` |
| 修改 | `update` | `updateStatus()` |

## 领域模型命名

| 类型 | 后缀 | 用途 |
|------|------|------|
| 数据对象 | `xxxDO` | 与数据库表一一对应 |
| 数据传输对象 | `xxxDTO` | Service 向外传输 |
| 展示对象 | `xxxVO` | Controller 返回给前端 |
| 查询对象 | `xxxQuery` | 超过 2 个参数的查询封装 |

> 禁止命名为 `xxxPOJO`。

## 常量定义

13. 【强制】禁止魔法值直接出现在代码中，必须定义为常量。
14. 【强制】`long` 赋值用大写 `L`：`Long a = 2L;`（小写 `l` 易与 `1` 混淆）。
15. 【推荐】常量按功能分类，不用一个大类维护所有常量：`CacheConsts`、`ConfigConsts`。
16. 【推荐】有限范围且含延伸属性的值，定义为枚举类。
