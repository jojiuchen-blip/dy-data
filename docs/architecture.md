# dy-data 当前系统架构

## 1. 架构目标

dy-data 以 PostgreSQL 为数据中心，通过采集与 worker 形成可追溯业务数据，由 FastAPI 提供统一认证与接口，再由 React Web 承载经营、结算、线索和后台管理。生产环境使用容器化服务并只通过反向代理暴露入口。

## 2. 服务组成

```text
Douyin APIs / controlled browser export
                    |
                    v
             worker + scripts
                    |
                    v
               PostgreSQL
               ^         ^
               |         |
           FastAPI     Alembic
               |
               v
          React/Vite Web
               |
               v
        reverse proxy / user
```

- `apps/api/`：创建 FastAPI 应用，注册认证、经营看板、线索、反馈、任务和管理路由。
- `apps/web/`：React 19 + TypeScript + Vite 应用；`AuthGate` 保护业务页面，真实 API 为默认数据源。
- `apps/worker/`：执行抖音采集、结算刷新、线索与评分相关任务，并记录任务状态。
- `src/dy_data/`：配置、抖音客户端、CSV、路径、SKU 等可复用基础代码。
- `alembic/`：数据库 schema 演进。
- `deploy/`：PostgreSQL、迁移、API、worker、Web、Chromium/noVNC 和代理的生产编排。

## 3. 业务边界

### 经营与结算

`dashboard.py` 提供门店排名、佣金规则摘要、月度结算、销售看板和订单明细。聚合结果必须能够追到数据库中的订单与券明细，页面不重新定义分账逻辑。

### 线索运营

`clues.py` 提供筛选、总览、分配轮次、详情、跟进和电话授权读取；管理端在 `admin.py` 提供主池、决策、候选、总部池、轮次、审计、规则、门店组和评分能力。

### 后台管理

`admin.py` 还负责账号、反馈、SKU、非佣金归属账号、商品类型可见性和同步配置。管理能力使用管理员或最高管理员依赖保护。

### 数据平台

认证、门店范围、任务状态、同步、迁移、采集和生产部署构成横向平台能力。开放平台凭据、浏览器状态和真实数据只存在于受控运行环境。

## 4. 数据链路

1. worker 或受控脚本从抖音接口和浏览器导出链路采集数据。
2. 原始数据、门店和账号映射、业务明细、汇总、线索和任务状态进入 PostgreSQL。
3. 业务服务按角色、门店范围、筛选和时间口径读取或修改数据。
4. FastAPI 使用明确 schema 返回 `{ data, definitions?, meta }` 包络。
5. React Web 通过带会话凭据的共享 client 加载数据并呈现状态。
6. 关键写操作通过 API 或数据库回读验证持久化结果。

## 5. 认证与授权

- `/api/v1/auth/*` 负责登录、当前用户、退出、改密、初始化和受控重置。
- 业务接口默认要求当前用户；管理员接口使用更严格角色依赖。
- 门店范围由后端依赖和查询约束执行，前端菜单与路由保护只改善体验。
- `/browser/` 受最高管理员会话保护，不直接暴露 Chromium 或 noVNC 端口。

## 6. 部署与可靠性

- `deploy/compose.yaml` 将数据库、迁移、API、worker、Web、浏览器和代理分离。
- 迁移成功后 API 和 worker 才启动；只有 proxy 发布宿主机端口。
- GitHub Actions 提供不同部署方式，实际目标由仓库变量和 secrets 决定，文档不固化生产标识。
- `job_runs` 等状态用于观察数据任务；详细部署、迁移、备份与恢复见 `docs/runbook.md`。

## 7. 架构事实来源

- 服务与路由：当前代码和依赖。
- 数据结构：Alembic 迁移、SQLAlchemy 模型和目标数据库实际 schema。
- 生产拓扑：`deploy/` 与当前 GitHub Actions workflow。
- 产品范围：`docs/项目产品介绍书.md`。
- 历史架构和计划只能作为 evidence 或 legacy，不能覆盖上述当前事实。
