# dy-data Web

React 19 + TypeScript + Vite 前端，承载需要登录的经营看板、结算复核、订单明细、线索运营和后台管理。

## 数据与认证

- 真实 `/api/v1` 是默认数据源，请求通过共享 client 发送并携带会话凭据。
- `AuthGate` 负责登录态页面体验；角色和门店数据权限仍由 FastAPI 后端执行。
- `VITE_USE_MOCKS=true` 只用于显式受控开发，不得静默掩盖真实 API 错误。

## 当前路由范围

- 登录、销售、门店排名、月度结算和订单明细。
- 线索总览、线索详情与跟进。
- 账号、SKU、非佣金归属账号、商品类型可见性、反馈和同步管理。
- 线索分配规则、试运行、记录、总部池和门店评分等管理页面。

准确路由以 `src/App.tsx` 为准，接口以 `src/api/` 和后端 schema 为准。

## 开发

```powershell
npm install
npm run dev
```

构建与类型检查：

```powershell
npm run build
```

## 实现约束

- 视觉与组件规范读取 `../../docs/design-system/README.md` 和 `../../docs/design-system/tokens.json`。
- 页面不复制结算、线索分配或权限业务规则；后端输出业务结果，前端负责状态与交互呈现。
- 接口型页面至少处理加载、空数据、错误、无权限和正常状态。
- 可保存功能必须用真实 API 验证提交后重新加载的回显一致性。
- 不提交 API 密钥、Cookie、生产 URL、真实个人数据或本地路径。
