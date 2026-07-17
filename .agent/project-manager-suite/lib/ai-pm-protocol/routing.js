/**
 * Traceability:
 * Rule sources:
 * - skills/00-01-ai-project-manager/references/core/runtime.md
 * - skills/00-01-ai-project-manager/references/core/routing.md
 * Consumed by:
 * - tools/route-check.mjs
 * - tools/bootstrap-host.mjs
 */
const routeTargets = {
    'S0.5': {
        skill: 'project-baseline-auditor',
        exclusiveDeliverable: true
    },
    S1: {
        skill: 'brd-writer',
        exclusiveDeliverable: true
    },
    S2: {
        skill: 'page-chief',
        followUpSkills: ['prd-chief'],
        internalSkills: ['page-designer', 'page-explainer', 'foundation-builder', 'prd-writer'],
        exclusiveDeliverable: true,
        prerequisites: ['pageTaskRequired'],
        handoffGate: 'pageStageClosedForPrd'
    },
    S3: {
        skill: 'delivery-planner',
        exclusiveDeliverable: true
    },
    S4: {
        skill: 'coding-standards',
        exclusiveDeliverable: true
    },
    S5: {
        skill: 'test-case-chief',
        internalSkills: ['prd-acceptance-reviewer', 'test-case-writer', 'test-case-reviewer'],
        exclusiveDeliverable: true
    },
    S6: {
        skill: 'test-case-runner',
        exclusiveDeliverable: true
    },
    S7: {
        skill: 'security-scan',
        exclusiveDeliverable: true
    }
};

const gatingRules = {
    startupMinimum: {
        description: '启动最小必需字段包必须足以恢复上下文',
        fields: ['project_name', 'project_one_liner', 'target_users', 'main_problem'],
        blockOnMissing: true
    },
    pageTaskRequired: {
        description: '页面任务进入 S2 前必须补齐页面任务必补字段包',
        fields: ['coverage_scope', 'page_primary_user', 'page_primary_purpose', 'page_positioning_tag'],
        blockOnMissing: true
    },
    brdReadyForPage: {
        description: '进入 S2 页面工作前，BRD 权威文档必须已经存在',
        evidence: ['brd_exists'],
        blockOnMissing: true
    },
    pageStageClosedForPrd: {
        description: 'S2 中只有页面环节被 page-chief 判定收口后，才允许切换到 prd-chief',
        evidence: [
            'page_delivery_exists',
            'page_code_files_exist',
            'explainer_files_complete',
            'interaction_status_locked',
            'no_unresolved_design_gap_or_logic_conflict'
        ],
        blockOnMissing: true
    },
    fullPrdReady: {
        description: '进入 S3/S5 前，完整版 PRD 必须已形成',
        evidence: ['full_prd_exists'],
        blockOnMissing: true
    },
    foundationReadyForDevelopmentPlan: {
        description: '进入 S3 前，foundation-builder 的交付清单与其声明文件必须已准备好',
        evidence: ['foundation_delivery_exists', 'foundation_artifact_files_exist'],
        blockOnMissing: true
    },
    developmentPlanReady: {
        description: '进入 S4 前，开发计划必须存在、通过结构校验，并由 delivery-planner 完成计划状态一致性校验',
        evidence: ['development_plan_exists', 'development_plan_structure_valid', 'development_plan_status_consistent'],
        blockOnMissing: true
    },
    buildAvailableForValidation: {
        description: '进入 S5 前，当前版本需要具备可验证基础',
        evidence: ['build_or_feature_available'],
        blockOnMissing: true
    },
    testCasesReady: {
        description: '进入 S6 前，测试用例必须已准备好',
        evidence: ['test_case_files_exist'],
        blockOnMissing: true
    },
    securityScanReady: {
        description: '进入 S7 前，应至少具备测试执行证据，并已进入完工前安全闸门语境',
        evidence: ['test_execution_reports_exist', 'release_gate_signal_present'],
        blockOnMissing: true
    },
    stageWritebackBeforeRouting: {
        description: '当前阶段变化时，必须先完成阶段切换日志回写，再进入子能力',
        evidence: ['stage_transition_logged'],
        blockOnMissing: true
    },
    projectBaselineAuditReady: {
        description: '既有项目接入时，必须先读取或刷新 baseline-audit 清单再路由到补档 skill',
        evidence: ['baseline_audit_json_exists'],
        blockOnMissing: true
    }
};

const pagePositioningTagRules = [
    {
        when: {
            page_primary_purpose: ['业务处理']
        },
        result: '操作'
    },
    {
        when: {
            page_primary_purpose: ['系统管理']
        },
        result: '配置'
    },
    {
        when: {
            page_primary_purpose: ['内容展示']
        },
        result: '查看'
    }
];

export { routeTargets, gatingRules, pagePositioningTagRules };
