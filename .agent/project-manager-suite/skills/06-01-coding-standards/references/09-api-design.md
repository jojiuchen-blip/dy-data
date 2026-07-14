# REST API 接口设计规范

> 来源：项目实际技术栈 + 团队约定 + PRD/API 契约收口结果
> 适用：设计新接口、修改已有接口
> 优先级：若通用 REST 习惯与本项目既有契约冲突，以本文件为准

---

## 1. 定位与使用方式

1. 【强制】本文件同时承载两层规则：
   - 通用 REST 设计原则
   - 宿主项目级接口口径
2. 【强制】设计/修改接口时，先按本文件判断：
   - 路径、方法、字段命名、分页、错误码是否符合项目统一规则
   - 当前接口是否属于固定行配置接口、列表接口、聚合接口
3. 【强制】若任务还给出了 PRD/fixtures，则本文件管“怎么设计”，PRD/fixtures 管“这个接口具体该长什么样”。

## 2. 路径规范

1. 【强制】默认接口前缀：`/api/admin/xxx`，如 `/api/admin/items`、`/api/admin/display-config`、`/api/admin/resource-list`。宿主项目可按实际约定使用 `/api/`、`/internal-api/` 等其他前缀，但单项目内统一一种。
2. 【强制】路径全小写，多单词用连字符 `-` 分隔，如 `/api/admin/sync-logs`。
3. 【强制】资源名优先使用名词，禁止动词式路径，如 `/api/admin/getOrders`。
4. 【推荐】集合资源使用复数，如 `/api/admin/orders`；固定语义配置接口可按现有项目口径保留，如 `/api/admin/display-config`。

## 3. HTTP 方法

| 方法 | 语义 | 适用场景 |
|------|------|---------|
| `GET` | 查询 | 获取资源，无副作用 |
| `POST` | 新增 / 触发 | 创建资源、触发任务 |
| `PUT` | 全量更新 | 配置保存、整体替换 |
| `DELETE` | 删除 | 删除单条资源 |

1. 【强制】`GET` 请求禁止修改数据。
2. 【强制】固定行配置表默认只提供 `GET + PUT`，不提供 `POST/DELETE`。
3. 【强制】可增删资源才使用 `POST / PUT / DELETE` 组合。

## 4. 统一响应格式

1. 【强制】所有接口返回统一包装结构：

```json
{
  "code": 0,
  "msg": "success",
  "data": { }
}
```

2. 【强制】项目冻结对象是 `data` 内业务字段；`code/msg` 为统一包装字段。
3. 【强制】项目现阶段成功态允许 `code = 0` 或 `code = 200`，但单个接口不得混用两套字段名。
4. 【强制】本项目统一使用 `msg`，不再新增 `message` 作为标准成功字段。
5. 【强制】错误响应保持相同包装结构，`data` 为 `null` 或空对象。

## 5. 字段契约规则

1. 【强制】请求字段优先定义为：必填 / 非必填。
2. 【强制】响应字段优先定义为：必返 / 可空，避免“字段可能不存在”。
3. 【强制】无数据列表返回 `[]`，不返回 `null`。
4. 【强制】对象字段如业务上存在但暂时无值，返回 `null`，不要省略字段。
5. 【推荐】优先使用“必返 + 可空”或“必返 + 空数组”，减少前端分支判断。

## 6. JSON 与命名风格

1. 【强制】请求参数、响应 JSON 字段统一使用 `camelCase`，如 `itemCount`、`primaryTag`、`pageSize`。
2. 【强制】数据库 `snake_case` 与 JSON `camelCase` 的映射由后端处理，不暴露给前端。
3. 【强制】枚举值使用 `UPPER_SNAKE_CASE`，如 `ACTIVE`、`INACTIVE`。
4. 【允许】层级型枚举/条件键使用点号表达，如 `STATUS.ACTIVE`、`TAG.HIGHLIGHT`。
5. 【推荐】颜色值使用 HEX，如 `#722ED1`；语义色名仅在主题色场景使用，如 `green`、`gold`、`red`。

## 7. 分页约定

1. 【强制】分页请求参数使用 `page` + `pageSize`，不要使用 `size`。
2. 【强制】`page` 从 `1` 开始，`pageSize` 默认 `10`，建议范围 `1~50`。
3. 【强制】分页响应至少包含：

```json
{
  "list": [],
  "total": 0,
  "page": 1,
  "pageSize": 10
}
```

4. 【允许】滚动加载接口额外返回 `hasMore`。
5. 【强制】无数据时直接返回空列表，不因空数据改变结构。

## 8. 错误码与异常

1. 【强制】参数缺失/格式非法使用明确业务错误码，如 `40001`。
2. 【强制】枚举值非法使用独立错误码，如 `40002`。
3. 【强制】资源不存在使用明确错误码，如 `40404`。
4. 【强制】服务内部异常统一经全局异常处理，不在 Controller 中手工拼错误响应。
5. 【推荐】下游失败但主链路可降级时，使用可识别错误码并保留主响应可用性。

## 9. 入参与安全

1. 【强制】Controller 层使用 `@Valid`、`@NotNull`、`@NotBlank` 等做入参校验。
2. 【强制】批量接口需限制单次操作量，避免无边界请求。
3. 【强制】敏感信息按场景脱敏，前端展示手机号等字段时不要直接暴露全量。
4. 【强制】SQL 参数必须绑定，禁止字符串拼接。
5. 【推荐】`POST` 触发类接口考虑幂等性，避免重复提交。

## 10. 项目级配置接口模式

### 10.1 固定行配置

1. 【强制】以下配置接口按“固定行、全量覆盖保存”设计：
   - `/api/admin/display-config`
   - `/api/admin/tag-rules`
   - `/api/admin/primary-tags`
   - `/api/admin/detail-actions`
   - `/api/admin/text-config`
   - `/api/admin/theme-config`
2. 【强制】固定行配置用 `GET/PUT`，`PUT` 请求体传完整数组或完整配置对象。
3. 【强制】固定行配置不提供创建、删除路由。

### 10.2 可增删配置

1. 【强制】以下接口按可增删资源设计：
   - `/api/admin/action-rules`
   - `/api/admin/resource-benefits`
2. 【强制】这类接口可使用 `POST / PUT / DELETE`。

### 10.3 阈值嵌入

1. 【强制】全局阈值就近挂载到最相关的配置接口，不单独新建阈值接口。
2. 【强制】当前项目口径：
   - `dueDays` / `dueCount` 嵌入 `display-config`
   - `highlightThreshold` 嵌入 `tag-rules`

## 11. 示例接口清单

### 11.1 配置接口

- `GET/PUT /api/admin/display-config`
- `GET/PUT /api/admin/tag-rules`
- `GET/PUT /api/admin/action-rules`
- `GET/PUT /api/admin/text-config`
- `GET/PUT /api/admin/theme-config`
- `GET/PUT /api/admin/primary-tags`
- `CRUD /api/admin/resource-benefits`
- `GET/PUT /api/admin/detail-actions`

### 11.2 数据接口

- `GET /api/admin/resource-list`
- `GET /api/admin/resource-detail`
- `GET /api/admin/sync-logs`
- `POST /api/admin/sync/trigger`

## 12. 实施提醒

1. 【强制】若你改了路径、分页参数、响应包装、字段命名，必须同步检查前端调用、测试、PRD、fixtures。
2. 【强制】若项目已有 PRD fixtures、接口总览文档或前端子项目 API 文档，修改接口时要核对是否需要同步更新。
3. 【推荐】新增接口前，先判断能否复用既有资源命名和现有配置接口模式，避免继续扩散风格。

## 13. Swagger 接口文档注解规范

> 适用：项目使用 Swagger / springdoc-openapi / knife4j 自动生成接口文档的场景
> 目标：让 Swagger UI 页面成为可直接使用的前后端协作文档，减少口头沟通

### 13.1 Controller 层注解

1. 【强制】每个 Controller 类必须加 `@Tag(name = "模块名")`，用于 Swagger UI 分组展示。

    ```java
    @Tag(name = "设备管理")
    @RestController
    @RequestMapping("/api/admin/devices")
    public class DeviceController { ... }
    ```

2. 【强制】每个接口方法必须加 `@Operation(summary = "一句话描述")`，禁止留空或使用方法名充当描述。

    ```java
    // ✅ 正确
    @Operation(summary = "根据条件分页查询设备列表")
    @GetMapping
    public Result<PageResult<DeviceVO>> listDevices(DeviceQuery query) { ... }

    // ❌ 错误 — 无注解或描述为空
    @GetMapping
    public Result<PageResult<DeviceVO>> listDevices(DeviceQuery query) { ... }
    ```

3. 【推荐】涉及多种响应状态的接口，使用 `@ApiResponse` 补充说明非 200 场景。

    ```java
    @Operation(summary = "删除设备")
    @ApiResponse(responseCode = "200", description = "删除成功")
    @ApiResponse(responseCode = "404", description = "设备不存在")
    @DeleteMapping("/{id}")
    public Result<Void> deleteDevice(@PathVariable Long id) { ... }
    ```

### 13.2 DTO / VO 字段注解

4. 【强制】所有 DTO、VO、Query 对象的字段必须加 `@Schema(description = "字段说明")`，禁止留空。

    ```java
    public class DeviceVO {
        @Schema(description = "设备唯一编码")
        private String deviceCode;

        @Schema(description = "设备状态：ONLINE-在线，OFFLINE-离线，FAULT-故障")
        private String status;

        @Schema(description = "最近一次上报时间，格式 yyyy-MM-dd HH:mm:ss")
        private String lastReportTime;
    }
    ```

5. 【强制】必填字段必须标注 `requiredMode = Schema.RequiredMode.REQUIRED`。

    ```java
    @Schema(description = "设备编码，新增时必填", requiredMode = Schema.RequiredMode.REQUIRED)
    private String deviceCode;
    ```

6. 【推荐】关键字段加 `example` 属性，为前端提供示例值参考。

    ```java
    @Schema(description = "设备编码", example = "DEV-2026-001")
    private String deviceCode;

    @Schema(description = "页码，从 1 开始", example = "1")
    private Integer page;
    ```

### 13.3 枚举与取值范围

7. 【强制】枚举类型字段必须在 `description` 中列出所有可选值及含义，格式为 `值-含义`，用逗号或中文顿号分隔。

    ```java
    // ✅ 正确 — 可选值自包含
    @Schema(description = "操作类型：CREATE-新增，UPDATE-修改，DELETE-删除")
    private String actionType;

    // ❌ 错误 — 只写了字段名
    @Schema(description = "操作类型")
    private String actionType;
    ```

8. 【推荐】数值范围字段在 `description` 中说明边界。

    ```java
    @Schema(description = "每页条数，范围 1~50，默认 10", example = "10")
    private Integer pageSize;
    ```

### 13.4 注意事项

9. 【强制】Swagger 注解中的描述文本与接口实际行为必须一致；接口变更时同步更新注解，不要留过期描述。
10. 【强制】禁止使用已废弃的 Swagger 2.x 注解（如 `@ApiOperation`、`@ApiModel`、`@ApiModelProperty`），统一使用 OpenAPI 3 注解（`@Operation`、`@Schema`、`@Tag`）。如项目仍在 Swagger 2.x，应计划迁移。
11. 【推荐】按业务域使用不同的 `@Tag` 分组，保持 Swagger UI 页面清晰。
