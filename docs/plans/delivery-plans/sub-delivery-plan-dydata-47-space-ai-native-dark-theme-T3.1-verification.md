# DYDATA-47 T3.1 自动化与视觉验收

#### T3.1 建立双主题防退化并完成全量验证

**PRD 双链·读**：`docs/superpowers/specs/2026-07-23-dydata-47-space-ai-native-dark-theme-design.md` §9。  
**核心逻辑**：补静态门禁和主题行为测试；Playwright 覆盖关键路由与 390/768/1440 浅色、深色组合；使用结构、溢出、关键控件和截图 smoke，而非脆弱像素 diff。  
**核心文件**：`tests/test_design_system_docs.py`、`tests/test_design_system_enforcement.py`、`tests/test_visual_smoke.py`、新增主题/品牌契约测试、验证证据。  
**完成标准**：设计 token 可解析；主题与署名不可绕过；关键页面无水平溢出、空白画布或固定元素遮挡；前端构建、完整 pytest 与 diff check 返回成功。  
**完成收尾：状态同步**：把证据、完成日期和剩余风险同步到主计划、看板和本子计划；Linear 更新为待人审，不执行部署。  
**Owner**：AI 执行 -> 人审。  
**前置**：T2.2。  
**状态**：已完成（2026-07-23）。

## Verification Method

- `python -m pytest tests/test_design_system_docs.py tests/test_design_system_enforcement.py tests/test_visual_smoke.py -q`
- `python -m pytest`
- `npm --prefix apps/web run build`
- `git diff --check`

## Evidence Log

- 完整回归：`python -m pytest -q`，`991 passed, 2 skipped`；跳过项为既有环境条件，不是本轮失败。
- 最终 SPACE 尺寸微调后复核：静态门禁 `48 passed`；关键页面与认证入口视觉 smoke `75 passed`。
- `npm --prefix apps/web run build` 成功，115 modules transformed；仅保留既有 500 kB chunk size warning。
- `git diff --check` 无 whitespace error；未执行 Railway 部署。
