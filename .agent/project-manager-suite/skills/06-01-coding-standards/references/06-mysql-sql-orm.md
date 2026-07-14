# SQL 语句与 ORM 映射规范

> 来源：阿里巴巴 Java 开发手册 §5.3 SQL 语句 + §5.4 ORM 映射
> 适用：编写 SQL、MyBatis Mapper、数据访问层

---

## SQL 语句

1. 【强制】禁止 `SELECT *`，需要哪些字段明确写出。
2. 【强制】`count(*)` 是标准统计行数语法，不要用 `count(列名)` 替代（会忽略 NULL 行）。
3. 【强制】`SUM()` 注意 NPE：全 NULL 时返回 NULL，用 `IFNULL(SUM(col), 0)` 兜底。
4. 【强制】判断 NULL 用 `ISNULL()` 函数，不用 `= NULL`（永远返回 NULL）。
5. 【强制】分页查询先判 `count`，为 0 直接返回，不执行后续分页 SQL。
6. 【强制】**禁止外键与级联**（与建表规约一致）。
7. 【强制】**禁止存储过程**（难调试、无移植性）。
8. 【强制】数据订正时，先 `SELECT` 确认再执行 `UPDATE/DELETE`。
9. 【推荐】`IN` 集合元素控制在 1000 个以内。
10. 【参考】字符存储用 `utf8mb4`（支持表情符号）。

---

## ORM 映射（MyBatis Plus）

11. 【强制】查询不用 `SELECT *`，`resultMap` 明确映射字段。
12. 【强制】POJO 布尔属性**不加 `is`**，数据库字段**加 `is_`**，在 `resultMap` 中做映射。
    ```xml
    <result column="is_active" property="active" />
    ```
13. 【强制】SQL 参数用 `#{}`，禁止 `${}`（防 SQL 注入）。
14. 【强制】更新记录时必须**同时更新 `gmt_modified`** 为当前时间。
15. 【强制】禁止用 `HashMap` 作为查询结果集输出。
16. 【推荐】不要写大而全的更新接口，只更新有改动的字段。
17. 【参考】`@Transactional` 不要滥用，考虑缓存回滚、搜索引擎回滚等方案。

---

## 本项目特别说明

- ORM 框架：**MyBatis Plus**，优先使用 LambdaQueryWrapper / LambdaUpdateWrapper。
- 数据库字段风格 `snake_case` ↔ Java 属性 `camelCase`，通过 MyBatis Plus 的 `@TableField` 或全局配置 `map-underscore-to-camel-case: true` 自动映射。
