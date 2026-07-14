# dy-data（抖音经营引擎）

面向汽车经销商集团及门店，统一承载抖音经营数据分析、跨店核销与分账复核、线索分配与跟进、后台运营管理，以及数据采集和生产运行。

系统当前覆盖四个业务域：

- **经营与结算**：销售看板、门店排名、月度结算、订单明细、跨店核销和异常复核。
- **线索运营**：线索总览、订单详情、跟进记录、分配轮次、试运行、总部线索池和门店评分。
- **后台管理**：账号与门店权限、SKU 规则、非佣金归属账号、商品类型可见性、反馈、同步和分配规则。
- **数据平台**：抖音数据采集、FastAPI 服务、PostgreSQL 数据库、React 前端、定时任务、浏览器导出和生产部署。

系统输出经营与分账参考，不执行真实资金划拨。业务边界以 [项目产品介绍书](docs/项目产品介绍书.md) 为准。

## 当前技术形态

- 后端：Python、FastAPI、SQLAlchemy、Alembic、PostgreSQL。
- 前端：React 19、TypeScript、Vite，真实 API 为默认数据源；`VITE_USE_MOCKS=true` 仅用于受控开发场景。
- 任务：独立 worker 执行同步、刷新和浏览器导出任务。
- 部署：Docker Compose 单机生产骨架；GitHub Actions 支持按仓库变量选择部署目标。
- 权限：业务页面需要登录；门店、管理员和超级管理员按角色及门店范围访问数据。

## 先读这些文档

- [项目画像](project-profile.md)：项目身份、当前阶段、范围和治理状态。
- [项目产品介绍书](docs/项目产品介绍书.md)：当前产品定义和业务边界。
- [系统架构](docs/architecture.md)：当前代码结构、服务边界和数据链路。
- [API 契约](docs/api-contract.md)：认证、响应包络和接口分组。
- [运行手册](docs/runbook.md)：生产部署、迁移、运维和恢复。
- [视觉系统](docs/design-system/README.md)：设计令牌、组件和页面视觉规范。
- [文档权威映射](docs/governance/authority-map.md)：现有文档的 authority、evidence、legacy 和 stale 角色。

## 仓库结构

```text
.agent/project-manager-suite/  公司项目治理套包安装态
apps/api/                     FastAPI 应用与业务接口
apps/web/                     React/Vite Web 应用
apps/worker/                  同步、刷新和浏览器任务 worker
alembic/                      PostgreSQL 迁移
deploy/                       Docker Compose、Nginx 与生产部署配置
docs/                         产品、架构、设计、治理和运行文档
scripts/                      导出、结算、诊断、同步和运维脚本
src/dy_data/                  可复用 Python 领域与基础设施代码
tests/                        后端、数据、治理和回归测试
```

`mock/` 与历史脚本仍可提供受控开发或数据核对素材，但不代表当前产品只运行静态 HTML 或模拟数据。

## 本地开发

安装 Python 依赖并运行测试：

```powershell
python -m pip install -r requirements.txt
python -m pytest
```

启动前端：

```powershell
npm --prefix apps/web install
npm --prefix apps/web run dev
```

构建前端：

```powershell
npm --prefix apps/web run build
```

本地配置从 `config.example.json` 复制到不提交的 `config.local.json`。读取优先级为：环境变量 > `DY_DATA_CONFIG` 指向的 JSON > `config.local.json` > 内置默认值。不得提交密钥、数据库 URL、Cookie、浏览器配置、真实导出数据或个人路径。

## 生产部署

`deploy/compose.yaml` 提供 PostgreSQL、API、worker、Web、浏览器和反向代理服务。部署前复制占位配置并替换所有 `CHANGE_ME_*`：

```bash
cp deploy/.env.example deploy/.env
docker compose --env-file deploy/.env -f deploy/compose.yaml config
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
```

完整迁移、健康检查、备份和恢复步骤见 [运行手册](docs/runbook.md)。

## 协作与治理

项目工作从 [AGENTS.md](AGENTS.md) 进入，需求生命周期以 Linear 的 `DYDATA` 团队为准，宿主实现规则位于 [docs/rules](docs/rules/README.md)。`/.worktrees/` 和 `/logs/` 只承载本地工作树与运行日志；可提交的开发过程日志统一写入 `docs/devlog/`。
