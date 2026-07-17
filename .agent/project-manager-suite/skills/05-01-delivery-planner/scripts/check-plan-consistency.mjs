#!/usr/bin/env node

/**
 * check-plan-consistency.mjs
 *
 * Traceability:
 *   Rule sources:
 *     - skills/05-01-delivery-planner/SKILL.md (S4 前计划一致性校验)
 *     - skills/00-01-ai-project-manager/references/core/runtime.md (S4 调度门禁)
 *
 * Purpose:
 *   Check whether the formal delivery plan file group is internally
 *   consistent before ai-project-manager routes S4 work to coding-standards.
 *
 *   Active-task resolution (three-level source):
 *     1. Optional cockpit table in the main plan (a two-column "字段/内容"
 *        Markdown table with rows 当前活跃 Phase / Task and 当前子开发计划).
 *        When present it is read and cross-checked against the kanban.
 *     2. Otherwise the active task is derived from the task kanban row whose
 *        状态 is 进行中, plus the sub delivery plan linked from that row.
 *     3. When neither source yields an active task, an error is reported
 *        with concrete fix instructions.
 *
 * Usage:
 *   node check-plan-consistency.mjs <main-delivery-plan-file> [--json]
 *
 * Exit codes:
 *   0 – consistency checks passed
 *   1 – fatal error (file not found, unreadable, bad args)
 *   2 – consistency checks failed
 */

import fs from 'fs';
import path from 'path';
import process from 'process';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);

function printUsage() {
    console.log(
        'Usage: node <suite-path>/skills/05-01-delivery-planner/scripts/check-plan-consistency.mjs <main-delivery-plan-file> [--json]'
    );
}

function parseArgs(argv) {
    const args = argv.slice(2);
    const options = {
        planFile: '',
        json: false
    };

    for (const arg of args) {
        if (arg === '--json') {
            options.json = true;
            continue;
        }

        if (!options.planFile) {
            options.planFile = arg;
            continue;
        }

        throw new Error(`Unknown argument: ${arg}`);
    }

    if (!options.planFile) throw new Error('Missing <main-delivery-plan-file> argument.');
    return options;
}

function makeIssue(type, message, extra = {}) {
    return { type, message, ...extra };
}

function normalizePathTarget(target) {
    return target
        .split('#')[0]
        .trim()
        .replace(/^\.\/+/, '');
}

function normalizeInlineValue(rawValue) {
    return String(rawValue || '')
        .replace(/`/g, '')
        .replace(/<br\s*\/?>/gi, ' ')
        .replace(/\s+/g, ' ')
        .trim();
}

function resolveRelativeTo(baseDir, target) {
    if (path.isAbsolute(target)) return target;
    return path.resolve(baseDir, target);
}

function normalizePathForOutput(targetPath) {
    return targetPath ? path.resolve(targetPath) : null;
}

function parseMarkdownTables(content) {
    const lines = content.split('\n');
    const tables = [];
    let index = 0;

    while (index < lines.length) {
        const line = lines[index].trim();
        const separatorLine = lines[index + 1]?.trim() || '';

        if (!line.startsWith('|') || !separatorLine.startsWith('|')) {
            index += 1;
            continue;
        }

        const headers = splitTableLine(line);
        const separators = splitTableLine(separatorLine);
        if (
            headers.length === 0 ||
            headers.length !== separators.length ||
            !separators.every((cell) => /^:?-{3,}:?$/.test(cell.trim()))
        ) {
            index += 1;
            continue;
        }

        const rows = [];
        let rowIndex = index + 2;
        while (rowIndex < lines.length) {
            const rowLine = lines[rowIndex].trim();
            if (!rowLine.startsWith('|')) break;

            const cells = splitTableLine(rowLine);
            if (cells.length === headers.length) {
                rows.push(cells);
            }
            rowIndex += 1;
        }

        tables.push({ headers, rows, startLine: index + 1 });
        index = rowIndex;
    }

    return tables;
}

function splitTableLine(line) {
    return line
        .split('|')
        .slice(1, -1)
        .map((cell) => cell.trim());
}

function findColumn(headers, names) {
    return headers.findIndex((header) => names.includes(header.trim()));
}

function extractMarkdownTarget(rawValue, basenamePattern) {
    const text = String(rawValue || '');
    const candidates = [
        ...[...text.matchAll(/\[[^\]]+\]\(([^)]+\.md(?:#[^)]+)?)\)/g)].map((match) => match[1]),
        ...[...text.matchAll(/`([^`]+\.md(?:#[^`]*)?)`/g)].map((match) => match[1]),
        ...[...text.matchAll(/(?:^|\s)([^`\s|()]+\.md)(?:\s|$)/g)].map((match) => match[1])
    ];

    for (const target of candidates) {
        const normalized = normalizePathTarget(target);
        if (!basenamePattern || basenamePattern.test(path.basename(normalized))) {
            return normalized;
        }
    }

    return '';
}

function taskIdFromText(text) {
    return String(text || '').match(/\bT\d+\.\d+\b/)?.[0] || null;
}

function normalizeStatus(rawStatus) {
    const text = normalizeInlineValue(rawStatus);
    if (!text || text === '-') return '';
    if (text.includes('进行中')) return '进行中';
    if (text.includes('已完成')) return '已完成';
    if (text.includes('待审阅')) return '待审阅';
    if (text.includes('待开发')) return '待开发';
    if (text.includes('阻塞')) return '阻塞';
    return text;
}

function extractDate(rawValue) {
    return String(rawValue || '').match(/\b\d{4}-\d{2}-\d{2}\b/)?.[0] || '';
}

function extractCockpit(content) {
    const cockpit = {};

    // 驾驶舱表是可选结构：扫描主计划里所有「字段 | 内容」两列表，
    // 同名字段以先出现者为准（文档信息表与驾驶舱表并存时互不覆盖）。
    for (const table of parseMarkdownTables(content)) {
        const fieldIndex = findColumn(table.headers, ['字段']);
        const valueIndex = findColumn(table.headers, ['内容']);
        if (fieldIndex === -1 || valueIndex === -1) continue;

        for (const row of table.rows) {
            const key = normalizeInlineValue(row[fieldIndex]);
            if (!key || key in cockpit) continue;
            cockpit[key] = row[valueIndex] || '';
        }
    }

    return cockpit;
}

function extractTaskRowsFromTables(content, mode) {
    const tables = parseMarkdownTables(content);
    const tasks = [];

    for (const table of tables) {
        const taskIndex = findColumn(table.headers, ['Task', '任务']);
        const subPlanIndex = findColumn(table.headers, ['子开发计划', '子计划']);
        const statusIndex = findColumn(table.headers, ['状态']);
        const completionDateIndex = findColumn(table.headers, ['完成日期']);

        if (taskIndex === -1 || subPlanIndex === -1 || statusIndex === -1) {
            continue;
        }

        for (const row of table.rows) {
            const taskId = normalizeInlineValue(row[taskIndex]);
            if (!/^T\d+\.\d+$/.test(taskId)) continue;

            const rawStatus = row[statusIndex] || '';
            const rawCompletionDate = completionDateIndex === -1 ? '' : row[completionDateIndex] || '';
            const target = extractMarkdownTarget(row[subPlanIndex], /^sub-delivery-plan-.+\.md$/);
            tasks.push({
                taskId,
                mode,
                subPlanTarget: target,
                rawStatus,
                status: normalizeStatus(rawStatus),
                completionDate: extractDate(rawCompletionDate) || extractDate(rawStatus),
                sourceLine: row.join(' | ')
            });
        }
    }

    return tasks;
}

function extractTaskKanbanTarget(content) {
    for (const table of parseMarkdownTables(content)) {
        const fieldIndex = findColumn(table.headers, ['字段']);
        const valueIndex = findColumn(table.headers, ['内容']);
        if (fieldIndex === -1 || valueIndex === -1) continue;

        for (const row of table.rows) {
            if (normalizeInlineValue(row[fieldIndex]) === '当前任务看板') {
                const target = extractMarkdownTarget(row[valueIndex], /^task-kanban-.+\.md$/);
                if (target) return target;
            }
        }
    }

    return extractMarkdownTarget(content, /^task-kanban-.+\.md$/);
}

function extractSubPlanStatus(content) {
    const match = content.match(/\*\*状态\*\*[：:]\s*([^\n]+)/);
    return {
        rawStatus: match ? match[1].trim() : '',
        status: match ? normalizeStatus(match[1]) : ''
    };
}

function indexByTaskId(tasks) {
    const result = new Map();
    for (const task of tasks) {
        result.set(task.taskId, task);
    }
    return result;
}

function compareMainAndKanbanRows({ mainTasks, kanbanTasks, errors }) {
    const mainById = indexByTaskId(mainTasks);
    const kanbanById = indexByTaskId(kanbanTasks);
    const taskIds = [...new Set([...mainById.keys(), ...kanbanById.keys()])].sort();

    for (const taskId of taskIds) {
        const mainTask = mainById.get(taskId);
        const kanbanTask = kanbanById.get(taskId);
        if (!mainTask) {
            errors.push(makeIssue('missing_main_task_status', `${taskId} 出现在任务看板中，但主计划执行阶段表缺少该 Task`, { taskId }));
            continue;
        }
        if (!kanbanTask) {
            errors.push(makeIssue('missing_kanban_task_status', `${taskId} 出现在主计划执行阶段表中，但任务看板缺少该 Task`, { taskId }));
            continue;
        }

        if (mainTask.status !== kanbanTask.status) {
            errors.push(makeIssue(
                'main_kanban_status_mismatch',
                `${taskId} 主计划状态与任务看板状态不一致：主计划=${mainTask.rawStatus}，看板=${kanbanTask.rawStatus}`,
                { taskId, mainStatus: mainTask.status, kanbanStatus: kanbanTask.status }
            ));
        }

        if (mainTask.subPlanTarget && kanbanTask.subPlanTarget && mainTask.subPlanTarget !== kanbanTask.subPlanTarget) {
            errors.push(makeIssue(
                'main_kanban_sub_plan_mismatch',
                `${taskId} 主计划与任务看板指向的子开发计划不一致`,
                { taskId, mainSubPlanTarget: mainTask.subPlanTarget, kanbanSubPlanTarget: kanbanTask.subPlanTarget }
            ));
        }

        if (mainTask.status === '已完成' && kanbanTask.status === '已完成') {
            if (!mainTask.completionDate || !kanbanTask.completionDate) {
                errors.push(makeIssue(
                    'missing_completion_date',
                    `${taskId} 已完成，但主计划或任务看板缺少完成日期`,
                    { taskId, mainDate: mainTask.completionDate, kanbanDate: kanbanTask.completionDate }
                ));
            } else if (mainTask.completionDate !== kanbanTask.completionDate) {
                errors.push(makeIssue(
                    'completion_date_mismatch',
                    `${taskId} 完成日期不一致：主计划=${mainTask.completionDate}，看板=${kanbanTask.completionDate}`,
                    { taskId, mainDate: mainTask.completionDate, kanbanDate: kanbanTask.completionDate }
                ));
            }
        }
    }
}

function checkPlanConsistency({ planPath }) {
    const resolvedPlanPath = path.resolve(planPath || '');
    if (!planPath || !fs.existsSync(resolvedPlanPath)) {
        throw new Error(`Main delivery plan file does not exist: ${resolvedPlanPath}`);
    }

    const planDir = path.dirname(resolvedPlanPath);
    const mainContent = fs.readFileSync(resolvedPlanPath, 'utf8');
    const errors = [];
    const warnings = [];
    const cockpit = extractCockpit(mainContent);
    const mainTasks = extractTaskRowsFromTables(mainContent, 'main-plan');
    const kanbanTarget = extractTaskKanbanTarget(mainContent);
    const kanbanPath = kanbanTarget ? resolveRelativeTo(planDir, kanbanTarget) : '';
    let kanbanTasks = [];

    if (!kanbanTarget) {
        errors.push(makeIssue('missing_task_kanban', '主开发计划未声明当前任务看板或任务看板链接'));
    } else if (!fs.existsSync(kanbanPath)) {
        errors.push(makeIssue('missing_task_kanban', `任务看板文件不存在：${kanbanTarget}`, { target: kanbanTarget }));
    } else {
        kanbanTasks = extractTaskRowsFromTables(fs.readFileSync(kanbanPath, 'utf8'), 'task-kanban');
    }

    compareMainAndKanbanRows({ mainTasks, kanbanTasks, errors });

    const activeKanbanTasks = kanbanTasks.filter((task) => task.status === '进行中');
    const activeMainTasks = mainTasks.filter((task) => task.status === '进行中');
    let activeTask = activeKanbanTasks[0] || null;
    let activeSubPlanPath = null;
    let subPlanStatus = { rawStatus: '', status: '' };

    // 三级来源：驾驶舱表（可选，向后兼容）→ 任务看板「进行中」行推导 → 两者皆无则报错。
    const cockpitActiveTaskRaw = normalizeInlineValue(cockpit['当前活跃 Phase / Task'] || '');
    const cockpitSubPlanRaw = normalizeInlineValue(cockpit['当前子开发计划'] || '');
    const hasCockpit = Boolean(cockpitActiveTaskRaw || cockpitSubPlanRaw);
    const cockpitActiveTaskId = taskIdFromText(cockpitActiveTaskRaw);
    const cockpitSubPlanTarget = extractMarkdownTarget(cockpit['当前子开发计划'] || '', /^sub-delivery-plan-.+\.md$/);

    if (activeKanbanTasks.length === 0) {
        if (hasCockpit) {
            errors.push(makeIssue(
                'missing_active_task',
                '主计划驾驶舱声明了当前 Task，但任务看板中没有状态为「进行中」的 Task。修复方法：在任务看板将当前开工 Task 状态置为『进行中』，并同步主计划执行阶段表与子开发计划的状态'
            ));
        } else {
            errors.push(makeIssue(
                'missing_active_task',
                '无法确定当前活跃 Task：任务看板中没有状态为「进行中」的 Task，主计划也没有驾驶舱表。修复方法：在任务看板将当前开工 Task 状态置为『进行中』，或在主计划补驾驶舱表（字段：当前活跃 Phase / Task、当前子开发计划）'
            ));
        }
    } else if (activeKanbanTasks.length > 1) {
        errors.push(makeIssue(
            'multiple_active_tasks',
            `任务看板中存在多个进行中 Task：${activeKanbanTasks.map((task) => task.taskId).join(', ')}`,
            { taskIds: activeKanbanTasks.map((task) => task.taskId) }
        ));
        activeTask = activeKanbanTasks[0];
    }

    if (activeMainTasks.length > 1) {
        errors.push(makeIssue(
            'multiple_active_tasks',
            `主计划执行阶段表中存在多个进行中 Task：${activeMainTasks.map((task) => task.taskId).join(', ')}`,
            { taskIds: activeMainTasks.map((task) => task.taskId), source: 'main-plan' }
        ));
    }

    const activeTaskId = activeTask?.taskId || null;
    if (hasCockpit) {
        if (!cockpitActiveTaskId) {
            errors.push(makeIssue(
                'missing_cockpit_active_task',
                '主计划驾驶舱缺少当前活跃 Phase / Task 字段，或该字段中没有可识别的 Task 编号（应含 T<阶段>.<序号>，如 T1.2）'
            ));
        } else if (activeTaskId && cockpitActiveTaskId !== activeTaskId) {
            errors.push(makeIssue(
                'cockpit_active_task_mismatch',
                `主计划驾驶舱当前 Task 与任务看板进行中 Task 不一致：驾驶舱=${cockpitActiveTaskId}，看板=${activeTaskId}`,
                { cockpitTaskId: cockpitActiveTaskId, activeTaskId }
            ));
        }
    }

    if (activeTask && !activeTask.subPlanTarget) {
        errors.push(makeIssue(
            'missing_current_sub_plan',
            `${activeTask.taskId} 在任务看板中未链接子开发计划，无法确定当前子开发计划。修复方法：在该 Task 的看板行补上 sub-delivery-plan-<slug>-<TaskID>-<short-name>.md 链接`,
            { taskId: activeTask.taskId }
        ));
    }

    if (activeTask?.subPlanTarget) {
        activeSubPlanPath = resolveRelativeTo(planDir, activeTask.subPlanTarget);
        if (!fs.existsSync(activeSubPlanPath)) {
            errors.push(makeIssue(
                'missing_current_sub_plan',
                `当前进行中 Task 的子开发计划文件不存在：${activeTask.subPlanTarget}`,
                { taskId: activeTask.taskId, target: activeTask.subPlanTarget }
            ));
        } else {
            const subContent = fs.readFileSync(activeSubPlanPath, 'utf8');
            subPlanStatus = extractSubPlanStatus(subContent);
            if (!subPlanStatus.status) {
                errors.push(makeIssue(
                    'missing_current_sub_plan_status',
                    `${activeTask.taskId} 当前子开发计划缺少 **状态** 字段`,
                    { taskId: activeTask.taskId, subPlanPath: activeSubPlanPath }
                ));
            } else if (subPlanStatus.status !== activeTask.status) {
                errors.push(makeIssue(
                    'current_sub_plan_status_mismatch',
                    `${activeTask.taskId} 当前子开发计划状态与任务看板状态不一致：子计划=${subPlanStatus.rawStatus}，看板=${activeTask.rawStatus}`,
                    { taskId: activeTask.taskId, subPlanStatus: subPlanStatus.status, kanbanStatus: activeTask.status }
                ));
            }
        }
    }

    if (hasCockpit) {
        if (!cockpitSubPlanTarget) {
            errors.push(makeIssue('missing_cockpit_sub_plan', '主计划驾驶舱缺少当前子开发计划（应为 sub-delivery-plan-*.md 链接）'));
        } else if (activeTask?.subPlanTarget && cockpitSubPlanTarget !== activeTask.subPlanTarget) {
            errors.push(makeIssue(
                'cockpit_sub_plan_mismatch',
                `主计划驾驶舱当前子开发计划与任务看板进行中 Task 不一致：驾驶舱=${cockpitSubPlanTarget}，看板=${activeTask.subPlanTarget}`,
                { cockpitSubPlanTarget, activeSubPlanTarget: activeTask.subPlanTarget }
            ));
        }
    }

    return {
        passed: errors.length === 0,
        purpose: 's4_pre_coding_plan_consistency_check',
        activeTaskId,
        activeSubPlanPath: normalizePathForOutput(activeSubPlanPath),
        errors,
        warnings,
        sources: {
            mainPlan: {
                path: normalizePathForOutput(resolvedPlanPath),
                cockpitPresent: hasCockpit,
                cockpitActiveTaskId,
                cockpitSubPlanTarget: cockpitSubPlanTarget || null
            },
            taskKanban: {
                path: normalizePathForOutput(kanbanPath),
                activeTaskIds: activeKanbanTasks.map((task) => task.taskId)
            },
            subPlan: {
                path: normalizePathForOutput(activeSubPlanPath),
                status: subPlanStatus.status || null
            }
        }
    };
}

function formatReport(result) {
    const lines = ['=== check-plan-consistency ===', `Purpose: ${result.purpose}`, ''];
    lines.push(`Active Task: ${result.activeTaskId || 'UNKNOWN'}`);
    lines.push(`Active Sub Plan: ${result.activeSubPlanPath || 'UNKNOWN'}`);
    lines.push('');

    if (result.passed && result.warnings.length === 0) {
        lines.push('一致性校验通过');
        return lines.join('\n');
    }

    if (result.errors.length > 0) {
        lines.push(`错误 (${result.errors.length})`);
        for (const error of result.errors) {
            lines.push(`- ${error.message}`);
        }
        lines.push('');
    }

    if (result.warnings.length > 0) {
        lines.push(`警告 (${result.warnings.length})`);
        for (const warning of result.warnings) {
            lines.push(`- ${warning.message}`);
        }
    }

    return lines.join('\n').trimEnd();
}

function main() {
    const options = parseArgs(process.argv);
    const result = checkPlanConsistency({ planPath: options.planFile });

    if (options.json) {
        console.log(JSON.stringify(result, null, 2));
    } else {
        console.log(formatReport(result));
    }

    if (!result.passed) {
        process.exit(2);
    }
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
    try {
        main();
    } catch (error) {
        printUsage();
        console.error('\nError:', error.message);
        process.exit(1);
    }
}

export { checkPlanConsistency };
