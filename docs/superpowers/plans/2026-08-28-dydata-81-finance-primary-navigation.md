# DYDATA-81 财务一级导航实施计划

> **执行方式：** 当前对话内逐项执行；每个行为先写失败测试，再做最小实现。
> **关联 Issue：** Linear `DYDATA-81`
> **设计规格：** `docs/superpowers/specs/2026-08-28-dydata-81-finance-primary-navigation-design.md`

**目标：** 将六个既有财务页面从“后台”拆为独立一级“财务”，同步桌面/移动导航，并收口门店侧 SAP 入口与 `/finance/stores` 特例。

**实现原则：** 只修改 Shell 的信息架构配置与 App 的前端准入判断；沿用 D01、既有路由、页面、API、设计令牌和组件，不新增财务首页或业务能力。

**技术栈：** React、TypeScript、Vite、pytest 前端源码契约、现有浏览器 smoke 测试。

---

## Task 1：锁定导航与权限红灯

**文件：**

- 修改：`tests/test_frontend_user_facing_contracts.py`
- 修改：`tests/test_visual_smoke.py`

**步骤：**

1. 将旧的“门店 B02 可访问 `/finance/stores` / 订单分佣显示 SAP 建议”源码契约改为相反断言。
2. 新增财务一级模块契约：`section: "finance"`、默认 `/finance/promotion`、使用 D01、位于后台项之前。
3. 新增浏览器断言：管理员财务页激活“财务”、后台页激活“后台”；门店导航无“财务”和“SAP 建议”，直达 `/finance/stores` 显示无权限。
4. 运行聚焦测试并确认失败原因来自尚未实现的新行为。

**红灯命令：**

```powershell
python -m pytest tests/test_frontend_user_facing_contracts.py -k "finance or sap"
python -m pytest tests/test_visual_smoke.py -k "finance and navigation"
```

## Task 2：最小实现财务一级导航

**文件：**

- 修改：`apps/web/src/components/Shell.tsx`
- 修改：`apps/web/src/App.tsx`

**步骤：**

1. 在 `Shell.tsx` 增加 `finance` section 与独立 finance 路由集合，把财务一级项插入后台之前。
2. 让 `secondaryNav("finance")` 直接返回六个既有财务二级项；后台只返回后台管理项。
3. 从订单分佣二级项删除“SAP 建议”，删除门店 `/finance/stores` 的 section 特例。
4. 在 `App.tsx` 删除门店角色凭 B02 访问 `/finance/stores` 的 `hasPageAccess` 特例。
5. 运行 Task 1 的聚焦测试，确认由红转绿。

## Task 3：工程与视觉验证

**文件：**

- 新增或更新：`design-qa.md`
- 视结果更新：`docs/devlog/`

**步骤：**

1. 运行 `git diff --check` 与完整前端契约测试。
2. 运行 Web production build。
3. 在 1440×900、768×1024、390×844 下核对管理员财务/后台顺序与激活态，以及门店无入口/直达拒绝；记录对照结论。
4. 运行完整 `python -m pytest`；若失败，只处理本次改动引入的回归，预存问题单独记录。
5. 运行治理套件结构、计划一致性与 S4 路由门禁。

**验证命令：**

```powershell
git diff --check
python -m pytest tests/test_frontend_user_facing_contracts.py
python -m pytest tests/test_visual_smoke.py -k "finance or navigation"
npm --prefix apps/web run build
python -m pytest
node .agent/project-manager-suite/skills/05-01-delivery-planner/scripts/validate-plan-structure.mjs docs/plans/delivery-plans/main-delivery-plan-dy-data.md
node .agent/project-manager-suite/skills/05-01-delivery-planner/scripts/check-plan-consistency.mjs docs/plans/delivery-plans/main-delivery-plan-dy-data.md
node .agent/project-manager-suite/tools/route-check.mjs .
```

## Task 4：证据回填与交付

**文件：**

- 更新：`docs/plans/delivery-plans/main-delivery-plan-dy-data.md`
- 更新：`docs/plans/delivery-plans/task-kanban-dy-data.md`
- 更新：`docs/plans/delivery-plans/sub-delivery-plan-dy-data-T5.7-system-uat.md`
- 更新：Linear `DYDATA-81`

**步骤：**

1. 回填真实测试数量、构建结果、三视口结论与剩余风险，不提前标记 T5.7 完成。
2. 提交并推送 `codex/dydata-81-finance-nav`。
3. 将 commit、验证结果和未完成的 PR/CI/部署门禁回填 Linear；保持 Issue `In Progress`，直到用户验收和最终发布门禁关闭。
