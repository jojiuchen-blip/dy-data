# 交互描述 - dy-data（DYDATA-32 账号权限配置现状基线）

> 生成时间: 2026-07-20
> Skill: page-explainer
> 依据: page-delivery + 真实运行页面验证 + `AdminAccountsPage.tsx`
> 当前状态: 全部语义条目已于 2026-07-20 经用户确认并标记为 `locked`

> 状态权威源：每条语义的 status 在卡片行和“机读表（下游消费）”各写一次，以机读表为权威；两处必须同步更新。

## 账号管理

> 路由: `/admin/accounts`
> 文件: `C:\Users\86138\Documents\抖音来客看板-dydata-32-rules\apps\web\src\pages\AdminAccountsPage.tsx`
> 运行页面证据: `http://127.0.0.1:5173/admin/accounts`；Codex Browser 实际登录最高管理员后完成 DOM 快照、全页截图、角色选择、账号保存和密码重置入口点击
> 代码证据: `AdminAccountsPage.tsx`；`apps/web/src/api/client.ts`
> 页面目的: 维护本地登录账号、现有角色状态、门店绑定、密码和未激活门店查询。
> 覆盖角色: 当前运行系统中的最高管理员；目标角色边界和新增入口记录在差异文件中，不在本文件冒充现有能力。
> 原型 / mock 边界: 验证使用独立临时 SQLite 数据库和测试最高管理员；测试账号只存在于临时数据库，不代表生产数据。

### 页面布局

```text
┌─────────────────────────────────────────────────────────────┐
│ 管理后台导航                                      当前账号  │
├─────────────────────────────────────────────────────────────┤
│ 账号管理说明                                  [新建账号]    │
├──────────────────────────────────┬──────────────────────────┤
│ 账号列表                         │ 新建 / 编辑账号表单       │
│ 账号、角色、状态、门店、操作     │ 角色、状态、门店、密码    │
│                                  │ 可选的密码重置表单        │
├──────────────────────────────────┴──────────────────────────┤
│ 未激活门店：查询条件、查询/重置、结果表格                    │
└─────────────────────────────────────────────────────────────┘
```

### 模块交互

#### 页面头部

**描述**：显示账号管理标题、用途说明和“新建账号”按钮。

**证据来源**：Codex Browser 运行页面截图与 DOM 快照；页面代码佐证按钮状态处理。

**原型态说明**：none

**交互语义**：

> **`accounts.header.create.1`** `locked`
>
> - **元素**: 页面头部 → 新建账号
> - **角色**: 当前最高管理员
> - **前置条件**: 已进入账号管理页面
> - **触发**: 点击
> - **系统行为**: 清除当前编辑账号和状态提示，恢复新建账号空表单
> - **用户可见结果**: 右侧显示“新建账号”和默认的门店账号、启用状态
> - **校验**: none
> - **业务态兜底**: 当前已在新建状态时仍保持空表单
> - **证据来源**: Codex Browser 运行页面可见 + `startCreate` 代码佐证
> - **原型态说明**: none

<details>
<summary>机读表（下游消费）</summary>

| id | actor | source_page | source_module | source_element | precondition | trigger | system_behavior | user_visible_result | validation | fallback | evidence_source | prototype_note | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| accounts.header.create.1 | 当前最高管理员 | /admin/accounts | 页面头部 | 新建账号 | 已进入账号管理页面 | 点击 | 清除当前编辑账号和状态提示并恢复空表单 | 右侧显示新建账号表单及默认值 | none | 已在新建状态时仍保持空表单 | Codex Browser 运行页面可见 + startCreate 代码佐证 | none | locked |

</details>

#### 账号列表

**描述**：表格展示账号名、所属账户编号、角色、状态、门店范围、激活状态和更新时间；有数据时每行提供编辑和重置密码。

**证据来源**：Codex Browser 在临时数据库中保存测试账号后，运行页面实际出现数据行、编辑和重置密码按钮；页面代码佐证按钮行为。

**原型态说明**：验证行 `preview-viewer-32` 仅为临时测试数据，表示真实账号行的交互状态。

**交互语义**：

> **`accounts.list.edit.1`** `locked`
>
> - **元素**: 账号列表 → 编辑
> - **角色**: 当前最高管理员
> - **前置条件**: 列表存在账号
> - **触发**: 点击
> - **系统行为**: 将所选账号内容载入右侧编辑表单
> - **用户可见结果**: 表单标题变为“编辑账号”，显示账号现有角色、状态和门店范围
> - **校验**: none
> - **业务态兜底**: 空列表显示“暂无账号”，不显示行级操作
> - **证据来源**: Codex Browser 测试账号行可见 + `startEdit` 代码佐证
> - **原型态说明**: 临时测试账号仅用于显示真实行级交互

> **`accounts.list.reset-password.2`** `locked`
>
> - **元素**: 账号列表 → 重置密码
> - **角色**: 当前最高管理员
> - **前置条件**: 列表存在账号
> - **触发**: 点击
> - **系统行为**: 选中目标账号并在右侧追加重置密码表单
> - **用户可见结果**: 显示目标账号名、新密码、确认密码、取消和确认重置
> - **校验**: none
> - **业务态兜底**: 空列表不显示重置入口
> - **证据来源**: Codex Browser 实际点击测试账号“重置密码” + 页面代码佐证
> - **原型态说明**: 未提交真实密码重置；只验证入口和表单状态

<details>
<summary>机读表（下游消费）</summary>

| id | actor | source_page | source_module | source_element | precondition | trigger | system_behavior | user_visible_result | validation | fallback | evidence_source | prototype_note | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| accounts.list.edit.1 | 当前最高管理员 | /admin/accounts | 账号列表 | 编辑 | 列表存在账号 | 点击 | 将所选账号内容载入编辑表单 | 显示账号现有角色、状态和门店范围 | none | 空列表显示暂无账号且无行级操作 | Codex Browser 测试账号行可见 + startEdit 代码佐证 | 临时测试账号仅用于显示真实行级交互 | locked |
| accounts.list.reset-password.2 | 当前最高管理员 | /admin/accounts | 账号列表 | 重置密码 | 列表存在账号 | 点击 | 选中目标账号并追加重置密码表单 | 显示目标账号和密码重置字段 | none | 空列表不显示重置入口 | Codex Browser 实际点击 + 页面代码佐证 | 未提交真实密码重置 | locked |

</details>

#### 账号表单

**描述**：表单维护账号名、显示名称、所属账户编号、当前角色、状态、门店权限和密码。当前角色选项为门店账号、全局查看和最高管理员。

**证据来源**：Codex Browser 实际展开角色选择、选择“全局查看”、观察门店权限禁用联动并保存临时测试账号；页面代码佐证字段整理和保存逻辑。

**原型态说明**：none

**交互语义**：

> **`accounts.editor.role.1`** `locked`
>
> - **元素**: 账号表单 → 角色
> - **角色**: 当前最高管理员
> - **前置条件**: 新建或编辑账号
> - **触发**: 选择
> - **系统行为**: 在门店账号、全局查看和最高管理员之间切换当前角色
> - **用户可见结果**: 角色显示更新，门店权限控件随角色联动
> - **校验**: 只能选择当前页面提供的三个角色值
> - **业务态兜底**: none
> - **证据来源**: Codex Browser 实际展开和选择角色 + `SelectField` 配置佐证
> - **原型态说明**: 这是现有角色模型，不代表 DYDATA-32 目标角色已经落地

> **`accounts.editor.status.2`** `locked`
>
> - **元素**: 账号表单 → 状态
> - **角色**: 当前最高管理员
> - **前置条件**: 新建或编辑账号
> - **触发**: 选择
> - **系统行为**: 在启用和停用之间切换账号状态
> - **用户可见结果**: 状态字段显示所选值；保存后列表状态同步
> - **校验**: 只能选择启用或停用
> - **业务态兜底**: none
> - **证据来源**: 运行页面状态控件可见 + `SelectField` 配置和保存逻辑佐证
> - **原型态说明**: none

> **`accounts.editor.store-scope.3`** `locked`
>
> - **元素**: 账号表单 → 门店权限
> - **角色**: 当前最高管理员
> - **前置条件**: 新建或编辑账号
> - **触发**: 选择门店或切换角色
> - **系统行为**: 门店账号可选择多个门店；全局查看和最高管理员禁用选择器并清空提交范围
> - **用户可见结果**: 门店账号显示已选门店或“未绑定门店”；全局角色显示“全部门店”
> - **校验**: 当前前端未显式阻止门店账号空范围提交
> - **业务态兜底**: 无门店选项时门店账号保持“未绑定门店”
> - **证据来源**: Codex Browser 选择“全局查看”后控件变为禁用且显示全部门店 + `compactPayload` 代码佐证
> - **原型态说明**: 临时数据库没有门店选项；不据此判断生产门店数据缺失

> **`accounts.editor.save.4`** `locked`
>
> - **元素**: 账号表单 → 保存账号
> - **角色**: 当前最高管理员
> - **前置条件**: 已填写账号表单
> - **触发**: 提交
> - **系统行为**: 新建时创建账号，编辑时更新账号；成功后将结果写回并按账号名排序列表
> - **用户可见结果**: 成功显示“账号已保存”，表单进入编辑状态；失败显示通用检查提示
> - **校验**: 前端整理空格；新建时提交密码；失败提示要求检查账号名、所属账户编号、密码确认和门店绑定
> - **业务态兜底**: 保存失败时保留表单内容供用户修改
> - **证据来源**: Codex Browser 成功保存临时测试账号 + `handleSave` 代码佐证
> - **原型态说明**: 保存发生在独立临时数据库，不涉及生产数据

<details>
<summary>机读表（下游消费）</summary>

| id | actor | source_page | source_module | source_element | precondition | trigger | system_behavior | user_visible_result | validation | fallback | evidence_source | prototype_note | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| accounts.editor.role.1 | 当前最高管理员 | /admin/accounts | 账号表单 | 角色 | 新建或编辑账号 | 选择 | 在门店账号、全局查看和最高管理员之间切换 | 角色显示更新且门店权限联动 | 只能选择当前三个角色值 | none | Codex Browser 实际选择 + SelectField 配置佐证 | 现有角色模型，不代表目标已落地 | locked |
| accounts.editor.status.2 | 当前最高管理员 | /admin/accounts | 账号表单 | 状态 | 新建或编辑账号 | 选择 | 在启用和停用之间切换 | 当前状态更新，保存后列表同步 | 只能选择启用或停用 | none | 运行页面可见 + SelectField 和保存逻辑佐证 | none | locked |
| accounts.editor.store-scope.3 | 当前最高管理员 | /admin/accounts | 账号表单 | 门店权限 | 新建或编辑账号 | 选择门店或切换角色 | 门店账号可选多店；全局角色禁用选择并清空提交范围 | 显示已选门店、未绑定门店或全部门店 | 当前前端未显式阻止门店账号空范围提交 | 无门店选项时保持未绑定门店 | Codex Browser 联动验证 + compactPayload 代码佐证 | 临时数据库无门店选项不代表生产缺失 | locked |
| accounts.editor.save.4 | 当前最高管理员 | /admin/accounts | 账号表单 | 保存账号 | 已填写账号表单 | 提交 | 创建或更新账号并刷新排序后的列表 | 成功提示并进入编辑状态；失败显示检查提示 | 整理空格，新建提交密码，服务端结果决定成功 | 保存失败保留表单内容 | Codex Browser 临时账号保存成功 + handleSave 代码佐证 | 仅写入独立临时数据库 | locked |

</details>

#### 密码重置

**描述**：从账号行打开后，在账号编辑区下方显示目标账号、新密码、确认密码、取消和确认重置。

**证据来源**：Codex Browser 实际点击测试账号“重置密码”；页面代码佐证提交与取消行为。

**原型态说明**：未提交密码重置，只验证页面入口与字段状态。

**交互语义**：

> **`accounts.password-reset.cancel.1`** `locked`
>
> - **元素**: 密码重置 → 取消
> - **角色**: 当前最高管理员
> - **前置条件**: 已打开密码重置表单
> - **触发**: 点击
> - **系统行为**: 清除当前重置目标
> - **用户可见结果**: 密码重置表单关闭
> - **校验**: none
> - **业务态兜底**: none
> - **证据来源**: Codex Browser 表单可见 + 取消按钮代码佐证
> - **原型态说明**: none

> **`accounts.password-reset.submit.2`** `locked`
>
> - **元素**: 密码重置 → 确认重置
> - **角色**: 当前最高管理员
> - **前置条件**: 已选择目标账号并填写两次密码
> - **触发**: 提交
> - **系统行为**: 请求重置目标账号密码，成功后更新账号行并关闭表单
> - **用户可见结果**: 成功显示“密码已重置”；失败提示检查两次输入是否一致
> - **校验**: 两次密码由服务端校验是否一致
> - **业务态兜底**: 提交失败时保留表单供用户修改
> - **证据来源**: Codex Browser 表单可见 + `handleResetPassword` 代码佐证
> - **原型态说明**: 未在运行验证中提交新密码

<details>
<summary>机读表（下游消费）</summary>

| id | actor | source_page | source_module | source_element | precondition | trigger | system_behavior | user_visible_result | validation | fallback | evidence_source | prototype_note | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| accounts.password-reset.cancel.1 | 当前最高管理员 | /admin/accounts | 密码重置 | 取消 | 已打开密码重置表单 | 点击 | 清除重置目标 | 重置表单关闭 | none | none | Codex Browser 表单可见 + 取消按钮代码佐证 | none | locked |
| accounts.password-reset.submit.2 | 当前最高管理员 | /admin/accounts | 密码重置 | 确认重置 | 已选择账号并填写两次密码 | 提交 | 请求重置密码，成功后更新账号并关闭表单 | 显示成功或失败提示 | 服务端校验两次密码一致 | 失败时保留表单 | Codex Browser 表单可见 + handleResetPassword 代码佐证 | 未提交新密码 | locked |

</details>

#### 未激活门店

**描述**：页面底部提供一个查询条件、查询、重置和结果表，用于按所属账户编号或门店位置编号（POI ID）寻找当前系统判定的未激活门店。

**证据来源**：Codex Browser 运行页面实际可见；页面代码佐证查询和重置行为。

**原型态说明**：临时数据库结果为空；空表只表示当前测试数据状态。

**交互语义**：

> **`accounts.unactivated.search.1`** `locked`
>
> - **元素**: 未激活门店 → 查询
> - **角色**: 当前最高管理员
> - **前置条件**: none
> - **触发**: 输入编号后提交
> - **系统行为**: 按去除首尾空格后的查询值重新读取未激活门店
> - **用户可见结果**: 表格刷新为匹配结果
> - **校验**: 查询值可以为空
> - **业务态兜底**: 无匹配结果显示“暂无未激活门店”
> - **证据来源**: Codex Browser 运行页面可见 + `handleUnactivatedSearch` 代码佐证
> - **原型态说明**: 临时数据库空结果不代表生产无未激活门店

> **`accounts.unactivated.reset.2`** `locked`
>
> - **元素**: 未激活门店 → 重置
> - **角色**: 当前最高管理员
> - **前置条件**: none
> - **触发**: 点击
> - **系统行为**: 清空查询值并重新读取全部未激活门店
> - **用户可见结果**: 查询框清空，结果表恢复默认范围
> - **校验**: none
> - **业务态兜底**: 无结果时显示“暂无未激活门店”
> - **证据来源**: Codex Browser 运行页面可见 + `resetUnactivatedSearch` 代码佐证
> - **原型态说明**: none

<details>
<summary>机读表（下游消费）</summary>

| id | actor | source_page | source_module | source_element | precondition | trigger | system_behavior | user_visible_result | validation | fallback | evidence_source | prototype_note | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| accounts.unactivated.search.1 | 当前最高管理员 | /admin/accounts | 未激活门店 | 查询 | none | 输入编号后提交 | 按修剪后的查询值读取未激活门店 | 表格刷新为匹配结果 | 查询值可以为空 | 无匹配结果显示暂无未激活门店 | Codex Browser 运行页面可见 + handleUnactivatedSearch 代码佐证 | 临时数据库空结果不代表生产状态 | locked |
| accounts.unactivated.reset.2 | 当前最高管理员 | /admin/accounts | 未激活门店 | 重置 | none | 点击 | 清空查询并读取全部未激活门店 | 查询框清空且结果恢复默认范围 | none | 无结果显示暂无未激活门店 | Codex Browser 运行页面可见 + resetUnactivatedSearch 代码佐证 | none | locked |

</details>
