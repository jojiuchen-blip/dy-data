# DYDATA-104 构建依赖安全补丁验证

日期：2026-10-27；基线 `315bab1`。仅修改 Web 依赖清单、锁文件和本说明；没有产品源码、基础设施或生产操作。独立工作树使用自己的 `node_modules`，没有修改其他工作树的依赖目录。

## 公告与最小变更

| 依赖 | 原锁版本 | 修复后锁版本 | 官方依据 |
|---|---|---|---|
| Vite | 7.3.5 | 7.3.7 | [GHSA-587h-7wmj-h5pm](https://github.com/advisories/GHSA-587h-7wmj-h5pm) 指定7系修复版本7.3.7；[正式发布](https://github.com/vitejs/vite/releases/tag/v7.3.7)。 |
| source-map-js | 1.2.1 | 1.2.2 | [GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q) 指定修复版本1.2.2；[正式发布](https://github.com/7rulnik/source-map-js/releases/tag/v1.2.2)。 |
| esbuild | 0.27.7 | 0.28.2 | [GHSA-g7r4-m6w7-qqqr](https://github.com/advisories/GHSA-g7r4-m6w7-qqqr) 指定0.28.1起修复；[0.28.2正式发布](https://github.com/evanw/esbuild/releases/tag/v0.28.2)。 |

`package.json` 仅将 Vite 最低版本从 `^7.0.0` 更新到 `^7.3.7`。通过 `npm view vite@7.3.7 dependencies engines --json` 核对，Vite新版明确接受 `esbuild: ^0.27.0 || ^0.28.0`；因此使用正常定向解析安装0.28.2，不需要越过上游约束的 override。PostCSS原有 `source-map-js: ^1.2.1` 范围本身允许1.2.2。

锁文件中的包节点仍为125个（含根节点及各平台可选包）。版本差异仅为上表三组及 esbuild 对应平台二进制；React、React DOM、PostCSS、TypeScript、React插件及其他包版本均未变化。npm 11重生了5个既有包的peer标记，未新增业务依赖。Vite的Node要求仍为 `^20.19.0 || >=22.12.0`。

没有使用 `npm audit fix --force`、跨主版本升级、override或安全豁免。

## 执行与结果

环境：Windows，Node `v24.11.1`、npm `11.6.2`。锁文件正常解析及安装：

```powershell
cd apps/web
npm install --save-dev vite@7.3.7 --save-prefix='^' --package-lock-only --ignore-scripts
npm update esbuild source-map-js --package-lock-only --ignore-scripts
npm ci
npm audit --json
npm audit --omit=dev --json
npm exec -- tsc --noEmit
npm run build
```

- `npm ci`：退出码0，安装75个当前平台依赖，审计76个节点，报告0漏洞；实际运行安装脚本。
- 全量 `npm audit`：退出码0，info/low/moderate/high/critical均为0，total=0。
- `npm audit --omit=dev`：退出码0，全部严重级别及total均为0。
- TypeScript单独检查：退出码0。
- Vite生产构建：退出码0，实际版本7.3.7；751模块转换成功，仅有原有大包体积提示。
- `npm ls vite esbuild source-map-js react react-dom --all`：退出码0，确认实际安装版本与锁文件一致；React/DOM均保持19.2.7。
- `git diff --check`：退出码0。

原始审计JSON保存在本工作树未跟踪的 `.tmp/dependencies/npm-all.json` 和 `npm-prod.json`；发布安全负责人还会独立复扫，不把本记录替代最终CI结果。

## 代表性浏览器回归

Browser plugin not available；使用既有 Python Playwright/Chromium，真实独立合成SQLite、FastAPI和本工作树安装的新版Vite，不请求生产。

```powershell
python -m pytest tests/test_dydata105_buttons_browser.py::test_dydata105_store_confirm_invoice_lifecycle_and_replacement_real_readback tests/test_dydata105_buttons_browser.py::test_dydata105_ranking_filters_drill_and_order_fee_direction_downloads tests/test_dydata105_remaining_buttons_browser.py::test_remaining_status_pagination_and_real_terminated_candidate_recovery tests/test_visual_smoke.py::test_finance_import_clears_stale_preview_after_409 -q --tb=short
```

结果：`5 passed, 6 warnings in 106.03s`，退出码0，零失败/跳过。覆盖红冲/作废与替换回读、确认金额和税额、榜单筛选/下钻/双费方向下载、真实终止后恢复候选，以及409清理旧冻结预览后重传成功。警告为既有MCP认证配置弃用提示；没有修改测试断言或产品行为。

范围限制：本次完成依赖补丁、当前机器安装/审计/构建和指定5例回归；Linux CI、最终全仓及部署仍由主线程独立验收。生产未变更。
