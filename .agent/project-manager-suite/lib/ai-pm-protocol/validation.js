/**
 * Traceability:
 * Rule sources:
 * - skills/00-01-ai-project-manager/references/core/global-files-protocol.md
 * - skills/00-01-ai-project-manager/assets/global-files/*.md
 * Consumed by:
 * - tools/validate-global-files.mjs
 */
import { FILE_ROLE_IDS } from './constants.js';

const validationPolicy = {
    scan: {
        maxDepth: 5,
        includeExtensions: ['.md'],
        ignoredDirectories: [
            '.git',
            'node_modules',
            '.next',
            'dist',
            'build',
            '.idea',
            '.vscode',
            '.agent/project-manager-suite',
            'project-manager-suite'
        ]
    },
    roles: {
        [FILE_ROLE_IDS.RULES]: {
            minimumScore: 3,
            duplicateThresholdDelta: 1,
            filenameMatchers: ['project-rules.md', 'rules.md'],
            pathMatchers: ['project-rules.md', 'docs/rules.md'],
            contentMarkers: [
                '# 项目全局规则',
                '## 1. 规则入口与引用约定',
                '## 2. 项目结构约定',
                '## 3. 工作方式约定'
            ],
            requiredMarkers: [
                '## 1. 规则入口与引用约定',
                '## 2. 项目结构约定',
                '## 3. 工作方式约定',
                '## 6. 交付件要求',
                '## 7. AI 协作规则'
            ]
        },
        [FILE_ROLE_IDS.PROFILE]: {
            minimumScore: 3,
            duplicateThresholdDelta: 1,
            filenameMatchers: ['project-profile.md'],
            pathMatchers: ['project-profile.md'],
            contentMarkers: [
                '# 项目画像',
                '项目一句话目标：',
                '目标使用者：',
                '当前阶段：'
            ],
            requiredMarkers: [
                '项目名称：',
                '项目一句话目标：',
                '目标使用者：',
                '主要问题：',
                '协作模式：',
                '当前阶段：',
                '当前最适合进入的阶段：',
                '当前轮应输出的交付物：',
                '当前任务执行主体：'
            ]
        },
        [FILE_ROLE_IDS.PLAN]: {
            minimumScore: 3,
            duplicateThresholdDelta: 1,
            filenameMatchers: ['execution-plan.md'],
            pathMatchers: ['docs/plans/execution-plan.md', 'execution-plan.md'],
            contentMarkers: [
                '# 当前执行计划',
                '## 1. 当前阶段',
                '## 2. 当前目标',
                '## 5. 完成标准'
            ],
            requiredMarkers: [
                '## 1. 当前阶段',
                '## 2. 当前目标',
                '## 3. 进行中任务',
                '## 4. 下一步任务',
                '## 5. 完成标准',
                // 以下两项不锁章节序号：该章节位于可选章节之后，序号可能因增减而变化
                '当前正式计划文件组',
                '当前子开发计划：'
            ]
        },
        [FILE_ROLE_IDS.DEVLOG]: {
            filenameMatchers: [],
            defaultPath: 'logs/',
            logFilePattern: '^(?:\\d{8}_.+|\\d{4}-\\d{2}-\\d{2})\\.md$'
        }
    }
};

export { validationPolicy };
