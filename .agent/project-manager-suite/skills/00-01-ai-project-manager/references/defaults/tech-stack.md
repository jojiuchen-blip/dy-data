# 默认参考技术栈

## 用途说明

本文件存放 `ai-project-manager` 的默认技术栈参数，用于在涉及技术选型、页面实现、后端开发、数据库设计、部署方案等任务时，作为默认参考输入按需加载。

使用原则：
- 这里存放的是默认参数，不是不可变的硬编码事实
- 宿主项目已有明确技术栈时，以宿主项目权威信息为准
- 宿主项目尚未定栈时，主入口与子能力可引用本文件作为默认建议
- 若默认技术栈发生调整，只改本文件，不在其他协议文件中重复维护副本

> 本套包面向内部 / 本机工具场景，下方默认栈以"单端 Web 应用"为参考起点；如果项目是单机桌面工具、纯脚本或独立 CLI，按"轻量栈"段引用即可。

## Web 工具前端（示例）
1. 载体：Web
2. 框架：Vue 3
3. 语言：JavaScript + CSS
4. UI 组件库：Ant Design Vue 4.x
5. 状态管理：Pinia
6. 路由：Vue Router
7. 请求：Axios
8. 打包：Vite

## 后端服务（示例）
1. 框架：Spring Boot 3.1.5
2. 语言：Java 17（项目编译标准，开发环境兼容 17~21）
3. 数据库：MySQL
4. ORM：MyBatis-Plus
5. 缓存：Redis（如确实需要）
6. 工具库：Lombok
7. 构建：Maven

## Python 服务 / 脚本（示例）
1. 语言：Python 3.11+
2. 框架：FastAPI（API 服务） / 无框架（独立脚本）
3. 数据建模：Pydantic v2
4. 依赖管理：pyproject.toml + uv / pip
5. Lint / 格式化：Ruff
6. 测试：pytest
7. 虚拟环境：uv / venv

## 单机 / 轻量栈（示例）

针对本机使用、个人或小团队内部工具，可选用更轻量的栈：

1. **桌面工具**：Tauri（Rust + Web 前端）/ Electron（Node + Web 前端）
2. **本地数据存储**：SQLite / 文件 JSON
3. **快速管理面板**：Python + Streamlit / Gradio
4. **纯命令行 CLI**：Node.js + Commander / Python + Click
5. **本地 Web 工具**：Node.js + SQLite + Express / FastAPI + SQLite

部署形态：本地启动或内网部署即可，不预设公开发布、容器编排或云资源。
