# 工程结构与分层模型

> 来源：阿里巴巴 Java 开发手册 §6.1 应用分层 + 通用后端工程实践
> 适用：Java 后端项目在新建类、包、模块时确定归属层与领域模型

---

## 分层架构

```
Controller（Web / API 层）
    ↓ 调用
Service 接口 + ServiceImpl（业务逻辑层）
    ↓ 调用
Mapper / Repository（数据访问层）
    ↓ 访问
数据库 / 外部存储
```

| 层 | 职责 | 命名规范 |
|----|------|---------|
| **Controller** | 参数校验、调用 Service、返回统一响应 | `XxxController` |
| **Service** | 业务逻辑、跨仓储组合、事务管理 | 接口 `XxxService` + 实现 `XxxServiceImpl` |
| **Mapper / Repository** | 数据 CRUD、持久化访问 | `XxxMapper` / `XxxRepository` |

## 包结构建议

推荐按“公共层 + 业务模块”组织，而不是把所有类平铺在一个包下。

```text
com.example.project
├── common/
│   ├── config/
│   ├── exception/
│   ├── response/
│   └── util/
├── module-a/
│   ├── controller/
│   ├── service/
│   ├── service/impl/
│   ├── mapper/
│   ├── entity/
│   ├── dto/
│   └── vo/
└── module-b/
    ├── controller/
    ├── service/
    ├── service/impl/
    ├── mapper/
    ├── entity/
    ├── dto/
    └── vo/
```

1. 【强制】不同业务模块保持清晰边界，禁止跨模块随意直接读写内部实现。
2. 【推荐】先按业务域分模块，再在模块内按分层放置类。
3. 【推荐】公共能力沉淀到 `common/`，避免复制。

---

## 领域模型

| 类型 | 命名 | 对应层 | 用途 |
|------|------|-------|------|
| **DO / Entity** | `XxxDO` / `XxxEntity` | DAO → Service | 与数据库表或持久化模型对应 |
| **DTO** | `XxxDTO` | Service → Controller / 外部调用 | 跨层数据传输 |
| **VO** | `XxxVO` | Controller → 前端 | 前端展示对象 |
| **Query** | `XxxQuery` | Controller → Service | 查询参数封装 |
| **Command** | `XxxCommand` | Controller → Service | 写操作入参封装 |

1. 【强制】禁止用 `Map` 作为长期稳定的跨层输入输出模型。
2. 【强制】禁止命名为 `xxxPOJO`。
3. 【推荐】查询条件超过 2 个参数时，优先封装为 `Query` 或 `Command` 对象。

---

## 分层异常处理

| 层 | 处理方式 |
|----|---------|
| Mapper / Repository | 抛出或包装后抛出，不重复记录日志 |
| Service | 捕获并记录日志，转换为业务异常 |
| Controller | 不泄露堆栈细节，转为统一错误响应 |

1. 【强制】异常处理按层分责，避免每层都打同一份错误日志。
2. 【推荐】统一错误码、统一响应结构、统一异常转换入口。
