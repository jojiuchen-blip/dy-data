# DYDATA-47 T1.1 正式设计系统与主题契约

#### T1.1 固化双主题 token、组件预览和协作规则

**PRD 双链·读**：`docs/superpowers/specs/2026-07-23-dydata-47-space-ai-native-dark-theme-design.md` §2-§4、§9。  
**核心逻辑**：正式设计系统从 light-only 升级为 light/dark；保留品牌橙与语义色职责分离；展示主题选择、深色组件、署名变体和页面骨架，候选历史文件保持不变。  
**核心文件**：`docs/design-system/tokens.json`、`docs/design-system/index.html`、`docs/design-system/README.md`、`tests/test_design_system_docs.py`、`tests/test_design_system_enforcement.py`。  
**完成标准**：机器 token 包含两套语义色与主题元数据；HTML 可切换并完整展示两种主题；README 写清修改同步规则和项目专属署名限制；目标测试精确验证已确认值。  
**完成收尾：状态同步**：记录目标 pytest、构建和 diff check；同步主计划、看板、本子计划，再进入 T1.2。  
**Owner**：AI 执行 -> 人审。  
**前置**：用户确认 V0.2 视觉和本次直接开发授权。  
**状态**：已完成（2026-07-23）。

## Verification Method

- `python -m pytest tests/test_design_system_docs.py tests/test_design_system_enforcement.py -q`
- `npm --prefix apps/web run build`
- `git diff --check`

## Evidence Log

- RED：先更新目标契约测试，6 项因正式元数据、深色 token、主题预览和 README 尚未升级而失败。
- GREEN：`python -m pytest tests/test_design_system_docs.py tests/test_design_system_enforcement.py -q`，`42 passed`。
- BUILD：首次因新 worktree 缺少 `tsc` 失败；执行 `npm --prefix apps/web ci` 后，`npm --prefix apps/web run build` 成功，107 modules transformed。
- `git diff --check` 无 whitespace error，仅有 Git 的 LF/CRLF 工作区提示。
