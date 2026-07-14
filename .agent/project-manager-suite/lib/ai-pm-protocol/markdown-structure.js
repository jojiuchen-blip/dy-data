/**
 * Traceability:
 * Rule sources:
 * - skills/00-01-ai-project-manager/references/core/runtime.md
 * Consumed by:
 * - tools/route-check.mjs
 */
import { FILE_ROLE_IDS } from './constants.js';

const markdownStructure = {
    [FILE_ROLE_IDS.PROFILE]: {
        sections: {
            basicInfo: '基本信息',
            collaboration: '身份识别',
            businessGoals: '业务目标',
            pageTask: '页面与任务定位',
            assets: '当前资产',
            entries: '项目入口与识别信息',
            judgment: '当前判断',
            pending: '待确认'
        },
        labels: {
            project_name: '项目名称',
            project_one_liner: '项目一句话目标',
            current_stage: '当前阶段',
            collaboration_mode: '协作模式',
            target_users: '目标使用者',
            main_problem: '主要问题',
            v1_core_goal: '第一版核心目标',
            coverage_scope: '项目覆盖对象',
            page_primary_user: '当前页面主要给谁用',
            page_primary_purpose: '当前页面主要用途',
            page_positioning_tag: '页面定位标签',
            recommended_stage: '当前最适合进入的阶段',
            current_round_deliverable: '当前轮应输出的交付物',
            largest_uncertainty: '当前最大不确定项',
            current_executor: '当前任务执行主体'
        }
    },
    [FILE_ROLE_IDS.PLAN]: {
        sections: {
            currentStage: '当前阶段',
            currentGoal: '当前目标',
            inProgress: '进行中任务',
            nextTasks: '下一步任务',
            completionCriteria: '完成标准',
            dependencies: '前置依赖',
            pending: '待确认项'
        }
    }
};

export { markdownStructure };
