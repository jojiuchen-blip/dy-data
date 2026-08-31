# DYDATA-81 开票确认视觉对齐 QA

## 对比证据

- source visual truth path: `C:/Users/86138/AppData/Local/Temp/codex-clipboard-821f04a5-e51d-484e-b838-7bf9a0efece6.png`
- implementation screenshot path: `pwScreenShot/dydata-81-store-finance/final/store-invoice-verification-1440x900.png`
- source pixels: 829 × 457，约 144 dpi；截图为原临时看板的开票工作区参考，不含正式系统外壳。
- implementation pixels: 1440 × 1993，96 dpi；CSS viewport 1440 × 900，deviceScaleFactor 1，full-page capture。
- normalization: 以内容结构和同一“已选完整账期、日期与 20 位号码均有效、全部核验通过”状态比较；未按像素缩放追求临时看板皮肤，因为用户明确要求沿用正式系统视觉规范。
- state: 门店 `store_001`，系统自动锁定账期 `2026-08` 及完整抵扣组，价税合计 ¥10.24，发票日期 `2026-08-08`，号码 `98765432109876543210`，七项核验通过，提交按钮可用。

## Findings

- 无 P0/P1/P2 问题。原参考中的左右双栏、购买方完整开票资料、一键复制、数电专票表单、不含税/税额/价税合计、逐项核验和整栏主操作，均在正式系统设计语言中复现。
- [P3] 正式系统在工作区之前保留只读系统账期、指标和推广费账单，导致工作区不在页面首屏。该差异属于真实业务流程约束：用户需要先核对系统自动确定的完整账期，且系统需要保留现有账单与替换发票闭环，不建议为临时看板的首屏构图而删除。

## Required Fidelity Surfaces

- Fonts and typography: 使用正式系统现有字体栈、标题层级、表单字号与字重；中文长地址在窄屏正常换行，无截断。
- Spacing and layout rhythm: 桌面为约 1:1.18 双栏，面板内边距、表单栅格、信息行和主按钮节奏与正式卡片体系一致；390/768/1440 三档无页面横向溢出。
- Colors and visual tokens: 使用 `--brand-orange`、`--brand-orange-soft`、`--brand-orange-ink`、正式表面/边框 token；当前环节和必要提示使用品牌高亮，未复制临时看板的独立配色。
- Image quality and asset fidelity: 参考工作区无图片资产；复制、核验状态均使用项目既有 Solar Icon 图标库，没有文本符号、手绘 SVG 或占位图形。
- Copy and content: 购买方、税号、地址、电话、开户行账号、项目名称、税收分类编码、税率及核验规则与参考逻辑对齐；演示说明未带入正式页面。

## Full-view comparison evidence

- 同一次视觉比较输入中打开了源参考与浏览器渲染截图。正式页保持主系统外壳、七步结算时间轴、筛选/账单/记录模块；核心工作区的左右关系和任务顺序与参考一致。
- 页面宽度检查：390、768、1440 均满足 `scrollWidth <= clientWidth + 1`。

## Focused region comparison evidence

- 聚焦“登记发票信息”双栏区域检查：左栏字段顺序、右栏字段组合、金额拆分、核验列表和全宽 CTA 均清晰可读；该区域在 1440 截图中具备足够像素，不需要额外裁切图。

## Comparison history

- Initial comparison: 未发现 P0/P1/P2。发现实现中的核验状态最初使用文本勾号，按正式资产规范替换为项目既有 Solar Icon；同时补齐固定购买方/6% 税率及税额计算一致性两项核验。
- Post-fix evidence: `store-invoice-verification-1440x900.png` 对应的交互状态测试已通过；最终源码使用 `SolarIcon`，七项核验全部通过后按钮才可用。

## Implementation Checklist

- [x] 账期由系统按最早未开票规则自动确定并只读展示；保留真实登记 API、幂等键和替换发票逻辑。
- [x] 建立始终可见的左右双栏开票核验工作区。
- [x] 以整数分自动推导不含税金额与税额，并逐项展示核验结果。
- [x] 当前环节提示条使用正式品牌高亮色。
- [x] 完成静态契约、设计系统、浏览器交互、响应式和构建验证。

## Follow-up Polish

- 用户逐页验收时可根据真实门店数据长度微调左栏标签宽度；当前无阻塞问题。

final result: passed
