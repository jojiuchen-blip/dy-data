# OOP 与集合规约

> 来源：阿里巴巴 Java 开发手册 §1.4 OOP 规约 + §1.5 集合处理 + §1.6 并发处理
> 适用：Java 面向对象设计、集合操作、多线程

---

## OOP 规约

1. 【强制】所有覆写方法必须加 `@Override`。
2. 【强制】`equals` 用常量或确定有值的对象调用：`"test".equals(object)`，推荐 `Objects.equals()`。
3. 【强制】包装类对象值比较一律用 `equals`，不用 `==`。
4. 【强制】POJO 属性必须使用**包装数据类型**（`Integer` 而非 `int`）。
5. 【强制】POJO 类**不设任何属性默认值**。
6. 【强制】构造方法禁止加入业务逻辑，初始化逻辑放 `init` 方法。
7. 【强制】POJO 类必须写 `toString` 方法。
8. 【推荐】类内方法顺序：公有/保护方法 → 私有方法 → getter/setter。
9. 【推荐】getter/setter 中不要增加业务逻辑。
10. 【推荐】循环体内字符串拼接用 `StringBuilder.append()`。
11. 【推荐】类成员与方法访问控制从严：能 `private` 就不 `protected`，能 `protected` 就不 `public`。

## 集合处理

12. 【强制】重写 `equals` 就必须重写 `hashCode`。
13. 【强制】`foreach` 循环内禁止 `remove/add`，用 `Iterator` 方式。
14. 【强制】`Comparator` 必须处理相等情况（返回 0），否则排序抛异常。
15. 【推荐】集合初始化时指定大小：`new HashMap<>(16)`。
16. 【推荐】遍历 Map 用 `entrySet`（JDK8 用 `Map.forEach`），不用 `keySet`。
17. 【参考】利用 `Set` 去重，避免 `List.contains()` 遍历对比。

## 并发处理

18. 【强制】线程资源必须通过**线程池**提供，禁止手动创建线程。
19. 【强制】线程池用 `ThreadPoolExecutor` 创建，禁止用 `Executors`（可能 OOM）。
20. 【强制】线程/线程池指定有意义的名称，便于排查。
21. 【强制】`SimpleDateFormat` 线程不安全，用 JDK8 的 `DateTimeFormatter`。
22. 【强制】多个资源加锁时保持一致的加锁顺序，防止死锁。
23. 【推荐】高并发时优先无锁结构；能锁区块就不锁整个方法。

## 控制语句

24. 【强制】`switch` 每个 `case` 必须 `break/return`，必须包含 `default`。
25. 【强制】`if/else/for/while` 必须使用大括号，即使只有一行。
26. 【推荐】`if-else` 不超过 3 层，超过用卫语句或策略模式重构。
27. 【推荐】复杂条件判断结果赋值给有意义的布尔变量名。
