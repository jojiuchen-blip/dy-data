#!/usr/bin/env node

/**
 * Traceability:
 * Rule sources:
 * - skills/00-01-ai-project-manager/references/core/global-files-protocol.md
 * - skills/00-01-ai-project-manager/references/core/runtime.md
 * - skills/00-01-ai-project-manager/references/rules/devlog.md
 * Related tools:
 * - tools/validate-global-files.mjs
 */
import fs from 'fs';
import path from 'path';
import process from 'process';
import { execFileSync } from 'child_process';
import { fileURLToPath } from 'url';
import { resolveDevlogDirectory } from '../lib/ai-pm-protocol/devlog-path.js';
import { validateGlobalFiles } from './validate-global-files.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const suiteRoot = path.resolve(__dirname, '..');
const dailyTemplatePath = path.join(suiteRoot, 'skills', '00-02-project-devlog', 'assets', 'daily.md');
const ruleCandidatesTemplatePath = path.join(
    suiteRoot,
    'skills',
    '00-01-ai-project-manager',
    'assets',
    'devlog',
    'rule-candidates-template.md'
);

function printUsage() {
    console.log(
        'Usage: node <suite-path>/tools/devlog-sync.mjs <host-project-root> --title <title> --goal <goal> --action <action> --result <result> [--devlog-dir <relative-path>] [--actor <actor>] [--date YYYY-MM-DD] [--time HH:MM] [--files path1,path2] [--stage <stage>] [--conclusion <text>] [--next <text>] [--plan-path <path>] [--reflection <text>] [--rule-scope <scope>] [--rule-target <path>] [--rule-check <text>] [--rule-title <title>] [--dry-run] [--json]'
    );
    console.log(
        '<suite-path> 指套件根目录：源码仓库联调时为 project-manager-suite/，安装到宿主后为 .agent/project-manager-suite/；命令默认在宿主项目根目录执行。'
    );
}

function parseArgs(argv) {
    const args = argv.slice(2);
    const options = {
        hostRoot: '',
        devlogDir: '',
        actor: '',
        date: '',
        time: '',
        title: '',
        goal: '',
        action: '',
        result: '',
        files: '',
        stage: '',
        conclusion: '',
        next: '',
        planPath: '',
        reflection: '',
        ruleScope: '',
        ruleTarget: '',
        ruleCheck: '',
        ruleTitle: '',
        dryRun: false,
        json: false
    };

    const valueFlags = new Set([
        '--devlog-dir',
        '--actor',
        '--date',
        '--time',
        '--title',
        '--goal',
        '--action',
        '--result',
        '--files',
        '--stage',
        '--conclusion',
        '--next',
        '--plan-path',
        '--reflection',
        '--rule-scope',
        '--rule-target',
        '--rule-check',
        '--rule-title'
    ]);

    for (let i = 0; i < args.length; i += 1) {
        const arg = args[i];

        if (arg === '--dry-run') {
            options.dryRun = true;
            continue;
        }

        if (arg === '--json') {
            options.json = true;
            continue;
        }

        if (valueFlags.has(arg)) {
            const nextValue = args[i + 1];
            if (!nextValue) {
                throw new Error(`Missing value for ${arg}`);
            }

            const key = arg.replace(/^--/, '').replace(/-([a-z])/g, (_, char) => char.toUpperCase());
            options[key] = nextValue;
            i += 1;
            continue;
        }

        if (!options.hostRoot) {
            options.hostRoot = arg;
            continue;
        }

        throw new Error(`Unknown argument: ${arg}`);
    }

    if (!options.hostRoot) {
        throw new Error('Missing host project root.');
    }

    for (const requiredKey of ['title', 'goal', 'action', 'result']) {
        if (!options[requiredKey]) {
            throw new Error(`Missing required argument: --${requiredKey}`);
        }
    }

    return options;
}

function pad2(value) {
    return String(value).padStart(2, '0');
}

function getDateParts(dateInput) {
    const date = dateInput ? new Date(`${dateInput}T00:00:00`) : new Date();
    if (Number.isNaN(date.getTime())) {
        throw new Error(`Invalid date: ${dateInput}`);
    }

    const yyyy = date.getFullYear();
    const mm = pad2(date.getMonth() + 1);
    const dd = pad2(date.getDate());

    return {
        isoDate: `${yyyy}-${mm}-${dd}`,
        compactDate: `${yyyy}${mm}${dd}`,
        yearMonth: `${yyyy}${mm}`,
        yearMonthDisplay: `${yyyy}年${mm}月`
    };
}

function getTimeText(timeInput) {
    if (timeInput) return timeInput;
    const now = new Date();
    return `${pad2(now.getHours())}:${pad2(now.getMinutes())}`;
}

function slugifyActor(actor) {
    const normalized = actor.trim();
    if (!normalized) return 'unknown';
    const slug = normalized
        .replace(/\s+/g, '_')
        .replace(/[^\w\u4e00-\u9fa5-]/g, '_')
        .replace(/_+/g, '_')
        .replace(/^_+|_+$/g, '');
    return slug || 'unknown';
}

function splitList(text) {
    if (!text) return [];
    return text
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean);
}

function safeRead(filePath) {
    return fs.existsSync(filePath) ? fs.readFileSync(filePath, 'utf8') : '';
}

function ensureDir(targetPath, dryRun) {
    if (dryRun) return;
    fs.mkdirSync(targetPath, { recursive: true });
}

function escapeRegExp(value) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function getActor(options, hostRoot) {
    if (options.actor) return options.actor;

    const validation = validateGlobalFiles({ hostRoot });
    const profileRelative = validation.authority.project_profile;
    if (profileRelative) {
        const content = safeRead(path.join(hostRoot, profileRelative));
        const match = content.match(/- 身份识别口径：(.*)/);
        if (match && match[1] && !/【|待确认|待填写/.test(match[1])) {
            return match[1].trim();
        }
    }

    const gitUserName = getGitUserName(hostRoot);
    if (gitUserName) return gitUserName;

    return process.env.USER || process.env.LOGNAME || 'unknown';
}

function getGitUserName(hostRoot) {
    try {
        const value = execFileSync('git', ['-C', hostRoot, 'config', 'user.name'], {
            encoding: 'utf8',
            stdio: ['ignore', 'pipe', 'ignore']
        }).trim();

        return value || '';
    } catch {
        return '';
    }
}

function isCompositeActorLabel(value) {
    return /(?:\+|&|AI|当前工作区|本人|我们|协作)/i.test(value);
}

function getActorFileKey(options, hostRoot, actor) {
    const gitUserName = getGitUserName(hostRoot);
    if (gitUserName) {
        return gitUserName;
    }

    if (options.actor && !isCompositeActorLabel(options.actor)) {
        return options.actor;
    }

    const fallbackUser = process.env.USER || process.env.LOGNAME || '';
    if (fallbackUser) {
        return fallbackUser;
    }

    if (actor && !isCompositeActorLabel(actor)) {
        return actor;
    }

    return 'unknown';
}

function resolvePlanPath(options, hostRoot) {
    if (options.planPath) return options.planPath;

    const validation = validateGlobalFiles({ hostRoot });
    return validation.authority.execution_plan || 'docs/plans/execution-plan.md';
}

function buildNewDailyLog({
    isoDate,
    actor,
    planPath,
    title,
    goal,
    action,
    result,
    files,
    conclusion,
    next,
    stage
}) {
    const template = safeRead(dailyTemplatePath);
    const actorText = actor || 'unknown';
    const filesText = files.length > 0 ? files.join('、') : '无';
    const nextItems = next ? next.split('||').map((item) => item.trim()).filter(Boolean) : [];
    const nextMarkdown = nextItems.length > 0 ? nextItems.map((item) => `- [ ] ${item}`).join('\n') : '- [ ] 待补充';

    let content = template
        .replace('YYYY-MM-DD', isoDate)
        .replace('一句话描述今天主要做了什么', title)
        .replace('姓名（角色）', actorText)
        .replace('skills/00-01-ai-project-manager/assets/global-files/execution-plan.md / 宿主项目计划文件', planPath)
        .replace('| 1 | 描述 | Phase/PR/BUG 编号 | ✅/⏳/❌ |', `| 1 | ${title} | ${stage || '本轮推进'} | ✅ |`)
        .replace('（可选，一句话概括今天最重要的决策或产出）', conclusion || result)
        .replace('### 任务 1：标题', `### 任务 1：${title}`)
        .replace('- **目标**：做什么', `- **目标**：${goal}`)
        .replace('- **操作**：怎么做（关键命令/改动）', `- **操作**：${action}`)
        .replace('- **结果**：成了还是没成', `- **结果**：${result}`)
        .replace('- **涉及文件**：列表', `- **涉及文件**：${filesText}`)
        .replace('- [ ] 明天计划 1\n- [ ] 明天计划 2', nextMarkdown);

    return content;
}

function appendSupplementUpdate(existingContent, { title, goal, action, result, files, timeText }) {
    const supplementMatches = [...existingContent.matchAll(/^## 补充更新/gm)];
    const updateNumber = supplementMatches.length + 1;
    const filesText = files.length > 0 ? files.join('、') : '无';
    const taskNumber = updateNumber + 1;

    const block = [
        '',
        '---',
        '',
        `## 补充更新 ${updateNumber}（${timeText} · 窗口 ${updateNumber}）`,
        '',
        `### 任务 ${taskNumber}：${title}`,
        `- **目标**：${goal}`,
        `- **操作**：${action}`,
        `- **结果**：${result}`,
        `- **涉及文件**：${filesText}`,
        ''
    ].join('\n');

    return `${existingContent.replace(/\s*$/, '')}${block}`;
}

function parseSummaryRows(existingContent) {
    return [...existingContent.matchAll(/^\| (\d+) \| (.+?) \| (.+?) \| (.+?) \|$/gm)].map((match) => ({
        index: Number(match[1]),
        title: match[2].trim(),
        stage: match[3].trim(),
        status: match[4].trim(),
        raw: match[0]
    }));
}

function extractLatestTaskBlock(existingContent) {
    const taskMatches = [...existingContent.matchAll(/^### 任务 (\d+)：(.+)$/gm)];
    if (taskMatches.length === 0) {
        return null;
    }

    const latest = taskMatches[taskMatches.length - 1];
    const start = latest.index ?? 0;
    const end = existingContent.length;

    return {
        taskNumber: Number(latest[1]),
        title: latest[2].trim(),
        start,
        end,
        block: existingContent.slice(start, end)
    };
}

function isDecisionLikeUpdate({ title, goal, action, result }) {
    const text = [title, goal, action, result].filter(Boolean).join('\n');
    return /(确认|澄清|收口|细化|明确|对齐|口径)/.test(text);
}

function shouldMergeIntoLatest(existingContent, { title, goal, action, result, stage }) {
    if (!stage) {
        return false;
    }

    if (!isDecisionLikeUpdate({ title, goal, action, result })) {
        return false;
    }

    const latestTask = extractLatestTaskBlock(existingContent);
    if (!latestTask) {
        return false;
    }

    const summaryRows = parseSummaryRows(existingContent);
    const latestSummaryRow = summaryRows[summaryRows.length - 1];
    if (!latestSummaryRow) {
        return false;
    }

    return latestSummaryRow.stage === stage;
}

function mergeFilesLine(existingLine, files) {
    const currentFiles = existingLine
        .split('：')
        .slice(1)
        .join('：')
        .split('、')
        .map((item) => item.trim())
        .filter(Boolean);
    const merged = [...new Set([...currentFiles, ...files])];
    return `- **涉及文件**：${merged.length > 0 ? merged.join('、') : '无'}`;
}

function mergeIntoLatestTask(existingContent, { title, action, result, files, timeText }) {
    const latestTask = extractLatestTaskBlock(existingContent);
    if (!latestTask) {
        return existingContent;
    }

    let block = latestTask.block;
    const detailLine = `  - ${timeText} ${title}：${action}；结果：${result}`;

    if (block.includes('- **同主题补充**：')) {
        block = block.replace(/(\n- \*\*涉及文件\*\*：)/, `\n${detailLine}$1`);
    } else {
        block = block.replace(/(\n- \*\*涉及文件\*\*：)/, `\n- **同主题补充**：\n${detailLine}$1`);
    }

    block = block.replace(/- \*\*涉及文件\*\*：.*$/m, (line) => mergeFilesLine(line, files));

    return `${existingContent.slice(0, latestTask.start)}${block}`;
}

function injectSummaryRow(existingContent, { title, stage }) {
    const marker = '| 1 |';
    if (!existingContent.includes(marker)) {
        return existingContent;
    }

    const matches = [...existingContent.matchAll(/^\| (\d+) \|/gm)];
    const maxIndex = matches.reduce((max, match) => Math.max(max, Number(match[1])), 0);
    const nextIndex = maxIndex + 1;
    const newRow = `| ${nextIndex} | ${title} | ${stage || '补充更新'} | ✅ |`;

    return existingContent.replace(
        /(\|---\|------\|------\|------\|\n(?:\|.*\|\n)*)/,
        (match) => `${match}${newRow}\n`
    );
}

function hasRuleSignal(texts) {
    const fullText = texts.filter(Boolean).join('\n');
    return /建议提炼为规则|建议写入规则|建议升级为规则|是否提炼为规则.*✅|→ 🔧/.test(fullText);
}

function buildRuleCandidateId(yearMonth, existingContent) {
    const matches = [...existingContent.matchAll(/RC-(\d{6})-(\d{3})/g)];
    const sameMonth = matches
        .map((match) => match.slice(1))
        .filter(([ym]) => ym === yearMonth)
        .map(([, seq]) => Number(seq));

    const nextSeq = (sameMonth.length > 0 ? Math.max(...sameMonth) : 0) + 1;
    return `RC-${yearMonth}-${String(nextSeq).padStart(3, '0')}`;
}

function ensureRuleCandidatesFile(retrospectivesDir, yearMonthDisplay, dryRun) {
    const compactMonth = yearMonthDisplay.replace(/[^\d]/g, '').slice(0, 6);
    const filePath = path.join(retrospectivesDir, `rule-candidates-${compactMonth}.md`);

    if (fs.existsSync(filePath)) {
        return filePath;
    }

    const template = safeRead(ruleCandidatesTemplatePath).replace('YYYY年MM月', yearMonthDisplay);
    if (!dryRun) {
        fs.mkdirSync(retrospectivesDir, { recursive: true });
        fs.writeFileSync(filePath, template, 'utf8');
    }

    return filePath;
}

function appendRuleCandidate(existingContent, payload) {
    const pendingSectionMarker = '## 已采纳升级区 (Accepted)';
    const entry = [
        `### 1. [${payload.isoDate}] ${payload.ruleTitle}`,
        `- **候选 ID**：\`${payload.candidateId}\``,
        `- **来源任务/日志**：\`${payload.logRelativePath}\``,
        `- **首次记录时间**：${payload.isoDate}`,
        `- **最后一次命中时间**：${payload.isoDate}`,
        `- **适用范围**：${payload.ruleScope || '待评估'}`,
        `- **问题背景**：${payload.reflection || payload.result}`,
        `- **建议规则内容**：${payload.ruleSummary}`,
        `- **建议落点**：\`${payload.ruleTarget || 'project-rules.md'}\``,
        '- **复现频次**：首次提出',
        `- **可执行检查点**：${payload.ruleCheck || '待补充'}`,
        '- **当前状态**：`待评估`',
        '',
        '---',
        ''
    ].join('\n');

    if (existingContent.includes(pendingSectionMarker)) {
        return existingContent.replace(pendingSectionMarker, `${entry}${pendingSectionMarker}`);
    }

    return `${existingContent.trim()}\n\n${entry}`;
}

function devlogSync(options) {
    const hostRoot = path.resolve(process.cwd(), options.hostRoot);
    const actor = getActor(options, hostRoot);
    const dateParts = getDateParts(options.date);
    const timeText = getTimeText(options.time);
    const planPath = resolvePlanPath(options, hostRoot);
    const actorFileKey = getActorFileKey(options, hostRoot, actor);
    const actorSlug = slugifyActor(actorFileKey);
    const devlogDirectory = resolveDevlogDirectory({
        hostRoot,
        explicitPath: options.devlogDir || ''
    });
    const logRelativePath = path.join(
        ...devlogDirectory.relativePath.split('/'),
        `${dateParts.compactDate}_refactor_log_${actorSlug}.md`
    );
    const logFilePath = path.join(hostRoot, logRelativePath);
    const files = splitList(options.files);
    const stage = options.stage || '';

    const result = {
        hostRoot,
        logFile: logRelativePath.split(path.sep).join('/'),
        actor,
        actorFileKey,
        devlogDirectory: devlogDirectory.relativePath,
        createdLog: false,
        appendedLog: false,
        mergedLog: false,
        updatedCandidatePool: false,
        candidatePoolFile: null,
        candidateId: null
    };

    const logsDir = path.dirname(logFilePath);
    ensureDir(logsDir, options.dryRun);

    if (!fs.existsSync(logFilePath)) {
        const content = buildNewDailyLog({
            isoDate: dateParts.isoDate,
            actor,
            planPath,
            title: options.title,
            goal: options.goal,
            action: options.action,
            result: options.result,
            files,
            conclusion: options.conclusion,
            next: options.next,
            stage
        });

        if (!options.dryRun) {
            fs.writeFileSync(logFilePath, content, 'utf8');
        }
        result.createdLog = true;
    } else {
        let content = safeRead(logFilePath);
        if (shouldMergeIntoLatest(content, options)) {
            content = mergeIntoLatestTask(content, {
                title: options.title,
                action: options.action,
                result: options.result,
                files,
                timeText
            });
            result.mergedLog = true;
        } else {
            content = appendSupplementUpdate(content, {
                title: options.title,
                goal: options.goal,
                action: options.action,
                result: options.result,
                files,
                timeText
            });
            content = injectSummaryRow(content, {
                title: options.title,
                stage
            });
            result.appendedLog = true;
        }

        if (!options.dryRun) {
            fs.writeFileSync(logFilePath, content, 'utf8');
        }
    }

    const shouldUpdateRuleCandidates = hasRuleSignal([
        options.reflection,
        options.result,
        options.conclusion,
        options.next,
        options.ruleTitle
    ]);

    if (shouldUpdateRuleCandidates) {
        const retrospectivesDir = path.join(hostRoot, 'docs', 'retrospectives');
        const candidateFilePath = ensureRuleCandidatesFile(
            retrospectivesDir,
            dateParts.yearMonthDisplay,
            options.dryRun
        );
        const existingCandidates = safeRead(candidateFilePath);
        const candidateId = buildRuleCandidateId(dateParts.yearMonth, existingCandidates);
        const ruleTitle = options.ruleTitle || options.title;
        const ruleSummary = options.ruleTarget
            ? `${ruleTitle}，建议写入 ${options.ruleTarget}`
            : `${ruleTitle}，建议提炼为规则`;

        const candidateContent = appendRuleCandidate(existingCandidates, {
            candidateId,
            isoDate: dateParts.isoDate,
            logRelativePath: logRelativePath.split(path.sep).join('/'),
            ruleScope: options.ruleScope,
            reflection: options.reflection,
            result: options.result,
            ruleSummary,
            ruleTarget: options.ruleTarget,
            ruleCheck: options.ruleCheck,
            ruleTitle
        });

        if (!options.dryRun) {
            fs.mkdirSync(path.dirname(candidateFilePath), { recursive: true });
            fs.writeFileSync(candidateFilePath, candidateContent, 'utf8');
        }

        result.updatedCandidatePool = true;
        result.candidatePoolFile = path.relative(hostRoot, candidateFilePath).split(path.sep).join('/');
        result.candidateId = candidateId;
    }

    return result;
}

function formatTextReport(result) {
    const lines = [
        `Host root: ${result.hostRoot}`,
        `Devlog directory: ${result.devlogDirectory}`,
        `Log file: ${result.logFile}`,
        `Actor: ${result.actor}`,
        `Actor file key: ${result.actorFileKey}`,
        `Created log: ${result.createdLog ? 'yes' : 'no'}`,
        `Appended log: ${result.appendedLog ? 'yes' : 'no'}`,
        `Merged log: ${result.mergedLog ? 'yes' : 'no'}`,
        `Updated candidate pool: ${result.updatedCandidatePool ? 'yes' : 'no'}`
    ];

    if (result.candidatePoolFile) {
        lines.push(`Candidate pool file: ${result.candidatePoolFile}`);
    }

    if (result.candidateId) {
        lines.push(`Candidate ID: ${result.candidateId}`);
    }

    return lines.join('\n');
}

function main() {
    const options = parseArgs(process.argv);
    const result = devlogSync(options);

    if (options.json) {
        console.log(JSON.stringify(result, null, 2));
        return;
    }

    console.log(formatTextReport(result));
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
    try {
        main();
    } catch (error) {
        printUsage();
        console.error(error.message);
        process.exit(1);
    }
}

export { devlogSync, formatTextReport };
