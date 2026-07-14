/**
 * Traceability:
 * Rule sources:
 * - skills/00-01-ai-project-manager/references/core/global-files-protocol.md
 * Consumed by:
 * - tools/validate-global-files.mjs
 * - tools/route-check.mjs
 *
 * Change impact:
 * - If startupMinimum or pageTaskRequired changes, also check:
 *   - skills/00-01-ai-project-manager/assets/global-files/project-profile.md
 *   - tools/validate-global-files.mjs
 *   - tools/route-check.mjs
 *   - tools/bootstrap-host.mjs
 */
import { FIELD_LEVELS, FIELD_SOURCES, FILE_ROLE_IDS } from './constants.js';

const fieldPackages = {
    startupMinimum: [
        'project_name',
        'project_one_liner',
        'target_users',
        'main_problem'
    ],
    identity: ['identity_policy'],
    pageTaskRequired: [
        'coverage_scope',
        'page_primary_user',
        'page_primary_purpose',
        'page_positioning_tag'
    ],
    runtimeWriteback: [
        'current_stage',
        'recommended_stage',
        'current_round_deliverable',
        'current_executor',
        'largest_uncertainty'
    ]
};

const fileContracts = {
    [FILE_ROLE_IDS.RULES]: [
        {
            key: 'authority_entries',
            label: '规则权威文件 / 计划权威文件 / 状态回写权威文件',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.SYSTEM_INFERRED
        },
        {
            key: 'requires_round_artifacts',
            label: '是否要求每轮沉淀交付物',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.SYSTEM_INFERRED
        },
        {
            key: 'collaboration_boundaries',
            label: '协作边界（长期有效）',
            level: FIELD_LEVELS.OPTIONAL,
            source: FIELD_SOURCES.USER_CONFIRMED
        },
        {
            key: 'other_entries_and_structure',
            label: '其他入口 / 核心目录结构 / 文档代码边界',
            level: FIELD_LEVELS.OPTIONAL,
            source: FIELD_SOURCES.SYSTEM_INFERRED
        },
        {
            key: 'default_language_and_communication',
            label: '默认工作语言 / 默认沟通方式',
            level: FIELD_LEVELS.INFERRED,
            source: FIELD_SOURCES.SYSTEM_INFERRED
        }
    ],
    [FILE_ROLE_IDS.PROFILE]: [
        {
            key: 'project_name',
            label: '项目名称',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.USER_CONFIRMED
        },
        {
            key: 'project_one_liner',
            label: '项目一句话目标',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.USER_CONFIRMED
        },
        {
            key: 'target_users',
            label: '目标使用者',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.USER_CONFIRMED
        },
        {
            key: 'main_problem',
            label: '主要问题',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.USER_CONFIRMED
        },
        {
            key: 'collaboration_mode',
            label: '协作模式',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.SYSTEM_INFERRED
        },
        {
            key: 'coverage_scope',
            label: '项目覆盖对象',
            level: FIELD_LEVELS.OPTIONAL,
            source: FIELD_SOURCES.USER_CONFIRMED,
            requiredWhen: ['page_task']
        },
        {
            key: 'page_primary_user',
            label: '当前页面主要给谁用',
            level: FIELD_LEVELS.OPTIONAL,
            source: FIELD_SOURCES.USER_CONFIRMED,
            requiredWhen: ['page_task']
        },
        {
            key: 'page_primary_purpose',
            label: '当前页面主要用途',
            level: FIELD_LEVELS.OPTIONAL,
            source: FIELD_SOURCES.USER_CONFIRMED,
            requiredWhen: ['page_task']
        },
        {
            key: 'page_positioning_tag',
            label: '页面定位标签',
            level: FIELD_LEVELS.OPTIONAL,
            source: FIELD_SOURCES.PM_WRITTEN,
            requiredWhen: ['page_task']
        },
        {
            key: 'v1_core_goal',
            label: '第一版核心目标',
            level: FIELD_LEVELS.OPTIONAL,
            source: FIELD_SOURCES.USER_CONFIRMED
        },
        {
            key: 'current_stage',
            label: '当前阶段',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'recommended_stage',
            label: '当前最适合进入的阶段',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'current_round_deliverable',
            label: '当前轮应输出的交付物',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'current_executor',
            label: '当前任务执行主体',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'v1_scope',
            label: '第一版范围',
            level: FIELD_LEVELS.OPTIONAL,
            source: FIELD_SOURCES.USER_CONFIRMED
        },
        {
            key: 'largest_uncertainty',
            label: '当前最大不确定项',
            level: FIELD_LEVELS.OPTIONAL,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'pending_items',
            label: '待确认项',
            level: FIELD_LEVELS.OPTIONAL,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'identity_policy',
            label: '身份识别口径',
            level: FIELD_LEVELS.INFERRED,
            source: FIELD_SOURCES.SYSTEM_INFERRED
        },
        {
            key: 'existing_assets_and_entries',
            label: '已有文档、原型、材料清单 / 规则入口 / 计划入口 / 状态入口 / PRD 入口',
            level: FIELD_LEVELS.INFERRED,
            source: FIELD_SOURCES.SYSTEM_INFERRED
        }
    ],
    [FILE_ROLE_IDS.PLAN]: [
        {
            key: 'current_stage',
            label: '当前阶段',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'current_goal',
            label: '当前目标',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'in_progress_tasks',
            label: '进行中任务（当前活跃 Phase / Task）',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'next_tasks',
            label: '下一步任务',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'completion_criteria',
            label: '完成标准（完成标准摘要）',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'official_plan_group',
            label: '当前正式计划文件组（若未生成则写 待生成）',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'active_sub_plan',
            label: '当前子开发计划',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'dependencies',
            label: '前置依赖',
            level: FIELD_LEVELS.OPTIONAL,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'pending_items',
            label: '待确认项',
            level: FIELD_LEVELS.OPTIONAL,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'milestones_and_order',
            label: '当前阶段里程碑 / 任务执行顺序',
            level: FIELD_LEVELS.OPTIONAL,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'inferred_dependencies_and_priority',
            label: '部分可推断前置依赖 / 任务优先级 / 可并行任务',
            level: FIELD_LEVELS.INFERRED,
            source: FIELD_SOURCES.SYSTEM_INFERRED
        }
    ],
    [FILE_ROLE_IDS.DEVLOG]: [
        {
            key: 'round_time',
            label: '本轮时间',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'round_actions',
            label: '本轮动作',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'round_outputs',
            label: '本轮产出',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'current_conclusion',
            label: '当前结论',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'next_suggestions',
            label: '下一步建议',
            level: FIELD_LEVELS.REQUIRED,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'risks_and_blockers',
            label: '风险与阻塞',
            level: FIELD_LEVELS.OPTIONAL,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'pending_items',
            label: '待确认项',
            level: FIELD_LEVELS.OPTIONAL,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'round_decisions',
            label: '本轮决策',
            level: FIELD_LEVELS.OPTIONAL,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'acceptance_conclusion',
            label: '本轮验收结论',
            level: FIELD_LEVELS.OPTIONAL,
            source: FIELD_SOURCES.PM_WRITTEN
        },
        {
            key: 'touched_files_stage_executor',
            label: '本轮涉及文件 / 本轮关联阶段 / 本轮执行主体',
            level: FIELD_LEVELS.INFERRED,
            source: FIELD_SOURCES.SYSTEM_INFERRED
        }
    ]
};

export { fieldPackages, fileContracts };
