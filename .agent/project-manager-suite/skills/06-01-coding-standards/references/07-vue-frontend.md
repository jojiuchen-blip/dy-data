# Vue 3 前端规范

> 来源：通用 Vue 3 工程实践（Vue 3 + Vite + Composition API）+ 团队约定
> 适用：Vue 3 前端项目，主要面向 Web 管理台和中后台页面

---

## 文件结构

1. 【强制】Vue 文件按以下顺序组织：
   ```vue
   <script setup>
   // 逻辑
   </script>

   <template>
     <!-- 模板 -->
   </template>

   <style scoped>
   /* 样式 */
   </style>
   ```

2. 【强制】组件文件名使用 **PascalCase**：`UserStatusCard.vue`、`UserProfileCard.vue`。
3. 【推荐】组合式函数放 `src/composables/`，以 `use` 开头：`useUserProfile.js`。
4. 【推荐】API 请求封装放 `src/services/`，按业务域拆分：`user.js`、`order.js`、`project.js`。

## 组件规约

5. 【强制】Props 必须声明类型和默认值：
   ```js
   const props = defineProps({
     status: { type: String, required: true },
     items: { type: Array, default: () => [] }
   })
   ```
6. 【强制】Emit 事件必须通过 `defineEmits` 声明。
7. 【推荐】单个组件不超过 300 行，超过则拆分子组件。

## 架构原则

8. 【强制】前端应保持 **UI 展示与交互编排职责**，避免把复杂业务规则分散写在模板中。
   - 禁止在模板里写复杂条件表达式
   - 复杂规则优先放入 `computed`、`composable` 或服务层
   - 展示所需的状态字段、标签文案、按钮可见性应尽量由接口或统一适配层提供
9. 【强制】不在模板中加入复杂逻辑，复杂计算用 `computed` 或 `composable` 封装。

## 样式规约

10. 【强制】默认使用 `<style scoped>`，避免全局样式污染；确需全局样式时单独放入全局样式文件。
11. 【推荐】主题色、间距、字号等优先通过设计令牌、CSS 变量或主题配置统一管理，不在组件中散落硬编码。
12. 【推荐】响应式布局优先使用 Flexbox；二维复杂布局优先考虑 Grid。

## 注释与命名

13. 【强制】注释使用团队统一语言，变量与函数名保持英文可读命名。
14. 【推荐】方法名用 `handle` 前缀表示事件处理：`handleTabClick`、`handleSubmit`。
15. 【推荐】计算属性和 `ref` 用名词命名：`visibleTabs`、`currentUser`。
