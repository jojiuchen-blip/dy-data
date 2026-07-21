#!/usr/bin/env node

/**
 * prd-check.mjs
 *
 * Traceability:
 *   Rule sources:
 *     - skills/04-03-prd-writer/SKILL.md
 *     - skills/04-03-prd-writer/templates/feature-list.md
 *     - skills/04-03-prd-writer/templates/main-prd.md
 *     - skills/04-03-prd-writer/templates/sub-prd.md
 *     - skills/04-03-prd-writer/references/phase-5-consistency-check.md
 *
 * Purpose:
 *   Provide machine-checkable PRD writing feedback for tool-collaborative models.
 *   Mechanical failures return exact rule ids, locations, fix hints, and the next
 *   command to run after repair.
 *
 * Usage:
 *   <suite-path> = suite root: project-manager-suite/ in-repo, .agent/project-manager-suite/ in a host project.
 *   node <suite-path>/skills/04-03-prd-writer/scripts/prd-check.mjs structure --file <path> [--json]
 *   node <suite-path>/skills/04-03-prd-writer/scripts/prd-check.mjs crosscheck --host-dir <path> --slug <slug> [--json]
 *   node <suite-path>/skills/04-03-prd-writer/scripts/prd-check.mjs progress --host-dir <path> --slug <slug> [--json]
 *   node <suite-path>/skills/04-03-prd-writer/scripts/prd-check.mjs sync-index --host-dir <path> --slug <slug> [--json]
 *   node <suite-path>/skills/04-03-prd-writer/scripts/prd-check.mjs set-status --host-dir <path> --slug <slug> --block <N> --status <状态> [--json]
 *
 * Exit codes:
 *   0 - pass
 *   1 - fatal usage / IO error
 *   2 - mechanical validation failure
 *   3 - unresolved needs_ai_review
 */

import fs from 'fs';
import path from 'path';
import process from 'process';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);

const VALID_STATUSES = new Set(['待开始', '待确认', '已确认']);
const ACCEPTANCE_TYPES = new Set(['业务规则', 'UX 交互', '异常兜底']);
const CIRCLED_NUMBERS = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳';
const FEATURE_HEADERS = ['#', '页面', '区块', '功能说明', 'subprd文件', '状态'];
const MAIN_HEADERS = ['#', '区块', '所属页面', 'subprd文件', '状态'];
const DATA_LINK_HEADERS = ['UI 元素', 'API 字段', '计算规则', '数据源（服务端读取）', '配置源（服务端读取）'];
const ACCEPTANCE_HEADERS = ['#', '类型', '场景', '触发条件', '预期结果'];
const REVIEW_EXIT = 3;
const FAIL_EXIT = 2;

function readFile(filePath) {
    return fs.readFileSync(filePath, 'utf8');
}

function writeFile(filePath, content) {
    fs.writeFileSync(filePath, content, 'utf8');
}

function normalizeValue(value) {
    return String(value || '').trim();
}

function stripMarkdown(value) {
    return normalizeValue(value)
        .replace(/\*\*/g, '')
        .replace(/`/g, '')
        .trim();
}

function basenameFromCell(value) {
    const target = normalizeMarkdownLinkTarget(value);
    return path.basename(target);
}

function normalizeMarkdownLinkTarget(value) {
    const raw = normalizeValue(value);
    const markdownLink = raw.match(/\[[^\]]+\]\(([^)]+)\)/);
    return (markdownLink?.[1] || raw).replace(/[?#].*$/, '').trim();
}

function isFenceLine(line) {
    return /^```/.test(line.trim());
}

function withoutCodeFences(content) {
    const lines = content.split('\n');
    let inFence = false;
    return lines
        .map((line) => {
            if (isFenceLine(line)) {
                inFence = !inFence;
                return '';
            }
            return inFence ? '' : line;
        })
        .join('\n');
}

function parseMarkdownTables(content) {
    const lines = content.split('\n');
    const tables = [];
    let index = 0;
    let inFence = false;

    while (index < lines.length) {
        const rawLine = lines[index];
        if (isFenceLine(rawLine)) {
            inFence = !inFence;
            index += 1;
            continue;
        }
        if (inFence) {
            index += 1;
            continue;
        }

        const line = rawLine.trim();
        const separatorLine = lines[index + 1]?.trim() || '';
        if (!line.startsWith('|') || !separatorLine.startsWith('|')) {
            index += 1;
            continue;
        }

        const headers = splitTableRow(line);
        const separator = splitTableRow(separatorLine);
        if (
            headers.length === 0 ||
            headers.length !== separator.length ||
            !separator.every((cell) => /^:?-{3,}:?$/.test(cell))
        ) {
            index += 1;
            continue;
        }

        const rows = [];
        let rowIndex = index + 2;
        while (rowIndex < lines.length) {
            const rowLine = lines[rowIndex].trim();
            if (!rowLine.startsWith('|')) {
                break;
            }
            const cells = splitTableRow(rowLine);
            if (cells.length === headers.length) {
                rows.push({ cells, lineNumber: rowIndex + 1, raw: lines[rowIndex] });
            }
            rowIndex += 1;
        }

        tables.push({
            headers,
            rows,
            startLine: index + 1,
            separatorLine: index + 2,
            endLine: rowIndex
        });
        index = rowIndex;
    }

    return tables;
}

function splitTableRow(line) {
    return line
        .split('|')
        .slice(1, -1)
        .map((cell) => cell.trim());
}

function headersEqual(left, right) {
    return left.length === right.length && left.every((item, index) => item === right[index]);
}

function findTable(content, headers) {
    return parseMarkdownTables(content).find((table) => headersEqual(table.headers, headers)) || null;
}

function makeIssue(ruleId, severity, file, section, expected, actual, fixHint, nextCommand, extra = {}) {
    return {
        ruleId,
        severity,
        file: file ? path.resolve(file) : '',
        section,
        expected,
        actual,
        fixHint,
        nextCommand,
        ...extra
    };
}

function summarizeIssues(issues) {
    return {
        fail: issues.filter((issue) => issue.severity === 'fail').length,
        warn: issues.filter((issue) => issue.severity === 'warn').length,
        needs_ai_review: issues.filter((issue) => issue.severity === 'needs_ai_review').length
    };
}

function report(command, issues, extra = {}) {
    const summary = summarizeIssues(issues);
    return {
        ok: summary.fail === 0 && summary.needs_ai_review === 0,
        command,
        summary,
        issues,
        ...extra
    };
}

function detectFileType(filePath, content) {
    const base = path.basename(filePath);
    if (/^prd-feature-list-.+\.md$/.test(base)) return 'feature-list';
    if (/^mainprd-.+\.md$/.test(base)) return 'mainprd';
    if (/^\d{2}-subprd-.+\.md$/.test(base)) return 'subprd';
    if (/^# .+ — mainprd/m.test(content)) return 'mainprd';
    if (/^# PRD \d+:/m.test(content)) return 'subprd';
    return 'feature-list';
}

function structure({ filePath }) {
    const content = readFile(filePath);
    const type = detectFileType(filePath, content);
    if (type === 'feature-list') return validateFeatureList(filePath, content);
    if (type === 'mainprd') return validateMainprd(filePath, content);
    if (type === 'subprd') return validateSubprd(filePath, content);
    return report('structure', [
        makeIssue(
            'structure.unknown-file-type',
            'fail',
            filePath,
            'file',
            'prd-feature-list/mainprd/subprd file naming or heading',
            path.basename(filePath),
            'Use the standard prd-writer filename and H1 format.',
            `node ${__filename} structure --file ${quote(filePath)} --json`
        )
    ], { fileType: type });
}

function validateFeatureList(filePath, content) {
    const issues = [];
    const requiredSections = ['## 产品背景与定位', '### 产品是什么', '### 使用者', '## 功能总表', '## 页面布局全景', '## 区块详情'];
    for (const section of requiredSections) {
        if (!content.includes(section)) {
            issues.push(
                makeIssue(
                    'feature-list.required-section',
                    'fail',
                    filePath,
                    section,
                    `Must include ${section}`,
                    'Missing',
                    `按 feature-list 模板补齐 ${section}；页面布局全景需为每个页面提供一个路由小节和 ASCII 围栏。`,
                    `node ${__filename} structure --file ${quote(filePath)} --json`
                )
            );
        }
    }

    const table = findTable(content, FEATURE_HEADERS);
    if (!table) {
        issues.push(
            makeIssue(
                'feature-list.table-header',
                'fail',
                filePath,
                '## 功能总表',
                FEATURE_HEADERS.join(' | '),
                'Missing or changed table header',
                '把功能总表表头恢复为模板固定字面量。',
                `node ${__filename} structure --file ${quote(filePath)} --json`
            )
        );
        return report('structure', issues, { fileType: 'feature-list' });
    }

    const rows = featureRows(content);
    for (const row of rows) {
        if (!VALID_STATUSES.has(row.status)) {
            issues.push(
                makeIssue(
                    'feature-list.invalid-status',
                    'fail',
                    filePath,
                    '## 功能总表',
                    '待开始 / 待确认 / 已确认',
                    row.status,
                    '把状态列改为固定三态之一。',
                    `node ${__filename} structure --file ${quote(filePath)} --json`,
                    { row: row.index }
                )
            );
        }
        if (!/^\d{2}-subprd-[^/]+\.md$/.test(path.basename(row.target))) {
            issues.push(
                makeIssue(
                    'feature-list.subprd-path',
                    'fail',
                    filePath,
                    '## 功能总表',
                    'subprd/0X-subprd-*.md',
                    row.target,
                    '把 subprd 链接改为两位序号开头，并指向 docs/prd/subprd/ 下的文件。',
                    `node ${__filename} structure --file ${quote(filePath)} --json`,
                    { row: row.index }
                )
            );
        }
    }

    const expectedOrder = rows.map((row) => Number(row.index));
    for (let i = 0; i < expectedOrder.length; i += 1) {
        if (expectedOrder[i] !== i + 1) {
            issues.push(
                makeIssue(
                    'feature-list.sequence',
                    'fail',
                    filePath,
                    '## 功能总表',
                    'Global sequence 1..N without gaps',
                    expectedOrder.join(', '),
                    '重排功能总表 # 列，保持从 1 开始连续递增。',
                    `node ${__filename} structure --file ${quote(filePath)} --json`
                )
            );
            break;
        }
    }

    validateFeaturePanorama(filePath, content, rows, issues);
    validateFeatureDetails(filePath, content, rows, issues);

    return report('structure', issues, { fileType: 'feature-list' });
}

function validateFeaturePanorama(filePath, content, rows, issues) {
    const section = extractSection(content, '## 页面布局全景');
    if (!section) return;

    const pageSections = extractSubsections(section.content, /^### (.+?)（路由: (\S+)）\s*$/u);
    const tablePages = new Map();
    for (const row of rows) {
        if (!tablePages.has(row.page)) tablePages.set(row.page, []);
        tablePages.get(row.page).push(row);
    }

    const panoramaPages = new Map(pageSections.map((item) => [item.titleMatch[1], item]));
    for (const page of tablePages.keys()) {
        if (!panoramaPages.has(page)) {
            issues.push(
                makeIssue(
                    'feature-list.panorama-page-missing',
                    'fail',
                    filePath,
                    '## 页面布局全景',
                    `Page section for ${page}`,
                    'Missing',
                    `补充 \`### ${page}（路由: /path）\` 小节，并放入一个 ASCII 布局代码围栏。`,
                    `node ${__filename} structure --file ${quote(filePath)} --json`,
                    { page }
                )
            );
            continue;
        }
        const pageSection = panoramaPages.get(page);
        const fenceCount = countCodeFences(pageSection.content);
        if (fenceCount !== 1) {
            issues.push(
                makeIssue(
                    'feature-list.panorama-code-fence-count',
                    'fail',
                    filePath,
                    `## 页面布局全景 / ${page}`,
                    'Exactly one ASCII layout code fence',
                    String(fenceCount),
                    '每个页面小节只保留一个 ASCII 布局代码围栏。',
                    `node ${__filename} structure --file ${quote(filePath)} --json`,
                    { page }
                )
            );
        }
        const circledCount = countCircledNumbers(pageSection.content);
        const expected = tablePages.get(page).length;
        if (circledCount !== expected) {
            issues.push(
                makeIssue(
                    'feature-list.panorama-block-count',
                    'fail',
                    filePath,
                    `## 页面布局全景 / ${page}`,
                    `${expected} circled block numbers`,
                    `${circledCount}`,
                    '让页面全景图中的带圈数字数量与该页功能总表区块数量一致。',
                    `node ${__filename} structure --file ${quote(filePath)} --json`,
                    { page }
                )
            );
        }
        const expectedIds = tablePages
            .get(page)
            .map((row) => circledNumberForIndex(Number(row.index)))
            .filter(Boolean);
        const actualIds = extractCircledNumbers(pageSection.content);
        if (expectedIds.length === expected && !sameCircledMultiset(actualIds, expectedIds)) {
            issues.push(
                makeIssue(
                    'feature-list.panorama-block-ids',
                    'fail',
                    filePath,
                    `## 页面布局全景 / ${page}`,
                    expectedIds.join(' '),
                    actualIds.length > 0 ? actualIds.join(' ') : 'Missing',
                    '页面布局全景必须使用功能总表的全局带圈编号，不能在每个页面内重新从 ① 编号。',
                    `node ${__filename} structure --file ${quote(filePath)} --json`,
                    { page }
                )
            );
        }
        if (expected > CIRCLED_NUMBERS.length) {
            issues.push(
                makeIssue(
                    'feature-list.too-many-blocks-on-page',
                    'fail',
                    filePath,
                    `## 页面布局全景 / ${page}`,
                    `At most ${CIRCLED_NUMBERS.length} blocks per page`,
                    `${expected}`,
                    '单页区块过多，需拆页或调整编号方案后再扩展脚本规则。',
                    `node ${__filename} structure --file ${quote(filePath)} --json`,
                    { page }
                )
            );
        }
    }
}

function validateFeatureDetails(filePath, content, rows, issues) {
    const section = extractSection(content, '## 区块详情');
    if (!section) return;

    const detailSections = extractSubsections(section.content, new RegExp(`^### ([${CIRCLED_NUMBERS}])\\s+(.+?)\\s*$`, 'u'));
    const detailKeys = new Set();
    for (const detail of detailSections) {
        const blockName = detail.titleMatch[2].trim();
        const ownerPage = detail.content.match(/\*\*所属页面\*\*：(.+?)（路由:\s*\S+）/u)?.[1]?.trim() || '';
        if (ownerPage) detailKeys.add(`${ownerPage}::${blockName}`);

        const anchors = ['**所属页面**：', '**布局**：', '**业务逻辑**：', '**涉及使用者**：'];
        for (const anchor of anchors) {
            if (!detail.content.includes(anchor)) {
                issues.push(
                    makeIssue(
                        'feature-list.detail-anchor-missing',
                        'fail',
                        filePath,
                        `## 区块详情 / ${blockName}`,
                        anchor,
                        'Missing',
                        `补齐区块详情固定锚点 ${anchor}。`,
                        `node ${__filename} structure --file ${quote(filePath)} --json`,
                        { block: blockName }
                    )
                );
            }
        }
    }

    for (const row of rows) {
        const key = `${row.page}::${row.block}`;
        if (!detailKeys.has(key)) {
            issues.push(
                makeIssue(
                    'feature-list.detail-block-missing',
                    'fail',
                    filePath,
                    '## 区块详情',
                    key,
                    'Missing',
                    '为功能总表中的每个页面区块补齐对应区块详情小节。',
                    `node ${__filename} structure --file ${quote(filePath)} --json`,
                    { page: row.page, block: row.block }
                )
            );
        }
    }
}

function validateMainprd(filePath, content) {
    const issues = [];
    if (!/^# .+ — mainprd\s*$/m.test(content)) {
        issues.push(
            makeIssue(
                'mainprd.h1',
                'fail',
                filePath,
                'H1',
                '# {项目名称} — mainprd',
                content.match(/^# .+$/m)?.[0] || 'Missing',
                '把 H1 改为模板固定格式，使用 em dash：# Demo — mainprd。',
                `node ${__filename} structure --file ${quote(filePath)} --json`
            )
        );
    }
    for (const section of ['## 上游引用', '## subprd索引', '## 全局设计规则']) {
        if (!content.includes(section)) {
            issues.push(
                makeIssue(
                    'mainprd.required-section',
                    'fail',
                    filePath,
                    section,
                    `Must include ${section}`,
                    'Missing',
                    `按 main-prd 模板补齐 ${section}。`,
                    `node ${__filename} structure --file ${quote(filePath)} --json`
                )
            );
        }
    }
    if (!findTable(content, MAIN_HEADERS)) {
        issues.push(
            makeIssue(
                'mainprd.index-header',
                'fail',
                filePath,
                '## subprd索引',
                MAIN_HEADERS.join(' | '),
                'Missing or changed table header',
                '把 subprd索引表头恢复为模板固定字面量。',
                `node ${__filename} structure --file ${quote(filePath)} --json`
            )
        );
    }
    for (const row of mainRows(content)) {
        if (!VALID_STATUSES.has(row.status)) {
            issues.push(
                makeIssue(
                    'mainprd.invalid-status',
                    'fail',
                    filePath,
                    '## subprd索引',
                    '待开始 / 待确认 / 已确认',
                    row.status,
                    '把状态列改为固定三态之一。',
                    `node ${__filename} structure --file ${quote(filePath)} --json`,
                    { row: row.index }
                )
            );
        }
    }
    return report('structure', issues, { fileType: 'mainprd' });
}

function validateSubprd(filePath, content) {
    const issues = [];
    if (!/^# PRD \d+: .+/m.test(content)) {
        issues.push(
            makeIssue(
                'subprd.h1',
                'fail',
                filePath,
                'H1',
                '# PRD {N}: {区块名称}',
                content.match(/^# .+$/m)?.[0] || 'Missing',
                '把 H1 改为 sub-prd 模板固定格式。',
                `node ${__filename} structure --file ${quote(filePath)} --json`
            )
        );
    }
    for (const section of ['## §1 文档范围', '## §2 页面整体布局']) {
        if (!content.includes(section)) {
            issues.push(
                makeIssue(
                    'subprd.required-section',
                    'fail',
                    filePath,
                    section,
                    `Must include ${section}`,
                    'Missing',
                    `补齐 ${section}。`,
                    `node ${__filename} structure --file ${quote(filePath)} --json`
                )
            );
        }
    }
    if (!/\]\(\.\.\/mainprd-[^)]+\.md\)/.test(content)) {
        issues.push(
            makeIssue(
                'subprd.mainprd-backlink',
                'fail',
                filePath,
                'header',
                '../mainprd-<slug>.md backlink',
                'Missing',
                '在关联文档中补回 mainprd 反链。',
                `node ${__filename} structure --file ${quote(filePath)} --json`
            )
        );
    }

    const sections = extractSubsections(content, /^## §(\d+)\s+(.+?)\s*$/u);
    for (const section of sections) {
        const number = Number(section.titleMatch[1]);
        const title = section.titleMatch[2];
        if (/异常与兜底策略|接口契约/.test(title)) continue;
        if (!isFunctionalSection(section.content, number)) continue;
        validateFunctionalSection(filePath, section, number, issues);
    }
    return report('structure', issues, { fileType: 'subprd' });
}

// 功能子区域按结构特征识别：含任一固定子节（X.1 用户体验 / X.3 数据链路 / X.4 异常与兜底 / X.6 验收）
// 即按功能子区域校验。不能按章节号硬排除：模板允许省略 §3 信息架构，省略后首个功能子区域就是 §3。
// §1 文档范围 / §2 页面整体布局 / §3 信息架构（3.1 模式切换规则等）都没有这些固定子节，天然不会命中。
function isFunctionalSection(content, number) {
    const labels = [`${number}.1 用户体验`, `${number}.3 数据链路`, `${number}.4 异常与兜底`, `${number}.6 验收`];
    return labels.some((label) => new RegExp(`^### ${escapeRegExp(label)}\\s*$`, 'm').test(content));
}

function validateFunctionalSection(filePath, section, number, issues) {
    const required = [
        `${number}.1 用户体验`,
        `${number}.3 数据链路`,
        `${number}.4 异常与兜底`,
        `${number}.6 验收`
    ];
    for (const label of required) {
        const pattern = new RegExp(`^### ${escapeRegExp(label)}\\s*$`, 'gm');
        const count = [...section.content.matchAll(pattern)].length;
        if (count !== 1) {
            issues.push(
                makeIssue(
                    'subprd.functional-subsection',
                    'fail',
                    filePath,
                    `§${number}`,
                    `Exactly one ### ${label}`,
                    String(count),
                    `补齐或去重 ### ${label}。`,
                    `node ${__filename} structure --file ${quote(filePath)} --json`
                )
            );
        }
    }

    const dataSection = extractHeadingContent(section.content, `### ${number}.3 数据链路`);
    const dataTable = dataSection ? findTable(dataSection, DATA_LINK_HEADERS) : null;
    if (!dataTable) {
        issues.push(
            makeIssue(
                'subprd.data-link-table-header',
                'fail',
                filePath,
                `§${number}.3 数据链路`,
                DATA_LINK_HEADERS.join(' | '),
                'Missing or changed table header',
                '恢复 X.3 数据链路固定 5 列表头。',
                `node ${__filename} structure --file ${quote(filePath)} --json`
            )
        );
    }

    const fallbackSection = extractHeadingContent(section.content, `### ${number}.4 异常与兜底`);
    for (const anchor of ['**服务端兜底**：', '**前端渲染兜底**：']) {
        if (!fallbackSection?.includes(anchor)) {
            issues.push(
                makeIssue(
                    'subprd.fallback-anchor',
                    'fail',
                    filePath,
                    `§${number}.4 异常与兜底`,
                    anchor,
                    'Missing',
                    `补齐 ${anchor} 及对应表格。`,
                    `node ${__filename} structure --file ${quote(filePath)} --json`
                )
            );
        }
    }

    const acceptanceSection = extractHeadingContent(section.content, `### ${number}.6 验收`);
    const acceptanceTable = acceptanceSection ? findTable(acceptanceSection, ACCEPTANCE_HEADERS) : null;
    if (!acceptanceTable) {
        issues.push(
            makeIssue(
                'subprd.acceptance-table-header',
                'fail',
                filePath,
                `§${number}.6 验收`,
                ACCEPTANCE_HEADERS.join(' | '),
                'Missing or changed table header',
                '恢复 X.6 验收固定表头。',
                `node ${__filename} structure --file ${quote(filePath)} --json`
            )
        );
        return;
    }
    const typeIndex = ACCEPTANCE_HEADERS.indexOf('类型');
    for (const row of acceptanceTable.rows) {
        const type = row.cells[typeIndex];
        if (!ACCEPTANCE_TYPES.has(type)) {
            issues.push(
                makeIssue(
                    'subprd.acceptance-type',
                    'fail',
                    filePath,
                    `§${number}.6 验收`,
                    [...ACCEPTANCE_TYPES].join(' / '),
                    type,
                    '把类型列改为固定枚举之一。',
                    `node ${__filename} structure --file ${quote(filePath)} --json`
                )
            );
        }
    }
}

function crosscheck({ hostDir, slug }) {
    const paths = resolvePrdPaths(hostDir, slug);
    const issues = [];
    for (const filePath of [paths.featureList, paths.mainprd]) {
        if (!fs.existsSync(filePath)) {
            issues.push(
                makeIssue(
                    'crosscheck.required-file',
                    'fail',
                    filePath,
                    'file',
                    'Existing PRD artifact',
                    'Missing',
                    '补齐 prd-writer 产物后重跑 crosscheck。',
                    `node ${__filename} crosscheck --host-dir ${quote(hostDir)} --slug ${slug} --json`
                )
            );
            continue;
        }
        issues.push(...structure({ filePath }).issues);
    }
    if (issues.some((issue) => issue.severity === 'fail')) {
        return report('crosscheck', issues);
    }

    const featureContent = readFile(paths.featureList);
    const mainContent = readFile(paths.mainprd);
    const fRows = featureRows(featureContent);
    const mRows = mainRows(mainContent);
    const referencedSubprd = new Set([...fRows, ...mRows].map((row) => row.target).filter(Boolean));

    for (const target of referencedSubprd) {
        const subprdPath = path.resolve(paths.prdDir, target);
        if (!fs.existsSync(subprdPath)) {
            issues.push(
                makeIssue(
                    'crosscheck.subprd-missing',
                    'fail',
                    subprdPath,
                    'subprd',
                    'Existing subprd file',
                    'Missing',
                    '按功能总表和 mainprd 索引补齐缺失 subprd 文件。',
                    `node ${__filename} crosscheck --host-dir ${quote(hostDir)} --slug ${slug} --json`
                )
            );
            continue;
        }
        issues.push(...structure({ filePath: subprdPath }).issues);
    }

    if (fRows.length !== mRows.length || referencedSubprd.size !== fRows.length) {
        issues.push(
            makeIssue(
                'crosscheck.index-count-drift',
                'fail',
                paths.mainprd,
                'PRD indexes',
                'feature-list rows == mainprd rows == unique subprd refs',
                `${fRows.length} / ${mRows.length} / ${referencedSubprd.size}`,
                '运行 sync-index，以功能列表为权威重渲染 mainprd 索引。',
                `node ${__filename} sync-index --host-dir ${quote(hostDir)} --slug ${slug} --json`
            )
        );
    }

    const mainByIndex = new Map(mRows.map((row) => [row.index, row]));
    for (const fRow of fRows) {
        const mRow = mainByIndex.get(fRow.index);
        const expected = {
            block: fRow.block,
            page: fRow.page,
            target: fRow.target,
            status: fRow.status
        };
        const actual = mRow
            ? {
                  block: mRow.block,
                  page: mRow.page,
                  target: mRow.target,
                  status: mRow.status
              }
            : null;
        if (!actual || JSON.stringify(expected) !== JSON.stringify(actual)) {
            issues.push(
                makeIssue(
                    'crosscheck.index-row-drift',
                    'fail',
                    paths.mainprd,
                    `row ${fRow.index}`,
                    JSON.stringify(expected),
                    JSON.stringify(actual),
                    '运行 sync-index 或 set-status，同步功能列表与 mainprd 索引。',
                    `node ${__filename} sync-index --host-dir ${quote(hostDir)} --slug ${slug} --json`,
                    { index: fRow.index }
                )
            );
        }
    }

    for (const row of [...fRows, ...mRows]) {
        if (row.status !== '已确认') {
            issues.push(
                makeIssue(
                    'crosscheck.unconfirmed-row',
                    'fail',
                    row.sourceFile || paths.mainprd,
                    'PRD indexes',
                    '已确认',
                    row.status,
                    '确认该 subprd 后运行 set-status 同步两张索引表。',
                    `node ${__filename} set-status --host-dir ${quote(hostDir)} --slug ${slug} --block ${row.index} --status 已确认 --json`,
                    { index: row.index }
                )
            );
        }
    }

    issues.push(...validatePhase5Evidence(paths.mainprd, mainContent, hostDir, slug));
    issues.push(...validateSchemaReferences(paths, [...referencedSubprd]));
    issues.push(...validateApiReferences(paths, [...referencedSubprd]));
    issues.push(...validateInteractionReferences(paths, [...referencedSubprd]));
    issues.push(...validatePageCoverage(paths, fRows));

    return report('crosscheck', issues);
}

function validatePhase5Evidence(mainPath, content, hostDir, slug) {
    const issues = [];
    if (!content.includes('## 一致性自查结果')) {
        issues.push(
            makeIssue(
                'crosscheck.phase5-evidence-missing',
                'fail',
                mainPath,
                '## 一致性自查结果',
                'Phase 5 self-check result section',
                'Missing',
                '在 mainprd 写入一致性自查结果摘要。',
                `node ${__filename} crosscheck --host-dir ${quote(hostDir)} --slug ${slug} --json`
            )
        );
    } else {
        const section = extractSection(content, '## 一致性自查结果')?.content || '';
        if (/[✗✘❌]/.test(section)) {
            issues.push(
                makeIssue(
                    'crosscheck.phase5-has-fail-mark',
                    'fail',
                    mainPath,
                    '## 一致性自查结果',
                    'No failed check marks',
                    'Found failure mark',
                    '修复自查失败项后重写自查结果。',
                    `node ${__filename} crosscheck --host-dir ${quote(hostDir)} --slug ${slug} --json`
                )
            );
        }
    }
    const gaps = extractSection(content, '## 待回溯缺口')?.content || '';
    const gapTable = findTable(gaps, ['缺口', '类型', '回溯目标', '状态']);
    if (!gapTable) {
        issues.push(
            makeIssue(
                'crosscheck.gap-section-missing',
                'fail',
                mainPath,
                '## 待回溯缺口',
                'Gap table with status column',
                'Missing',
                '补齐待回溯缺口表；无缺口时写一行 resolved。',
                `node ${__filename} crosscheck --host-dir ${quote(hostDir)} --slug ${slug} --json`
            )
        );
    } else {
        const statusIndex = gapTable.headers.indexOf('状态');
        for (const row of gapTable.rows) {
            const status = row.cells[statusIndex];
            if (status !== 'resolved' && status !== '已解决') {
                issues.push(
                    makeIssue(
                        'crosscheck.unresolved-gap',
                        'fail',
                        mainPath,
                        '## 待回溯缺口',
                        'resolved / 已解决',
                        status,
                        '处理或明确关闭待回溯缺口后再 DONE。',
                        `node ${__filename} crosscheck --host-dir ${quote(hostDir)} --slug ${slug} --json`
                    )
                );
            }
        }
    }
    return issues;
}

// 支持 PIPELINE §"产物拆分约定"的拆分模式：主文件同名子目录存在时，主文件只是索引，
// 字段/接口的权威来源是子目录下全部 *.md。返回主文件 + 子目录子文件的路径列表。
function foundationDocFiles(mainPath) {
    const files = [mainPath];
    const splitDir = mainPath.replace(/\.md$/, '');
    if (fs.existsSync(splitDir) && fs.statSync(splitDir).isDirectory()) {
        for (const name of fs.readdirSync(splitDir).sort()) {
            if (name.endsWith('.md')) files.push(path.join(splitDir, name));
        }
    }
    return files;
}

// 逐文件提取再合并（不做整体拼接），避免子文件内容被误归到索引文件的相邻小节名下。
function extractFoundationRefs(mainPath, extractor) {
    const refs = new Set();
    for (const filePath of foundationDocFiles(mainPath)) {
        for (const ref of extractor(readFile(filePath))) refs.add(ref);
    }
    return refs;
}

function validateSchemaReferences(paths, subprdTargets) {
    const schemaPath = path.join(paths.hostDir, 'docs', 'prd', 'foundation', `foundation-schema-${paths.slug}.md`);
    if (!fs.existsSync(schemaPath)) return [];
    const schemaRefs = extractFoundationRefs(schemaPath, extractSchemaFieldRefs);
    const issues = [];
    for (const target of subprdTargets) {
        const subprdPath = path.resolve(paths.prdDir, target);
        if (!fs.existsSync(subprdPath)) continue;
        for (const ref of extractDataLinkRefs(readFile(subprdPath))) {
            if (!schemaRefs.has(ref)) {
                issues.push(
                    makeIssue(
                        'crosscheck.schema-field-missing',
                        'fail',
                        subprdPath,
                        'X.3 数据链路',
                        `${ref} exists in foundation-schema`,
                        'Missing',
                        '修正 subprd 数据链路引用，或记录待回溯 foundation-builder 缺口。',
                        `node ${__filename} crosscheck --host-dir ${quote(paths.hostDir)} --slug ${paths.slug} --json`,
                        { ref }
                    )
                );
            }
        }
    }
    return issues;
}

function validateApiReferences(paths, subprdTargets) {
    const apiPath = path.join(paths.hostDir, 'docs', 'prd', 'foundation', `foundation-api-${paths.slug}.md`);
    if (!fs.existsSync(apiPath)) return [];
    const apiRefs = extractFoundationRefs(apiPath, extractApiRefs);
    const issues = [];
    for (const target of subprdTargets) {
        const subprdPath = path.resolve(paths.prdDir, target);
        if (!fs.existsSync(subprdPath)) continue;
        for (const ref of extractApiRefs(readFile(subprdPath))) {
            if (!apiRefs.has(ref)) {
                issues.push(
                    makeIssue(
                        'crosscheck.api-path-missing',
                        'fail',
                        subprdPath,
                        'API 引用',
                        `${ref} exists in foundation-api`,
                        'Missing',
                        '修正 subprd 接口引用，或记录待回溯 foundation-builder 缺口。',
                        `node ${__filename} crosscheck --host-dir ${quote(paths.hostDir)} --slug ${paths.slug} --json`,
                        { ref }
                    )
                );
            }
        }
    }
    return issues;
}

function validateInteractionReferences(paths, subprdTargets) {
    const interactionPath = path.join(paths.hostDir, 'src', 'frontend', 'page-preview', `explainer-b-interaction-${paths.slug}.md`);
    if (!fs.existsSync(interactionPath)) return [];
    const lockedIds = extractLockedInteractionIds(readFile(interactionPath));
    const issues = [];
    for (const target of subprdTargets) {
        const subprdPath = path.resolve(paths.prdDir, target);
        if (!fs.existsSync(subprdPath)) continue;
        const ids = extractInteractionIds(readFile(subprdPath));
        if (ids.length === 0) {
            issues.push(
                makeIssue(
                    'crosscheck.interaction-id-missing',
                    'needs_ai_review',
                    subprdPath,
                    'X.1 交互语义引用',
                    'At least one locked id or — when no interaction exists',
                    'Missing',
                    '补齐 `**交互语义引用**：` 槽位；无交互时写 `—` 并人工复核。',
                    `node ${__filename} crosscheck --host-dir ${quote(paths.hostDir)} --slug ${paths.slug} --json`
                )
            );
            continue;
        }
        for (const id of ids) {
            if (id === '—' || id === '-') continue;
            if (!lockedIds.has(id)) {
                issues.push(
                    makeIssue(
                        'crosscheck.interaction-id-invalid',
                        'fail',
                        subprdPath,
                        'X.1 交互语义引用',
                        `${id} exists in explainer and status == locked`,
                        'Missing or not locked',
                        '改为引用 explainer-b-interaction 中 status=locked 的语义 id，或回溯 page-explainer。',
                        `node ${__filename} crosscheck --host-dir ${quote(paths.hostDir)} --slug ${paths.slug} --json`,
                        { id }
                    )
                );
            }
        }
    }
    return issues;
}

function validatePageCoverage(paths, fRows) {
    const deliveryPath = path.join(paths.hostDir, 'src', 'frontend', 'page-preview', `page-delivery-${paths.slug}.md`);
    if (!fs.existsSync(deliveryPath)) return [];
    const deliveryPages = extractPageDeliveryPages(readFile(deliveryPath));
    const featurePages = new Set(fRows.map((row) => row.page));
    const issues = [];
    for (const page of deliveryPages) {
        if (!featurePages.has(page)) {
            issues.push(
                makeIssue(
                    'crosscheck.page-coverage-missing',
                    'fail',
                    paths.featureList,
                    '## 功能总表',
                    `${page} covered in feature-list`,
                    'Missing',
                    '补齐 page-delivery 页面对应的功能总表行和页面布局全景。',
                    `node ${__filename} crosscheck --host-dir ${quote(paths.hostDir)} --slug ${paths.slug} --json`,
                    { page }
                )
            );
        }
    }
    return issues;
}

function progress({ hostDir, slug }) {
    const paths = resolvePrdPaths(hostDir, slug);
    // 功能列表不存在时不能伪装成 phase 4：要么 --host-dir/--slug 写错，要么 Phase 2 还没开始。
    if (!fs.existsSync(paths.featureList)) {
        return report('progress', [
            makeIssue(
                'progress.feature-list-missing',
                'fail',
                paths.featureList,
                'file',
                `Existing ${path.basename(paths.featureList)} (prd-writer Phase 2 artifact)`,
                'Missing',
                '功能列表不存在：先核对 --host-dir 与 --slug 是否拼写正确；确认无误则说明 PRD 尚未开始（not-started），从 Phase 2 产出功能列表。',
                `node ${__filename} progress --host-dir ${quote(hostDir)} --slug ${slug} --json`
            )
        ], { phase: null, state: 'not-started', blocks: [], mainprdBlocks: [], pending: [] });
    }
    const fRows = featureRows(readFile(paths.featureList));
    const mRows = fs.existsSync(paths.mainprd) ? mainRows(readFile(paths.mainprd)) : [];
    // 文件在但功能总表解析不出任何区块行，同样不能报 "phase 4 无待办"。
    if (fRows.length === 0) {
        return report('progress', [
            makeIssue(
                'progress.feature-table-empty',
                'fail',
                paths.featureList,
                '## 功能总表',
                'At least one block row under the fixed header',
                '0 rows',
                '功能总表没有可解析的区块行：先跑 structure 校验并按 feature-list 模板补齐功能总表。',
                `node ${__filename} structure --file ${quote(paths.featureList)} --json`
            )
        ], { phase: null, state: 'feature-list-empty', blocks: [], mainprdBlocks: mRows.map((row) => ({ index: row.index, page: row.page, block: row.block, status: row.status })), pending: [] });
    }
    const pending = fRows.filter((row) => row.status !== '已确认');
    return report('progress', [], {
        phase: pending.length === 0 ? 5 : 4,
        state: 'in-progress',
        blocks: fRows.map((row) => ({ index: row.index, page: row.page, block: row.block, status: row.status })),
        mainprdBlocks: mRows.map((row) => ({ index: row.index, page: row.page, block: row.block, status: row.status })),
        pending
    });
}

function setStatus({ hostDir, slug, block, status }) {
    if (!VALID_STATUSES.has(status)) {
        return report('set-status', [
            makeIssue(
                'set-status.invalid-status',
                'fail',
                '',
                'status',
                [...VALID_STATUSES].join(' / '),
                status,
                '使用固定三态之一。',
                `node ${__filename} progress --host-dir ${quote(hostDir)} --slug ${slug} --json`
            )
        ]);
    }
    const paths = resolvePrdPaths(hostDir, slug);
    // 先只读检查两张表都有目标区块行，再统一写入：
    // 1) 区块号打错时必须显式 fail（匹配 0 行静默返回 ok 会造成索引漂移假象）；
    // 2) 避免只写成功一张表、加剧双表漂移。
    const targets = [
        { filePath: paths.featureList, headers: FEATURE_HEADERS, section: '## 功能总表' },
        { filePath: paths.mainprd, headers: MAIN_HEADERS, section: '## subprd索引' }
    ];
    const issues = [];
    for (const target of targets) {
        const blocks = listTableBlocks(target.filePath, target.headers);
        if (!blocks.includes(String(block))) {
            issues.push(
                makeIssue(
                    'set-status.block-not-found',
                    'fail',
                    target.filePath,
                    target.section,
                    `--block matches an existing row id: ${blocks.length > 0 ? blocks.join(', ') : '(table has no rows)'}`,
                    String(block),
                    '用表中已有的区块号重跑 set-status；若该区块行本就缺失，先按模板补齐功能总表 / mainprd 索引行。',
                    `node ${__filename} progress --host-dir ${quote(hostDir)} --slug ${slug} --json`,
                    { block, availableBlocks: blocks }
                )
            );
        }
    }
    if (issues.length > 0) {
        return report('set-status', issues, { block, status });
    }
    updateTableStatus(paths.featureList, FEATURE_HEADERS, block, status);
    updateTableStatus(paths.mainprd, MAIN_HEADERS, block, status);
    return report('set-status', [], { block, status });
}

function listTableBlocks(filePath, headers) {
    const table = findTable(readFile(filePath), headers);
    if (!table) throw new Error(`Cannot find table in ${filePath}: ${headers.join(' | ')}`);
    return table.rows.map((row) => row.cells[0]);
}

function syncIndex({ hostDir, slug }) {
    const paths = resolvePrdPaths(hostDir, slug);
    const fRows = featureRows(readFile(paths.featureList));
    const newTable = [
        '| # | 区块 | 所属页面 | subprd文件 | 状态 |',
        '|---|------|---------|-----------|------|',
        ...fRows.map((row) => `| ${row.index} | ${row.block} | ${row.page} | [${path.basename(row.target)}](${row.target}) | ${row.status} |`)
    ].join('\n');
    replaceTable(paths.mainprd, MAIN_HEADERS, newTable);
    return report('sync-index', [], { rows: fRows.length });
}

function updateTableStatus(filePath, headers, block, status) {
    const content = readFile(filePath);
    const lines = content.split('\n');
    const table = findTable(content, headers);
    if (!table) throw new Error(`Cannot find table in ${filePath}: ${headers.join(' | ')}`);
    const statusIndex = headers.indexOf('状态');
    for (const row of table.rows) {
        if (row.cells[0] === String(block)) {
            row.cells[statusIndex] = status;
            lines[row.lineNumber - 1] = `| ${row.cells.join(' | ')} |`;
        }
    }
    writeFile(filePath, lines.join('\n'));
}

function replaceTable(filePath, headers, newTable) {
    const content = readFile(filePath);
    const lines = content.split('\n');
    const table = findTable(content, headers);
    if (!table) throw new Error(`Cannot find table in ${filePath}: ${headers.join(' | ')}`);
    lines.splice(table.startLine - 1, table.endLine - table.startLine + 1, ...newTable.split('\n'));
    writeFile(filePath, lines.join('\n'));
}

function resolvePrdPaths(hostDir, slug) {
    const prdDir = path.join(hostDir, 'docs', 'prd');
    return {
        hostDir,
        slug,
        prdDir,
        featureList: path.join(prdDir, `prd-feature-list-${slug}.md`),
        mainprd: path.join(prdDir, `mainprd-${slug}.md`)
    };
}

function featureRows(content) {
    const table = findTable(content, FEATURE_HEADERS);
    if (!table) return [];
    return table.rows.map((row) => ({
        index: row.cells[0],
        page: stripMarkdown(row.cells[1]),
        block: stripMarkdown(row.cells[2]),
        description: row.cells[3],
        rawPath: row.cells[4],
        target: normalizeMarkdownLinkTarget(row.cells[4]),
        status: stripMarkdown(row.cells[5])
    }));
}

function mainRows(content) {
    const table = findTable(content, MAIN_HEADERS);
    if (!table) return [];
    return table.rows.map((row) => ({
        index: row.cells[0],
        block: stripMarkdown(row.cells[1]),
        page: stripMarkdown(row.cells[2]),
        rawPath: row.cells[3],
        target: normalizeMarkdownLinkTarget(row.cells[3]),
        status: stripMarkdown(row.cells[4])
    }));
}

function extractSection(content, heading) {
    const lines = content.split('\n');
    const start = lines.findIndex((line) => line.trim() === heading);
    if (start === -1) return null;
    let end = lines.length;
    for (let i = start + 1; i < lines.length; i += 1) {
        if (/^##\s+/.test(lines[i]) && lines[i].trim() !== heading) {
            end = i;
            break;
        }
    }
    return { heading, content: lines.slice(start + 1, end).join('\n'), startLine: start + 1, endLine: end };
}

function extractHeadingContent(content, heading) {
    const lines = content.split('\n');
    const start = lines.findIndex((line) => line.trim() === heading);
    if (start === -1) return null;
    const level = heading.match(/^#+/)?.[0].length || 1;
    let end = lines.length;
    for (let i = start + 1; i < lines.length; i += 1) {
        const match = lines[i].match(/^(#+)\s+/);
        if (match && match[1].length <= level) {
            end = i;
            break;
        }
    }
    return lines.slice(start + 1, end).join('\n');
}

function extractSubsections(content, headingPattern) {
    const lines = content.split('\n');
    const starts = [];
    for (let i = 0; i < lines.length; i += 1) {
        const match = lines[i].match(headingPattern);
        if (match) {
            starts.push({ lineIndex: i, titleMatch: match, title: lines[i].trim() });
        }
    }
    return starts.map((item, index) => {
        const next = starts[index + 1];
        return {
            ...item,
            content: lines.slice(item.lineIndex + 1, next ? next.lineIndex : lines.length).join('\n')
        };
    });
}

function countCodeFences(content) {
    return [...content.matchAll(/^```/gm)].length / 2;
}

function countCircledNumbers(content) {
    return [...content.matchAll(new RegExp(`[${CIRCLED_NUMBERS}]`, 'gu'))].length;
}

function extractCircledNumbers(content) {
    return [...content.matchAll(new RegExp(`[${CIRCLED_NUMBERS}]`, 'gu'))].map((match) => match[0]);
}

function circledNumberForIndex(index) {
    return Array.from(CIRCLED_NUMBERS)[index - 1] || '';
}

function sameCircledMultiset(left, right) {
    return normalizeCircledList(left).join('') === normalizeCircledList(right).join('');
}

function normalizeCircledList(items) {
    const order = new Map(Array.from(CIRCLED_NUMBERS).map((item, index) => [item, index]));
    return [...items].sort((a, b) => (order.get(a) ?? 999) - (order.get(b) ?? 999));
}

function extractSchemaFieldRefs(content) {
    const refs = new Set();
    const sections = extractSubsections(content, /^#{2,3}\s+.+?`([^`]+)`.*$/u);
    for (const section of sections) {
        const tableName = section.titleMatch[1];
        const table = parseMarkdownTables(section.content).find((item) => item.headers.includes('字段'));
        if (!table) continue;
        const fieldIndex = table.headers.indexOf('字段');
        for (const row of table.rows) {
            const field = stripMarkdown(row.cells[fieldIndex]);
            if (field) refs.add(`${tableName}.${field}`);
        }
    }
    return refs;
}

function extractDataLinkRefs(content) {
    const refs = new Set();
    for (const table of parseMarkdownTables(content)) {
        if (!headersEqual(table.headers, DATA_LINK_HEADERS)) continue;
        for (const row of table.rows) {
            for (const cell of [row.cells[3], row.cells[4]]) {
                if (stripMarkdown(cell) === '—') continue;
                for (const match of cell.matchAll(/`([A-Za-z_][\w]*\.[A-Za-z_][\w]*)`/g)) {
                    refs.add(match[1]);
                }
            }
        }
    }
    return refs;
}

function extractApiRefs(content) {
    const refs = new Set();
    for (const table of parseMarkdownTables(content)) {
        const methodIndex = table.headers.findIndex((header) => header === '方法' || header === 'Method');
        const pathIndex = table.headers.findIndex((header) => header === '路径' || header === 'Path');
        if (methodIndex === -1 || pathIndex === -1) continue;
        for (const row of table.rows) {
            const method = stripMarkdown(row.cells[methodIndex]).toUpperCase();
            const apiPath = stripMarkdown(row.cells[pathIndex]);
            if (method && apiPath.startsWith('/')) refs.add(`${method} ${normalizeApiPath(apiPath)}`);
        }
    }

    const noCode = withoutCodeFences(content);
    for (const match of noCode.matchAll(/\b(GET|POST|PUT|PATCH|DELETE)\s+(\/[A-Za-z0-9_./:{}-]+)/g)) {
        refs.add(`${match[1].toUpperCase()} ${normalizeApiPath(match[2])}`);
    }
    return refs;
}

function normalizeApiPath(value) {
    return value
        .replace(/[),，）。]+$/g, '')
        .replace(/\{([^}]+)\}/g, ':$1')
        .replace(/\/+/g, '/');
}

function extractLockedInteractionIds(content) {
    const ids = new Set();
    for (const table of parseMarkdownTables(content)) {
        const idIndex = table.headers.findIndex((header) => header === 'id');
        const statusIndex = table.headers.findIndex((header) => header === 'status');
        if (idIndex === -1 || statusIndex === -1) continue;
        for (const row of table.rows) {
            if (row.cells[statusIndex].toLowerCase() === 'locked') ids.add(row.cells[idIndex]);
        }
    }
    return ids;
}

function extractInteractionIds(content) {
    const ids = [];
    for (const match of content.matchAll(/\*\*交互语义引用\*\*：([^\n]+)/g)) {
        const raw = match[1].trim();
        const backticks = [...raw.matchAll(/`([^`]+)`/g)].map((item) => item[1].trim());
        if (backticks.length > 0) ids.push(...backticks);
        else ids.push(...raw.split(/[、,，\s]+/).map((item) => item.trim()).filter(Boolean));
    }
    return ids;
}

function extractPageDeliveryPages(content) {
    const pages = new Set();
    for (const table of parseMarkdownTables(content)) {
        const pageIndex = table.headers.indexOf('页面');
        if (pageIndex === -1) continue;
        const routeIndex = table.headers.indexOf('路由');
        for (const row of table.rows) {
            if (routeIndex !== -1) {
                const route = stripMarkdown(row.cells[routeIndex]);
                if (!route.startsWith('/')) continue;
            }
            const page = stripMarkdown(row.cells[pageIndex]);
            if (page) pages.add(page);
        }
    }
    return pages;
}

function escapeRegExp(value) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function quote(value) {
    return JSON.stringify(value);
}

function parseArgs(argv) {
    const args = argv.slice(2);
    const command = args.shift();
    const options = { command, json: false };
    for (let i = 0; i < args.length; i += 1) {
        const arg = args[i];
        if (arg === '--json') {
            options.json = true;
            continue;
        }
        if (arg === '--file') {
            options.filePath = args[++i];
            continue;
        }
        if (arg === '--host-dir') {
            options.hostDir = args[++i];
            continue;
        }
        if (arg === '--slug') {
            options.slug = args[++i];
            continue;
        }
        if (arg === '--block') {
            options.block = args[++i];
            continue;
        }
        if (arg === '--status') {
            options.status = args[++i];
            continue;
        }
        throw new Error(`Unknown argument: ${arg}`);
    }
    return options;
}

function printUsage() {
    console.log('Usage: prd-check.mjs <structure|crosscheck|progress|sync-index|set-status> [options] [--json]');
}

function run(options) {
    switch (options.command) {
        case 'structure':
            if (!options.filePath) throw new Error('Missing --file <path>');
            return structure({ filePath: options.filePath });
        case 'crosscheck':
            if (!options.hostDir || !options.slug) throw new Error('Missing --host-dir <path> or --slug <slug>');
            return crosscheck({ hostDir: options.hostDir, slug: options.slug });
        case 'progress':
            if (!options.hostDir || !options.slug) throw new Error('Missing --host-dir <path> or --slug <slug>');
            return progress({ hostDir: options.hostDir, slug: options.slug });
        case 'sync-index':
            if (!options.hostDir || !options.slug) throw new Error('Missing --host-dir <path> or --slug <slug>');
            return syncIndex({ hostDir: options.hostDir, slug: options.slug });
        case 'set-status':
            if (!options.hostDir || !options.slug || !options.block || !options.status) {
                throw new Error('Missing --host-dir <path>, --slug <slug>, --block <N>, or --status <状态>');
            }
            return setStatus({ hostDir: options.hostDir, slug: options.slug, block: options.block, status: options.status });
        default:
            throw new Error(`Unknown command: ${options.command || ''}`);
    }
}

function main() {
    const options = parseArgs(process.argv);
    const result = run(options);
    if (options.json) {
        console.log(JSON.stringify(result, null, 2));
    } else {
        console.log(formatHuman(result));
    }
    if (result.summary.fail > 0) process.exitCode = FAIL_EXIT;
    else if (result.summary.needs_ai_review > 0) process.exitCode = REVIEW_EXIT;
}

function formatHuman(result) {
    const lines = [
        `Command: ${result.command}`,
        `OK: ${result.ok ? 'yes' : 'no'}`,
        `Summary: fail=${result.summary.fail}, warn=${result.summary.warn}, needs_ai_review=${result.summary.needs_ai_review}`
    ];
    for (const issue of result.issues) {
        lines.push(`- [${issue.severity}] ${issue.ruleId}: ${issue.section}`);
        lines.push(`  expected: ${issue.expected}`);
        lines.push(`  actual: ${issue.actual}`);
        lines.push(`  fix: ${issue.fixHint}`);
        lines.push(`  next: ${issue.nextCommand}`);
    }
    return lines.join('\n');
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
    try {
        main();
    } catch (error) {
        const fatal = {
            ok: false,
            command: 'fatal',
            summary: { fail: 1, warn: 0, needs_ai_review: 0 },
            issues: [
                makeIssue(
                    'prd-check.fatal',
                    'fail',
                    '',
                    'cli',
                    'Valid command and readable files',
                    error.message,
                    '检查命令参数和文件路径。可用命令：structure --file <path> / crosscheck|progress|sync-index --host-dir <host> --slug <slug> / set-status --host-dir <host> --slug <slug> --block <N> --status <状态>。',
                    `node ${__filename} structure --file <path> --json`
                )
            ]
        };
        if (process.argv.includes('--json')) console.log(JSON.stringify(fatal, null, 2));
        else {
            printUsage();
            console.error(error.message);
        }
        process.exit(1);
    }
}

export {
    structure,
    crosscheck,
    progress,
    syncIndex,
    setStatus,
    parseMarkdownTables
};
