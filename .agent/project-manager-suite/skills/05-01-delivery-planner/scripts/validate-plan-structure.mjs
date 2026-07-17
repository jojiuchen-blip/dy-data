#!/usr/bin/env node

/**
 * validate-plan-structure.mjs
 *
 * Traceability:
 *   Rule sources:
 *     - skills/05-01-delivery-planner/SKILL.md (Step 5 产出自检)
 *     - skills/05-01-delivery-planner/references/quality-gates.md
 *
 * Location:
 *   skills/05-01-delivery-planner/scripts/validate-plan-structure.mjs
 *   （delivery-planner 专属产出校验脚本）
 *
 * Purpose:
 *   Validate a delivery plan file group through its main delivery plan:
 *     - 13 required main-plan sections
 *     - 1:1 Task mapping across main plan, task kanban, and sub plans
 *     - 8 required Task fields per sub-plan task block
 *     - High-risk vague words detection
 *
 *   Outputs a structured validation report (JSON or human-readable).
 *
 * Usage:
 *   node <suite-path>/skills/05-01-delivery-planner/scripts/validate-plan-structure.mjs <main-delivery-plan-file> [--json]
 *
 * Exit codes:
 *   0 – all checks passed
 *   1 – fatal error (file not found, unreadable)
 *   2 – validation failed (missing sections or fields)
 */

import fs from 'fs';
import path from 'path';
import process from 'process';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);

// ─── Constants ───────────────────────────────────────────────────────────────

/**
 * The 13 required sections from the "完整执行计划协议".
 * Each entry is a regex that matches the expected heading.
 */
const REQUIRED_SECTIONS = [
    { id: 'meta',            label: '计划头部元信息',        pattern: /^(?:#+\s.*(?:版本|发布日期|适用范围|元信息)|>\s*\*\*(?:版本|发布日期|适用范围)\*\*)/m },
    { id: 'guide',           label: '本计划使用指南',        pattern: /^#+\s.*使用指南/m },
    { id: 'prd-constraint',  label: 'PRD 加载约束',         pattern: /^#+\s.*PRD\s*加载约束/m },
    { id: 'pre-gate',        label: '读前门禁 / AI 自检清单', pattern: /^#+\s.*(?:读前门禁|AI\s*自检)/m },
    { id: 'post-gate',       label: '完成前验证门禁',        pattern: /^#+\s.*完成前验证/m },
    { id: 'gap-baseline',    label: '差距基线',             pattern: /^#+\s.*差距基线/m },
    { id: 'roles',           label: '分工与边界',           pattern: /^#+\s.*分工与边界/m },
    { id: 'phases',          label: '执行阶段',             pattern: /^#+\s.*(?:执行阶段|Phase)/m },
    { id: 'kanban',          label: '任务看板',             pattern: /^#+\s.*任务看板/m },
    { id: 'release-gate',    label: '发布闸门',             pattern: /^#+\s.*发布闸门/m },
    { id: 'risks',           label: '风险与应对',           pattern: /^#+\s.*风险与应对/m },
    { id: 'ai-example',      label: 'AI 执行示例',          pattern: /^#+\s.*AI\s*执行示例/m },
    { id: 'prd-index',       label: 'PRD → 任务反向索引',    pattern: /^#+\s.*PRD\s*→?\s*任务反向索引/m },
];

/**
 * The 8 required Task fields.
 * We look for these as bold labels within task blocks.
 */
const REQUIRED_TASK_FIELDS = [
    { id: 'prd-link',    label: 'PRD 双链·读',  pattern: /\*\*PRD\s*双链[·.]?\s*读\*\*/ },
    { id: 'core-logic',  label: '核心逻辑',     pattern: /\*\*核心逻辑\*\*/ },
    { id: 'core-files',  label: '核心文件',     pattern: /\*\*核心文件\*\*/ },
    { id: 'done-criteria',label: '完成标准',    pattern: /\*\*完成标准\*\*/ },
    { id: 'closing-sync', label: '完成收尾：状态同步', pattern: /\*\*完成收尾[：:]\s*状态同步\*\*/ },
    { id: 'owner',       label: 'Owner',       pattern: /\*\*Owner\*\*/ },
    { id: 'dependency',  label: '前置',        pattern: /\*\*前置\*\*/ },
    { id: 'status',      label: '状态',        pattern: /\*\*状态\*\*/ },
];

/**
 * High-risk vague words that should NOT appear in completion criteria.
 */
const VAGUE_WORDS = [
    '数据完整',
    '配置补齐',
    '链路打通',
    '符合预期',
    '正常运行',
    '无明显问题',
    '基本可用',
];

// ─── Arg parsing ─────────────────────────────────────────────────────────────

function printUsage() {
    console.log(
        'Usage: node <suite-path>/skills/05-01-delivery-planner/scripts/validate-plan-structure.mjs <main-delivery-plan-file> [--json]'
    );
}

function parseArgs(argv) {
    const args = argv.slice(2);
    const options = {
        planFile: '',
        json: false,
    };

    for (const arg of args) {
        if (arg === '--json') { options.json = true; continue; }
        if (!options.planFile) { options.planFile = arg; continue; }
        throw new Error(`Unknown argument: ${arg}`);
    }

    if (!options.planFile) throw new Error('Missing <main-delivery-plan-file> argument.');
    return options;
}

// ─── Validation logic ────────────────────────────────────────────────────────

/**
 * Extract task blocks from the plan content.
 * A task block starts with a heading like "#### T0.1 ..." and ends
 * at the next heading of the same or higher level.
 */
function extractTaskBlocks(content) {
    const taskHeadingRe = /^(#{3,4})\s+(T\d+\.\d+)\s+(.+)$/gm;
    const blocks = [];
    let match;

    while ((match = taskHeadingRe.exec(content)) !== null) {
        blocks.push({
            id: match[2],
            title: match[3].trim(),
            startIndex: match.index,
            level: match[1].length,
        });
    }

    // Determine end index for each block
    for (let i = 0; i < blocks.length; i++) {
        const nextBlock = blocks[i + 1];
        blocks[i].endIndex = nextBlock ? nextBlock.startIndex : content.length;
        blocks[i].content = content.slice(blocks[i].startIndex, blocks[i].endIndex);
    }

    return blocks;
}

function makeError(type, message, extra = {}) {
    return { type, message, ...extra };
}

function normalizeMarkdownTarget(target) {
    return target
        .split('#')[0]
        .trim()
        .replace(/^\.\/+/, '');
}

function extractMarkdownLinks(content, basenamePattern) {
    const refs = [];
    const lines = content.split('\n');

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];

        for (const match of line.matchAll(/\[[^\]]+\]\(([^)]+\.md(?:#[^)]+)?)\)/g)) {
            const target = normalizeMarkdownTarget(match[1]);
            if (basenamePattern.test(path.basename(target))) {
                refs.push({ target, line: i + 1, sourceLine: line });
            }
        }

        for (const match of line.matchAll(/`([^`]+\.md(?:#[^`]*)?)`/g)) {
            const target = normalizeMarkdownTarget(match[1]);
            if (basenamePattern.test(path.basename(target))) {
                refs.push({ target, line: i + 1, sourceLine: line });
            }
        }
    }

    return refs;
}

function taskIdFromText(text) {
    return text.match(/\b(T\d+\.\d+)\b/)?.[1] || null;
}

function taskIdFromSubPlanPath(target) {
    return path.basename(target).match(/-(T\d+\.\d+)(?:-|\.md$)/)?.[1] || null;
}

function resolveRelativeTo(baseDir, target) {
    if (path.isAbsolute(target)) return target;
    return path.resolve(baseDir, target);
}

function toComparableSet(items) {
    return new Set(items.filter(Boolean));
}

function diffSets(left, right) {
    return [...left].filter((item) => !right.has(item)).sort();
}

function extractMainSubPlanRefs(content) {
    return extractMarkdownLinks(content, /^sub-delivery-plan-.+\.md$/).map((ref) => ({
        ...ref,
        taskId: taskIdFromText(ref.sourceLine) || taskIdFromSubPlanPath(ref.target),
    }));
}

function extractKanbanTasks(content) {
    const tasks = [];
    const lines = content.split('\n');

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line.startsWith('|') || /^(\|\s*-+\s*)+\|?$/.test(line)) continue;

        const cells = line
            .split('|')
            .slice(1, -1)
            .map((cell) => cell.trim());

        if (cells.length === 0 || !/^T\d+\.\d+$/.test(cells[0])) continue;

        const link = line.match(/\[[^\]]+\]\(([^)]*sub-delivery-plan-[^)]+\.md)\)/)
            || line.match(/`([^`]*sub-delivery-plan-[^`]+\.md)`/);
        tasks.push({
            taskId: cells[0],
            target: link ? normalizeMarkdownTarget(link[1]) : '',
            line: i + 1,
            sourceLine: lines[i],
        });
    }

    return tasks;
}

function validatePlanLocation(planPath) {
    const errors = [];

    if (!planPath) {
        errors.push(makeError(
            'invalid_plan_location',
            '结构校验入口必须是 docs/plans/delivery-plans/main-delivery-plan-<slug>.md'
        ));
        return errors;
    }

    const basename = path.basename(planPath);
    const parent = path.basename(path.dirname(planPath));
    if (parent !== 'delivery-plans' || !/^main-delivery-plan-.+\.md$/.test(basename)) {
        errors.push(makeError(
            'invalid_plan_location',
            '正式开发计划入口必须是 docs/plans/delivery-plans/main-delivery-plan-<slug>.md',
            { planPath }
        ));
    }

    return errors;
}

function validateSections(content) {
    const errors = [];
    const found = [];

    for (const section of REQUIRED_SECTIONS) {
        if (section.pattern.test(content)) {
            found.push(section.id);
        } else {
            errors.push({
                type: 'missing_section',
                sectionId: section.id,
                label: section.label,
                message: `缺少必需章节：${section.label}`,
            });
        }
    }

    return { errors, found };
}

function validateTaskFields(blocks) {
    const errors = [];
    const warnings = [];

    if (blocks.length === 0) {
        errors.push({
            type: 'no_tasks',
            message: '未找到任何 Task 块（格式应为 ### T0.1 或 #### T0.1）',
        });
        return { errors, warnings };
    }

    for (const block of blocks) {
        for (const field of REQUIRED_TASK_FIELDS) {
            if (!field.pattern.test(block.content)) {
                errors.push({
                    type: 'missing_task_field',
                    taskId: block.id,
                    taskTitle: block.title,
                    fieldId: field.id,
                    fieldLabel: field.label,
                    message: `${block.id} 缺少必填字段：${field.label}`,
                });
            }
        }

        // Check for vague words in completion criteria section
        const doneSection = block.content.match(/\*\*完成标准\*\*[：:]\s*([\s\S]*?)(?=\*\*|$)/);
        if (doneSection) {
            for (const word of VAGUE_WORDS) {
                if (doneSection[1].includes(word)) {
                    warnings.push({
                        type: 'vague_completion_criteria',
                        taskId: block.id,
                        word,
                        message: `${block.id} 的完成标准中包含高风险模糊词「${word}」`,
                    });
                }
            }
        }
    }

    return { errors, warnings };
}

function validatePlan(content, options = {}) {
    const planPath = options.planPath ? path.resolve(options.planPath) : '';
    const locationErrors = validatePlanLocation(planPath);
    const sectionResult = validateSections(content);
    const baseDir = planPath ? path.dirname(planPath) : process.cwd();
    const kanbanRefs = extractMarkdownLinks(content, /^task-kanban-.+\.md$/);
    const mainSubRefs = extractMainSubPlanRefs(content);
    const errors = [...locationErrors, ...sectionResult.errors];
    const warnings = [];

    if (kanbanRefs.length === 0) {
        errors.push(makeError(
            'missing_task_kanban',
            '主开发计划必须链接独立任务看板：task-kanban-<slug>.md'
        ));
    }

    if (mainSubRefs.length === 0) {
        errors.push(makeError(
            'missing_sub_delivery_plan_index',
            '主开发计划的执行阶段必须以索引形式链接 sub-delivery-plan-<slug>-<TaskID>-<short-name>.md'
        ));
    }

    const kanbanPath = kanbanRefs[0] ? resolveRelativeTo(baseDir, kanbanRefs[0].target) : '';
    let kanbanTasks = [];
    if (kanbanPath) {
        if (!fs.existsSync(kanbanPath)) {
            errors.push(makeError(
                'missing_task_kanban',
                `任务看板文件不存在：${kanbanRefs[0].target}`,
                { target: kanbanRefs[0].target }
            ));
        } else {
            const kanbanContent = fs.readFileSync(kanbanPath, 'utf8');
            kanbanTasks = extractKanbanTasks(kanbanContent);
            if (kanbanTasks.length === 0) {
                errors.push(makeError('no_kanban_tasks', '任务看板未列出任何 Task 行'));
            }
        }
    }

    for (const task of kanbanTasks) {
        if (!task.target) {
            errors.push(makeError(
                'missing_sub_delivery_plan',
                `任务看板中的 ${task.taskId} 未链接子开发计划`,
                { taskId: task.taskId }
            ));
        }
    }

    const mainTaskIds = toComparableSet(mainSubRefs.map((ref) => ref.taskId));
    const kanbanTaskIds = toComparableSet(kanbanTasks.map((task) => task.taskId));
    for (const taskId of diffSets(mainTaskIds, kanbanTaskIds)) {
        errors.push(makeError(
            'missing_kanban_task',
            `主开发计划索引中的 ${taskId} 未出现在任务看板中`,
            { taskId }
        ));
    }
    for (const taskId of diffSets(kanbanTaskIds, mainTaskIds)) {
        errors.push(makeError(
            'missing_main_task_index',
            `任务看板中的 ${taskId} 未出现在主开发计划索引中`,
            { taskId }
        ));
    }

    const subRefByTask = new Map();
    for (const ref of [...mainSubRefs, ...kanbanTasks]) {
        const taskId = ref.taskId;
        if (!taskId) {
            errors.push(makeError(
                'missing_task_id_for_sub_delivery_plan',
                `无法从子开发计划引用中识别 Task ID：${ref.target}`,
                { target: ref.target }
            ));
            continue;
        }
        if (!subRefByTask.has(taskId)) {
            subRefByTask.set(taskId, ref.target);
            continue;
        }
        if (subRefByTask.get(taskId) !== ref.target) {
            errors.push(makeError(
                'sub_delivery_plan_mismatch',
                `${taskId} 在主计划和任务看板中指向的子开发计划不一致`,
                { taskId, expected: subRefByTask.get(taskId), actual: ref.target }
            ));
        }
    }

    const subTaskBlocks = [];
    const subPlanPaths = [];
    for (const [taskId, target] of subRefByTask) {
        const subPath = resolveRelativeTo(baseDir, target);
        if (!fs.existsSync(subPath)) {
            errors.push(makeError(
                'missing_sub_delivery_plan',
                `${taskId} 指向的子开发计划文件不存在：${target}`,
                { taskId, target }
            ));
            continue;
        }

        const subContent = fs.readFileSync(subPath, 'utf8');
        const blocks = extractTaskBlocks(subContent);
        const matchingBlocks = blocks.filter((block) => block.id === taskId);
        subPlanPaths.push(subPath);

        if (blocks.length !== 1 || matchingBlocks.length !== 1) {
            errors.push(makeError(
                'sub_delivery_plan_task_count_invalid',
                `${target} 必须且只能包含 ${taskId} 这一个 Task 块`,
                { taskId, target, taskCount: blocks.length }
            ));
            continue;
        }

        subTaskBlocks.push(...matchingBlocks);
    }

    const subTaskIds = toComparableSet(subTaskBlocks.map((block) => block.id));
    for (const taskId of diffSets(kanbanTaskIds, subTaskIds)) {
        if (!errors.some((error) => error.type === 'missing_sub_delivery_plan' && error.taskId === taskId)) {
            errors.push(makeError(
                'missing_sub_delivery_plan',
                `任务看板中的 ${taskId} 没有可校验的子开发计划 Task 块`,
                { taskId }
            ));
        }
    }

    const taskResult = validateTaskFields(subTaskBlocks);
    const allErrors = [...errors, ...taskResult.errors];
    const allWarnings = [...warnings, ...taskResult.warnings];

    return {
        passed: allErrors.length === 0,
        mode: 'multi-file',
        planPath: planPath || null,
        kanbanPath: kanbanPath || null,
        subPlanPaths,
        totalSectionsFound: sectionResult.found.length,
        totalSectionsRequired: REQUIRED_SECTIONS.length,
        totalTasksFound: subTaskBlocks.length,
        errors: allErrors,
        warnings: allWarnings,
        summary: {
            missingSections: sectionResult.errors.length,
            missingTaskFields: taskResult.errors.filter((e) => e.type === 'missing_task_field').length,
            missingSubDeliveryPlans: allErrors.filter((e) => e.type === 'missing_sub_delivery_plan').length,
            vagueWords: allWarnings.filter((w) => w.type === 'vague_completion_criteria').length,
        },
    };
}

// ─── Text formatter ──────────────────────────────────────────────────────────

function formatReport(result) {
    const lines = [];

    lines.push('=== validate-plan-structure ===');
    if (result.mode) lines.push(`模式: ${result.mode}`);
    lines.push(`章节: ${result.totalSectionsFound}/${result.totalSectionsRequired} | Task: ${result.totalTasksFound}`);
    lines.push('');

    if (result.passed && result.warnings.length === 0) {
        lines.push('✅ 全部通过');
        return lines.join('\n');
    }

    if (result.errors.length > 0) {
        lines.push(`── ❌ 错误 (${result.errors.length}) ──`);
        for (const e of result.errors) {
            lines.push(`  • ${e.message}`);
        }
        lines.push('');
    }

    if (result.warnings.length > 0) {
        lines.push(`── ⚠️  警告 (${result.warnings.length}) ──`);
        for (const w of result.warnings) {
            lines.push(`  • ${w.message}`);
        }
        lines.push('');
    }

    lines.push('── 结论 ──');
    if (result.passed) {
        lines.push('  ⚠️  结构通过，但存在警告项，建议修正');
    } else {
        lines.push('  ❌ 校验失败：请先修正以上错误再宣称计划完成');
    }

    return lines.join('\n');
}

// ─── Main ────────────────────────────────────────────────────────────────────

function main() {
    const options = parseArgs(process.argv);

    const planFile = path.resolve(options.planFile);
    if (!fs.existsSync(planFile)) {
        throw new Error(`Plan file does not exist: ${planFile}`);
    }

    const content = fs.readFileSync(planFile, 'utf8');
    const result = validatePlan(content, { planPath: planFile });

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
    } catch (err) {
        printUsage();
        console.error('\nError:', err.message);
        process.exit(1);
    }
}

export { validatePlan };
