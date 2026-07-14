# 异常处理与日志规范

> 来源：阿里巴巴 Java 开发手册 §2.1 异常处理 + §2.2 日志规约
> 适用：编写 try-catch、异常设计、日志输出

---

## 异常处理

1. 【强制】可通过预检查规避的 RuntimeException 不应用 catch 处理。
   - 正例：`if (obj != null) { ... }`
   - 反例：`try { obj.method() } catch (NullPointerException e) { ... }`
2. 【强制】异常不要用来做流程控制或条件控制。
3. 【强制】对大段代码 try-catch 是不负责任的，应区分稳定代码和非稳定代码。
4. 【强制】捕获异常必须处理，不要 catch 后什么都不做。
5. 【强制】事务代码中 catch 后如需回滚，必须手动回滚。
6. 【强制】`finally` 块必须关闭资源（JDK7+ 用 try-with-resources）。
7. 【强制】`finally` 块中禁止 `return`。
8. 【推荐】防止 NPE 的检查清单：
   - 返回包装类型自动拆箱时
   - 数据库查询结果可能为 null
   - 集合 `isNotEmpty` 但元素可能为 null
   - 远程调用返回必须空指针检查
   - 级联调用 `obj.getA().getB()` 易产生 NPE，用 `Optional`
9. 【推荐】自定义业务异常（`ServiceException`），不直接抛 `RuntimeException`。
10. 【参考】对外 HTTP/API 接口用错误码；应用内部推荐抛异常；跨应用 RPC 用 `Result` 包装。

---

## 分层异常处理（本项目适用）

| 层 | 处理方式 |
|----|---------|
| DAO/Mapper | `catch(Exception e)` → 包装为 `DAOException` 抛出，不打日志 |
| Service | 捕获并记录日志（带参数信息），抛 `ServiceException` |
| Controller | 不再往上抛，转为错误响应码 + 友好提示 |

---

## 日志规约

11. 【强制】使用 **SLF4J** 门面 API，不直接用 Log4j/Logback。
    ```java
    import org.slf4j.Logger;
    import org.slf4j.LoggerFactory;
    private static final Logger logger = LoggerFactory.getLogger(Xxx.class);
    ```
12. 【强制】`debug/info` 级别日志使用**占位符**，不用字符串拼接。
    ```java
    logger.debug("Processing order id: {} for vin: {}", orderId, vin);
    ```
13. 【强制】异常日志必须包含案发现场信息 + 异常堆栈。
    ```java
    logger.error("查询订单失败, orderId={}, {}", orderId, e.getMessage(), e);
    ```
14. 【推荐】生产环境禁止 debug 日志，info 日志有选择输出。
15. 【推荐】用户输入参数错误用 `warn`，系统逻辑错误用 `error`。
