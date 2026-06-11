# 抖音结算中心前端 Mock 看板

本目录是第一阶段前端工程，使用 React + TypeScript + Vite 构建页面 1、页面 2、页面 3。

当前数据来自 `src/data/mock/`，这些文件复制自仓库根目录 `mock/`，只用于前后端并行开发和交互验证。后续真实 API 稳定后，应替换 `src/data/mockData.ts` 的数据读取层，不应把这些 mock 文件视为最终接口或真实业务数据。

## 本地运行

```powershell
npm install
npm run dev
```

## 构建检查

```powershell
npm run build
```
