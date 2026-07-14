#!/usr/bin/env node

/**
 * verify-task-context.mjs
 *
 * Traceability:
 *   Rule sources:
 *     - skills/06-01-coding-standards/SKILL.md (执行前置协议)
 *     - PIPELINE.md §7 coding-standards
 *
 * Location:
 *   skills/06-01-coding-standards/scripts/verify-task-context.mjs
 *
 * Purpose:
 *   Before coding-standards starts implementing a Task, verify that:
 *     1. The Task exists in the delivery plan file group
 *     2. All files referenced in the Task's "PRD双链·读" field actually exist on disk
 *     3. The Task's "核心文件" field is declared (non-empty)
 *   OR check environment readiness if --env-check is passed.
 *
 *   Outputs a structured report (JSON or human-readable).
 *
 * Usage:
 *   node <suite-path>/skills/06-01-coding-standards/scripts/verify-task-context.mjs \
 *     <main-delivery-plan-path> <task-id> [--json] [--env-check]
 *
 * Exit codes:
 *   0 – canExecute/envReady: true (all checks passed)
 *   1 – fatal error (file not found, bad args)
 *   2 – canExecute/envReady: false (checks failed)
 */

import fs from 'fs';
import path from 'path';
import process from 'process';
import { execSync } from 'child_process';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);

// ─── Arg parsing ─────────────────────────────────────────────────────────────

function printUsage() {
    console.log(
        'Usage: node verify-task-context.mjs <main-delivery-plan-path> <task-id> [--json] [--env-check] [--docs-dir <rel-path>]'
    );
}

function parseArgs(argv) {
    const args = argv.slice(2);
    // docsDir 默认 docs/prd，与 delivery-planner 的 collect-upstream-context.mjs 保持同一口径。
    const options = { planFile: '', taskId: '', json: false, envCheck: false, docsDir: 'docs/prd' };

    for (let i = 0; i < args.length; i++) {
        const arg = args[i];
        if (arg === '--json') { options.json = true; continue; }
        if (arg === '--env-check') { options.envCheck = true; continue; }
        if (arg === '--docs-dir') {
            const next = args[i + 1];
            if (!next) throw new Error('Missing value for --docs-dir');
            options.docsDir = next;
            i++;
            continue;
        }
        if (!options.planFile) { options.planFile = arg; continue; }
        if (!options.taskId) { options.taskId = arg; continue; }
        throw new Error(`Unknown argument: ${arg}`);
    }

    if (!options.planFile) throw new Error('Missing <main-delivery-plan-path> argument.');
    if (!options.taskId) throw new Error('Missing <task-id> argument.');
    return options;
}

// ─── Environment Verification (--env-check) ──────────────────────────────────

function extractEnvDeclarations(content) {
    const lines = content.split('\n');
    const cmds = [];
    const dirs = [];

    let inBlock = false;
    for (const line of lines) {
        if (line.includes('## 环境依赖声明') || line.includes('### 环境依赖声明')) {
            inBlock = true;
            continue;
        }
        if (inBlock && line.startsWith('## ') && !line.includes('环境依赖声明')) {
            break;
        }
        if (!inBlock) continue;

        // Matches markdown table lines: | Node.js | >= 18 | `node -v` | ... |
        const cmdMatch = line.match(/\|\s*[^|]+\s*\|\s*[^|]+\s*\|\s*`([^`]+)`\s*\|/);
        if (cmdMatch) {
            cmds.push({ raw: line, cmd: cmdMatch[1].trim() });
            continue;
        }

        // Matches path table lines: | `<前端工程目录>/` | `node_modules/` 存在 ... |
        const dirMatch = line.match(/\|\s*`([^`]+)`\s*\|\s*[^\s|]*?(`([^`]+)`|([a-zA-Z0-9_\-\./]+))\s*(存在|已就绪)/);
        if (dirMatch) {
            const dir = dirMatch[1].replace(/<|>/g, '');
            const required = (dirMatch[3] || dirMatch[4]).replace(/<|>/g, '');
            dirs.push({ raw: line, targetDir: dir, requiredItem: required });
        }
    }
    return { cmds, dirs };
}

function verifyEnv(planFile) {
    const planPath = path.resolve(planFile);
    if (!fs.existsSync(planPath)) {
        throw new Error(`Delivery plan file does not exist: ${planPath}`);
    }
    const content = fs.readFileSync(planPath, 'utf8');
    const declarations = extractEnvDeclarations(content);

    // If no declarations found, still pass (envReady: true) but emit a warning:
    // "0 条声明" 可能是计划确实无环境依赖，也可能是表格格式不符合可解析约定，
    // 静默放行会把"格式没写对"伪装成"环境已就绪"。
    if (declarations.cmds.length === 0 && declarations.dirs.length === 0) {
        return {
            envReady: true,
            missingEnv: [],
            warnings: [
                '主开发计划中没有解析到任何环境依赖声明（0 条）。若计划写了「环境依赖声明」章节，请核对表格格式是否符合 delivery-planner/references/plan-anatomy.md 的可解析示例；确无环境依赖时可忽略本警告。',
            ],
        };
    }

    const missingEnv = [];

    for (const { cmd, raw } of declarations.cmds) {
        try {
            execSync(cmd, { stdio: 'ignore' });
        } catch (e) {
            missingEnv.push(`命令执行失败: ${cmd} (依赖项: ${raw.split('|')[1]?.trim()})`);
        }
    }

    const planDir = path.dirname(planPath);
    for (const { targetDir, requiredItem } of declarations.dirs) {
        // Just checking if we can find it relative to host dir
        const hostDir = resolveHostRoot(planDir);
        const resolvedPath = path.resolve(hostDir, targetDir, requiredItem);
        if (!fs.existsSync(resolvedPath)) {
            missingEnv.push(`缺失工程依赖: ${path.join(targetDir, requiredItem)} 未找到。`);
        }
    }

    return {
        envReady: missingEnv.length === 0,
        missingEnv,
        warnings: [],
    };
}

// ─── Task extraction ─────────────────────────────────────────────────────────

function extractTaskBlock(content, taskId) {
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

    for (let i = 0; i < blocks.length; i++) {
        const next = blocks[i + 1];
        blocks[i].endIndex = next ? next.startIndex : content.length;
        blocks[i].content = content.slice(blocks[i].startIndex, blocks[i].endIndex);
    }

    return blocks.find((b) => b.id === taskId) || null;
}

function resolveHostRoot(planDir) {
    if (
        path.basename(planDir) === 'delivery-plans' &&
        path.basename(path.dirname(planDir)) === 'plans' &&
        path.basename(path.dirname(path.dirname(planDir))) === 'docs'
    ) {
        return path.resolve(planDir, '..', '..', '..');
    }

    return path.resolve(planDir, '..', '..');
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

    for (const line of lines) {
        for (const match of line.matchAll(/\[[^\]]+\]\(([^)]+\.md(?:#[^)]+)?)\)/g)) {
            const target = normalizeMarkdownTarget(match[1]);
            if (basenamePattern.test(path.basename(target))) {
                refs.push(target);
            }
        }
        for (const match of line.matchAll(/`([^`]+\.md(?:#[^`]*)?)`/g)) {
            const target = normalizeMarkdownTarget(match[1]);
            if (basenamePattern.test(path.basename(target))) {
                refs.push(target);
            }
        }
    }

    return [...new Set(refs)];
}

function resolveRelativeTo(baseDir, target) {
    if (path.isAbsolute(target)) return target;
    return path.resolve(baseDir, target);
}

function findTaskInKanban(kanbanContent, taskId) {
    const lines = kanbanContent.split('\n');

    for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('|') || !trimmed.includes(taskId)) continue;

        const cells = trimmed
            .split('|')
            .slice(1, -1)
            .map((cell) => cell.trim());
        if (cells[0] !== taskId) continue;

        const link = trimmed.match(/\[[^\]]+\]\(([^)]*sub-delivery-plan-[^)]+\.md)\)/)
            || trimmed.match(/`([^`]*sub-delivery-plan-[^`]+\.md)`/);
        if (!link) return { taskId, subPlanTarget: '' };

        return { taskId, subPlanTarget: normalizeMarkdownTarget(link[1]) };
    }

    return null;
}

function isMainDeliveryPlan(planPath) {
    return (
        path.basename(path.dirname(planPath)) === 'delivery-plans' &&
        /^main-delivery-plan-.+\.md$/.test(path.basename(planPath))
    );
}

function resolveTaskSource(planPath, content, taskId) {
    const planDir = path.dirname(planPath);

    if (!isMainDeliveryPlan(planPath)) {
        return {
            content,
            taskPlanPath: planPath,
            task: extractTaskBlock(content, taskId),
        };
    }

    const kanbanTargets = extractMarkdownLinks(content, /^task-kanban-.+\.md$/);
    if (kanbanTargets.length === 0) {
        return {
            content: '',
            taskPlanPath: null,
            task: null,
            reason: `Task ${taskId} cannot be resolved because task kanban is not linked from the main delivery plan.`,
        };
    }

    const kanbanPath = resolveRelativeTo(planDir, kanbanTargets[0]);
    if (!fs.existsSync(kanbanPath)) {
        return {
            content: '',
            taskPlanPath: null,
            task: null,
            reason: `Task ${taskId} cannot be resolved because task kanban does not exist: ${kanbanTargets[0]}`,
        };
    }

    const kanbanContent = fs.readFileSync(kanbanPath, 'utf8');
    const kanbanTask = findTaskInKanban(kanbanContent, taskId);
    if (!kanbanTask || !kanbanTask.subPlanTarget) {
        return {
            content: '',
            taskPlanPath: null,
            task: null,
            reason: `Task ${taskId} is not linked to a sub delivery plan in task kanban.`,
        };
    }

    const taskPlanPath = resolveRelativeTo(planDir, kanbanTask.subPlanTarget);
    if (!fs.existsSync(taskPlanPath)) {
        return {
            content: '',
            taskPlanPath,
            task: null,
            reason: `Task ${taskId} sub delivery plan does not exist: ${kanbanTask.subPlanTarget}`,
        };
    }

    const taskContent = fs.readFileSync(taskPlanPath, 'utf8');
    return {
        content: taskContent,
        taskPlanPath,
        task: extractTaskBlock(taskContent, taskId),
    };
}

// ─── PRD link extraction ──────────────────────────────────────────────────────

function extractPrdLinks(taskContent) {
    const sectionMatch = taskContent.match(
        /\*\*PRD\s*双链[·.]?\s*读\*\*[：:]?\s*([\s\S]*?)(?=\*\*|$)/
    );
    if (!sectionMatch) return [];

    const sectionText = sectionMatch[1];
    const fileRe = /`([^`]+\.md)`|^[-*]\s+([\w./]+\.md)/gm;
    const files = [];
    let m;

    while ((m = fileRe.exec(sectionText)) !== null) {
        const raw = (m[1] || m[2]).trim();
        const filePath = raw.split(' ')[0].replace(/\s*§.*$/, '').trim();
        if (filePath.endsWith('.md')) {
            files.push(filePath);
        }
    }

    return [...new Set(files)];
}

function hasCoreFilesDeclared(taskContent) {
    const match = taskContent.match(/\*\*核心文件\*\*[：:]?\s*([\s\S]*?)(?=\*\*|$)/);
    if (!match) return false;
    return match[1].trim().length > 0;
}

// ─── Verification ─────────────────────────────────────────────────────────────

function verifyTask(planFile, taskId, docsDir = 'docs/prd') {
    const planPath = path.resolve(planFile);
    if (!fs.existsSync(planPath)) {
        throw new Error(`Delivery plan file does not exist: ${planPath}`);
    }

    const content = fs.readFileSync(planPath, 'utf8');
    const planDir = path.dirname(planPath);
    // 计划落在 <host>/docs/plans/delivery-plans/；PRD/foundation 落在 <host>/<docsDir>（默认 docs/prd）。
    // 与 collect-upstream-context.mjs 同口径：PRD 双链优先按 <host>/<docsDir>/<link> 解析。
    const hostRoot = resolveHostRoot(planDir);
    const prdDocsDir = path.resolve(hostRoot, docsDir);

    const taskSource = resolveTaskSource(planPath, content, taskId);
    const task = taskSource.task;
    const taskPlanPath = taskSource.taskPlanPath;
    if (!task) {
        return {
            taskId,
            taskTitle: null,
            canExecute: false,
            reason: taskSource.reason || `Task ${taskId} not found in delivery plan file group.`,
            taskPlanPath,
            missingFiles: [],
            coreFilesDeclared: false,
        };
    }

    const prdLinks = extractPrdLinks(task.content);
    const prdLinksDeclared = prdLinks.length > 0;
    const missingFiles = prdLinksDeclared ? [] : ['PRD 双链·读'];

    for (const link of prdLinks) {
        const candidates = [
            path.resolve(prdDocsDir, link),                                  // <host>/<docsDir>/<link>：PRD/foundation 实际所在，裸名与拆分子目录引用都命中
            path.resolve(hostRoot, 'src', 'frontend', 'page-preview', link), // page-explainer 产物所在；与 collect-upstream-context 的第二上游位置同口径
            path.resolve(hostRoot, link),                                     // 宿主根相对路径
            path.resolve(planDir, link),                                     // 计划目录相对
            path.resolve(link),                                              // 兜底：cwd / 绝对路径
        ];
        const exists = candidates.some((c) => fs.existsSync(c));
        if (!exists) {
            missingFiles.push(link);
        }
    }

    const coreFilesDeclared = hasCoreFilesDeclared(task.content);
    const canExecute = prdLinksDeclared && missingFiles.length === 0 && coreFilesDeclared;

    return {
        taskId,
        taskTitle: task.title,
        taskPlanPath,
        canExecute,
        prdLinksFound: prdLinks,
        prdLinksDeclared,
        missingFiles,
        coreFilesDeclared,
    };
}

// ─── Formatter ───────────────────────────────────────────────────────────────

function formatEnvReport(result) {
    const lines = ['=== check-env-context ===', ''];
    if (result.envReady) {
        lines.push('✅ 环境验证通过 — envReady: true');
        for (const warning of result.warnings || []) {
            lines.push(`⚠️  ${warning}`);
        }
        return lines.join('\n');
    }

    lines.push('❌ 环境验证失败 — envReady: false', '');
    lines.push('── 缺失或异常的环境依赖 ──');
    for (const msg of result.missingEnv) {
        lines.push(`  • ${msg}`);
    }
    lines.push('', '请先补齐或安装上述环境依赖，再开始执行 Task。');
    return lines.join('\n');
}

function formatReport(result) {
    const lines = [];
    lines.push('=== verify-task-context ===');
    lines.push(`Task: ${result.taskId} ${result.taskTitle ? `"${result.taskTitle}"` : '(not found)'}`);
    lines.push('');

    if (result.canExecute) {
        lines.push('✅ 验证通过 — canExecute: true');
        lines.push(`   PRD 双链文件: ${result.prdLinksFound.length} 个，全部存在`);
        lines.push(`   核心文件字段: 已声明`);
        return lines.join('\n');
    }

    lines.push('❌ 验证失败 — canExecute: false');
    lines.push('');

    // Task 本身没找到时只报这一条定位错误，不再往下罗列字段级错误
    // （字段检查以 Task 存在为前提，叠加输出会误导排查方向）。
    if (!result.taskTitle) {
        lines.push(`  • Task ${result.taskId} 在开发计划文件组中不存在`);
        if (result.reason) lines.push(`    ${result.reason}`);
        lines.push('');
        lines.push('请先核对 Task ID 与任务看板中的条目是否一致，再重新运行本脚本。');
        return lines.join('\n');
    }

    if (result.prdLinksDeclared === false) {
        lines.push('── 未声明 PRD 双链 ──');
        lines.push('  • Task 的 **PRD 双链·读** 字段没有可解析的 .md 文件，禁止开始实装');
    }

    if (result.missingFiles.length > 0) {
        const missingRealFiles = result.missingFiles.filter((item) => item !== 'PRD 双链·读');
        if (missingRealFiles.length > 0) {
            lines.push(`── 缺失 PRD 文件 (${missingRealFiles.length}) ──`);
        }
        for (const f of missingRealFiles) {
            lines.push(`  • ${f}`);
        }
    }

    if (!result.coreFilesDeclared) {
        lines.push('── 未声明核心文件 ──');
        lines.push('  • Task 的 **核心文件** 字段为空或缺失，禁止开始实装');
    }

    lines.push('');
    lines.push('请先补齐上述缺失项，再重新运行本脚本。');
    return lines.join('\n');
}

// ─── Main ─────────────────────────────────────────────────────────────────────

function main() {
    const options = parseArgs(process.argv);

    if (options.envCheck) {
        const result = verifyEnv(options.planFile);
        if (options.json) {
            console.log(JSON.stringify(result, null, 2));
        } else {
            console.log(formatEnvReport(result));
        }
        if (!result.envReady) process.exit(2);
        return;
    }

    const result = verifyTask(options.planFile, options.taskId, options.docsDir);

    if (options.json) {
        console.log(JSON.stringify(result, null, 2));
    } else {
        console.log(formatReport(result));
    }

    if (!result.canExecute) {
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

export { verifyTask, verifyEnv };
