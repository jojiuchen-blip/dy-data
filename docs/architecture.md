# 架构整理说明

## 当前主线

当前仓库主线是经销商抖音订单分账数据看板，不再承载此前独立推进的抖音服务产品销售数据看板和每日发布流程。

已迁出的内容归档在：

```text
C:\Users\86138\Documents\抖音服务产品数据拉取归档
```

## 主线边界

- 保留订单、核销、退款、抖音号、门店 POI 和职人绑定相关采集及匹配脚本。
- 保留 SKU 到商品类型映射，因为分账看板仍按商品类型展示和筛选。
- 保留分账基础表、分账看板、异常诊断和数据可用性校验脚本。
- 迁出销售核销看板、每日销售看板工作流、COS 上传和原项目产品介绍书。

## 目标方向

后续架构建议分三层推进：

1. 采集层：订单、核销、退款、职人绑定信息由稳定任务采集。
2. 数据层：分账基础表作为当前可复核交付物，后续可沉淀到云数据库或多维表格。
3. 服务层：分账看板先保留静态 HTML，后续再拆分为后端 API 和前端页面。

技术栈、生产数据链路和云服务器部署方向见 `docs/技术架构与部署规划.md`。生产数据采集不能依赖开发者个人电脑或 Codex 定时执行，应迁移为服务器上的稳定任务。

## 后续目录目标

```text
apps/
  web/
  api/
  worker/
scripts/
  exports/
  settlement/
  diagnostics/
  exploration/
  utilities/
  tasks/
src/
  dy_data/
deploy/
docs/
tests/
```

当前已先完成脚本层整理：根目录历史脚本按用途迁入 `scripts/`，并保留 `src/dy_data` 作为共享 Python 业务包。`apps/web`、`apps/api`、`apps/worker` 和 `deploy` 暂不为了目录完整而空建，等前端、后端 API、worker 和部署文件真正开始实现时再创建。

迁移脚本后，协作者仍应从仓库根目录运行命令，例如 `python scripts/exports/douyin_verify_record_export.py`。脚本会自动把仓库根目录加入模块搜索路径，避免迁移到子目录后无法导入 `src.dy_data`。
