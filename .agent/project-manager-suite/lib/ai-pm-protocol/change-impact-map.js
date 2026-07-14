/**
 * Traceability:
 * Rule sources:
 * - skills/00-01-ai-project-manager/references/core/runtime.md
 * - skills/00-01-ai-project-manager/references/core/routing.md
 * - skills/00-01-ai-project-manager/references/core/global-files-protocol.md
 * Consumed by:
 * - tools/check-protocol-alignment.mjs
 */

const changeImpactMap = {
    entryIdentity: {
        description: '主入口身份、默认第一入口定位、核心红线与上位边界',
        currentAuthority: ['skills/00-01-ai-project-manager/SKILL.md'],
        targetAuthority: ['lib/ai-pm-protocol/bootstrap.js', 'lib/bootstrap/index.js'],
        checkAlso: [
            'skills/00-01-ai-project-manager/references/core/runtime.md',
            'skills/00-01-ai-project-manager/references/core/routing.md',
            'lib/ai-pm-protocol/stages.js',
            'lib/ai-pm-protocol/routing.js',
            'tools/route-check.mjs'
        ]
    },
    startupInterview: {
        description: '首轮访谈的必问字段、追问条件、展示顺序与停机条件',
        currentAuthority: ['skills/00-01-ai-project-manager/references/core/runtime.md'],
        targetAuthority: ['lib/ai-pm-protocol/field-contracts.js'],
        checkAlso: [
            'skills/00-01-ai-project-manager/assets/global-files/project-profile.md',
            'tools/bootstrap-host.mjs',
            'tools/validate-global-files.mjs'
        ]
    },
    runtimeFlow: {
        description: '主入口 Step 0 到 Step 5 的执行顺序、脚本优先和回退条件',
        currentAuthority: ['skills/00-01-ai-project-manager/references/core/runtime.md'],
        targetAuthority: ['tools/route-check.mjs'],
        checkAlso: [
            'tools/devlog-sync.mjs',
            'hooks/session-start'
        ]
    },
    stageDefinitions: {
        description: '阶段定义、最小交付物与默认 owner skill（阶段门禁判定以 tools/route-check.mjs 为准）',
        currentAuthority: [
            'skills/00-01-ai-project-manager/references/core/runtime.md',
            'skills/00-01-ai-project-manager/references/core/routing.md'
        ],
        targetAuthority: ['lib/ai-pm-protocol/constants.js', 'lib/ai-pm-protocol/stages.js'],
        checkAlso: [
            'skills/00-01-ai-project-manager/assets/global-files/project-profile.md',
            'tools/route-check.mjs'
        ]
    },
    s2PageProtocol: {
        description: 'S2 页面先行协议、页面字段包门禁、确认后再进入 prd-writer 的条件',
        currentAuthority: ['skills/00-01-ai-project-manager/references/core/runtime.md'],
        targetAuthority: ['lib/ai-pm-protocol/routing.js'],
        checkAlso: [
            'lib/ai-pm-protocol/stages.js',
            'lib/ai-pm-protocol/field-contracts.js',
            'skills/00-01-ai-project-manager/assets/global-files/project-profile.md',
            'tools/route-check.mjs'
        ]
    },
    scaffoldPolicy: {
        description: '宿主根目录判定、基础骨架、阶段触发目录与安装迁移策略',
        currentAuthority: ['skills/00-01-ai-project-manager/references/core/routing.md'],
        targetAuthority: ['tools/bootstrap-host.mjs'],
        checkAlso: [
            'tools/generate-host-rules.mjs',
            'tools/install-suite-into-host.mjs'
        ]
    },
    profileFieldContracts: {
        description: '项目画像字段合同、字段级别、字段来源与字段包',
        currentAuthority: ['skills/00-01-ai-project-manager/references/core/global-files-protocol.md'],
        targetAuthority: ['lib/ai-pm-protocol/field-contracts.js'],
        checkAlso: [
            'skills/00-01-ai-project-manager/assets/global-files/project-profile.md',
            'tools/validate-global-files.mjs',
            'tools/route-check.mjs',
            'tools/bootstrap-host.mjs'
        ]
    },
    profileTemplate: {
        description: '项目画像模板的字段标签、章节落点与默认占位内容',
        currentAuthority: ['skills/00-01-ai-project-manager/assets/global-files/project-profile.md'],
        targetAuthority: ['skills/00-01-ai-project-manager/assets/global-files/project-profile.md'],
        checkAlso: [
            'lib/ai-pm-protocol/field-contracts.js',
            'lib/ai-pm-protocol/stages.js',
            'tools/bootstrap-host.mjs',
            'tools/route-check.mjs'
        ]
    }
};

export { changeImpactMap };
