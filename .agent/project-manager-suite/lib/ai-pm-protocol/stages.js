/**
 * Traceability:
 * Rule sources:
 * - skills/00-01-ai-project-manager/references/core/runtime.md
 * - skills/00-01-ai-project-manager/references/core/routing.md
 * Consumed by:
 * - tools/route-check.mjs
 */
import { STAGE_IDS } from './constants.js';

// 阶段门禁的运行时判定以 tools/route-check.mjs（buildGateChecks / buildBlockingReasons）为准。
// 此处不再维护 gatekeeping 数组：它没有代码消费者，且曾与脚本实际检查项漂移。
const stages = [
    {
        id: STAGE_IDS.S0,
        name: '需求调研',
        signals: ['首次必问尚未完成，启动最小必需字段包仍有缺口', '需求仍停留在访谈和业务理解层'],
        minimumDeliverable: '需求清单',
        ownerSkill: null
    },
    {
        id: STAGE_IDS.S0_5,
        name: '既有项目基线诊断',
        signals: ['已有代码接入套件', '项目维护性差且缺少 BRD / 页面说明 / foundation / PRD 等关键文件'],
        minimumDeliverable: '项目画像草稿 + 关键维护文件缺口清单',
        ownerSkill: 'project-baseline-auditor'
    },
    {
        id: STAGE_IDS.S1,
        name: '业务需求文档',
        signals: ['首次必问已结束，启动最小必需字段包已齐', '需要形成可评审的业务需求文档'],
        minimumDeliverable: '业务需求文档 / BRD',
        ownerSkill: 'brd-writer'
    },
    {
        id: STAGE_IDS.S2,
        name: '页面设计、技术地基与完整版 PRD',
        signals: ['已有业务需求文档', '需要先完成页面代码与交互语义冻结，再收口页面环节并沉淀完整 PRD'],
        minimumDeliverable: '首轮：页面代码 / 页面交付清单 + 待确认项；页面环节收口后：术语表 / Schema / API / foundation 交付清单；最终：功能列表 + 主 PRD + 子 PRD',
        ownerSkill: 'page-chief -> prd-chief'
    },
    {
        id: STAGE_IDS.S3,
        name: '任务拆解与开发计划',
        signals: ['完整版 PRD 已形成', '需要拆成开发任务并形成开发计划'],
        minimumDeliverable: '正式开发计划文件组 + 当前执行摘要',
        ownerSkill: 'delivery-planner'
    },
    {
        id: STAGE_IDS.S4,
        name: '开发执行',
        signals: [
            '正式开发计划文件组存在、通过结构校验，且由 delivery-planner 完成 S4 前计划一致性校验',
            '可以进入编码、联调和实现'
        ],
        minimumDeliverable: '当前任务的执行结果 + 任务状态更新 + 问题/决策记录',
        ownerSkill: 'coding-standards'
    },
    {
        id: STAGE_IDS.S5,
        name: '测试用例生成',
        signals: ['开发执行已完成，或当前版本已具备可验证基础', '需要基于 PRD 生成标准化测试用例'],
        minimumDeliverable: '验收文档 + 单域测试用例文件 + 验收矩阵 + 版本历史',
        ownerSkill: 'test-case-chief'
    },
    {
        id: STAGE_IDS.S6,
        name: '测试执行',
        signals: ['测试用例已准备好', '需要执行测试并记录问题'],
        minimumDeliverable: '验收结论 + 不符合项清单 + 补缺建议 + 阶段收口建议',
        ownerSkill: 'test-case-runner'
    },
    {
        id: STAGE_IDS.S7,
        name: '完工前安全扫描',
        signals: ['已进入完工 / 交付前收口', '需要完成固定安全闸门扫描并给出 PASS/BLOCK/WAIVER 结论'],
        minimumDeliverable: '安全扫描报告 + PASS / BLOCK / WAIVER 结论 + 输入证据缺口说明',
        ownerSkill: 'security-scan'
    }
];

const stageDecisionRules = [
    '多个阶段可选时，优先较早阶段',
    '首次必问未结束、启动最小必需字段包未补齐前，不跳过 S0；补齐后即可进入 S1',
    '用户导入已有代码并要求补齐维护知识底座时，先进入 S0.5，由 project-baseline-auditor 生成项目画像和关键文件缺口清单',
    '用户要求先给方案时进入 S1 或 S2',
    '用户要求拆任务、拆开发任务、制定开发计划时进入 S3',
    '用户要求实现某模块但上下文不足时，先补上下文再进入 S3/S4',
    '当前阶段与推荐阶段冲突时，先解释差异再更新画像',
    '因页面信号而补问页面任务必补字段包，只代表在补 S2 门禁，不代表已经进入 S2',
    '项目画像、执行计划或基础骨架缺失时，必须停留在启动/骨架补齐态，不得对外表述为已进入 S2',
    'S2 页面代码或页面交付清单未产出前，主入口必须先停留在 page-chief 链路内',
    'S2 页面环节未被 page-chief 判定 DONE 前，不得进入 prd-chief、foundation-builder、prd-writer 或 S3',
    'S2 只有页面环节已收口后，才允许切换到 prd-chief；只有 foundation 完成后，才允许继续推进 prd-writer',
    'S7 只能作为完工前固定安全闸门使用；未完成 security-scan 报告前，不得把项目判定为可完工'
];

const globalCompanionAbilities = [
    {
        skill: 'project-devlog',
        triggers: [
            'new_stage_deliverable',
            'stage_changed',
            'effective_progress_made',
            'need_handover_for_next_round'
        ]
    },
    {
        skill: 'project-link-indexer',
        // 触发词与 skills/00-03-project-link-indexer/scripts/run-project-link-indexer.mjs 的 --trigger 合法取值一致：
        // 前两个为刷新类（会写 docs/index/*），后三个为诊断类（只检查不写文件）。
        triggers: [
            'artifact_files_added_or_split',
            'after_existing_project_baseline_audit',
            'need_broken_link_or_reverse_link_check',
            'need_file_relationship_diagnosis',
            'need_impact_lookup'
        ]
    }
];

export { stages, stageDecisionRules, globalCompanionAbilities };
