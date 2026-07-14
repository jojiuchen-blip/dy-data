import { FILE_ROLE_IDS } from './constants.js';

const fileRoles = [
    {
        id: FILE_ROLE_IDS.RULES,
        defaultFileName: 'project-rules.md',
        defaultPath: 'project-rules.md',
        authorityType: 'file',
        responsibility: '项目怎么运行、权威入口在哪、必须遵守的技术和协作边界',
        forbiddenContent: ['single_round_task', 'current_round_status', 'process_log'],
        readBy: ['ai-project-manager', 'all-child-skills'],
        writtenBy: ['ai-project-manager', 'project-maintainer']
    },
    {
        id: FILE_ROLE_IDS.PROFILE,
        defaultFileName: 'project-profile.md',
        defaultPath: 'project-profile.md',
        authorityType: 'file',
        responsibility: '项目目标快照、协作模式、当前阶段、执行主体、待确认项',
        forbiddenContent: ['long_term_rules', 'detailed_task_list', 'development_log'],
        readBy: ['ai-project-manager', 'planning-skills', 'requirements-skills'],
        writtenBy: ['ai-project-manager']
    },
    {
        id: FILE_ROLE_IDS.PLAN,
        defaultFileName: 'execution-plan.md',
        defaultPath: 'docs/plans/execution-plan.md',
        authorityType: 'file',
        responsibility: '现在的目标、进行中任务、下一步任务、完成标准',
        forbiddenContent: ['long_term_rules', 'single_round_attachments', 'team_snapshot'],
        readBy: ['ai-project-manager', 'planning-skills', 'execution-skills', 'acceptance-skills'],
        writtenBy: ['ai-project-manager', 'planning-skills']
    },
    {
        id: FILE_ROLE_IDS.DEVLOG,
        defaultFileName: 'logs/YYYYMMDD_refactor_log_<actor>.md 或 logs/YYYY-MM-DD.md',
        defaultPath: 'logs/',
        authorityType: 'ability',
        responsibility: '沉淀本轮动作、产出、结论、风险和下一步建议',
        forbiddenContent: ['rewrite_profile_baseline', 'restate_full_history'],
        readBy: ['ai-project-manager', 'all-child-skills'],
        writtenBy: ['project-devlog', 'execution-unit']
    },
    {
        id: FILE_ROLE_IDS.LINK_INDEX,
        defaultFileName: 'project-link-graph.json',
        defaultPath: 'docs/index/project-link-graph.json',
        authorityType: 'compiled-index',
        responsibility: '文件级引用关系、坏链诊断、缺回链诊断和 LLM wiki 导航入口',
        forbiddenContent: ['business_rule_source_of_truth', 'stage_routing_decision', 'task_breakdown_or_test_execution'],
        readBy: ['ai-project-manager', 'all-child-skills'],
        writtenBy: ['project-link-indexer']
    }
];

export { fileRoles };
