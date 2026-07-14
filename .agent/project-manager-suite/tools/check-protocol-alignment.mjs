#!/usr/bin/env node

/**
 * Traceability:
 * Rule sources:
 * - skills/00-01-ai-project-manager/SKILL.md
 * - skills/00-01-ai-project-manager/references/core/runtime.md
 * - skills/00-01-ai-project-manager/references/core/global-files-protocol.md
 * - skills/00-01-ai-project-manager/references/core/routing.md
 * Structured config:
 * - lib/ai-pm-protocol/*.js
 * - lib/bootstrap/index.js
 */
import fs from 'fs';
import path from 'path';
import process from 'process';
import { execFileSync } from 'child_process';
import { fileURLToPath } from 'url';
import { changeImpactMap } from '../lib/ai-pm-protocol/index.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEFAULT_SUITE_ROOT = path.resolve(__dirname, '..');

const PROTOCOL_DOCS = [
    'skills/00-01-ai-project-manager/SKILL.md',
    'skills/00-01-ai-project-manager/references/core/runtime.md',
    'skills/00-01-ai-project-manager/references/core/global-files-protocol.md',
    'skills/00-01-ai-project-manager/references/core/routing.md'
];

const STRUCTURED_ROOTS = ['lib/ai-pm-protocol', 'lib/bootstrap'];

function printUsage() {
    console.log(
        'Usage: node <suite-path>/tools/check-protocol-alignment.mjs [suite-root] [--json] [--changed file-a,file-b]'
    );
    console.log(
        '<suite-path> 指套件根目录：源码仓库联调时为 project-manager-suite/，安装到宿主后为 .agent/project-manager-suite/；命令默认在宿主项目根目录执行。'
    );
}

function parseArgs(argv) {
    const args = argv.slice(2);
    const options = {
        suiteRoot: DEFAULT_SUITE_ROOT,
        json: false,
        changedFiles: []
    };

    for (let i = 0; i < args.length; i += 1) {
        const arg = args[i];

        if (arg === '--json') {
            options.json = true;
            continue;
        }

        if (arg === '--changed') {
            const nextArg = args[i + 1];
            if (!nextArg) {
                throw new Error('Missing value for --changed');
            }

            options.changedFiles = nextArg
                .split(',')
                .map((item) => item.trim())
                .filter(Boolean);
            i += 1;
            continue;
        }

        if (options.suiteRoot === DEFAULT_SUITE_ROOT) {
            options.suiteRoot = path.resolve(process.cwd(), arg);
            continue;
        }

        throw new Error(`Unknown argument: ${arg}`);
    }

    return options;
}

function normalizeRelative(rootDir, targetPath) {
    return path.relative(rootDir, targetPath).split(path.sep).join('/');
}

function buildIssue(severity, code, message, details = {}) {
    return { severity, code, message, ...details };
}

function normalizeRepoPath(inputPath) {
    return inputPath.replace(/^\.\/+/, '').split(path.sep).join('/');
}

function detectGitChangedFiles(suiteRoot) {
    try {
        const repoRoot = execFileSync('git', ['-C', suiteRoot, 'rev-parse', '--show-toplevel'], {
            encoding: 'utf8',
            stdio: ['ignore', 'pipe', 'ignore']
        }).trim();

        const statusOutput = execFileSync('git', ['-C', repoRoot, 'status', '--porcelain', '-z'], {
            encoding: 'utf8',
            stdio: ['ignore', 'pipe', 'ignore']
        });

        // `--porcelain -z` 的输出以 NUL 分隔且路径不做引号转义：每条形如 "XY <path>"。
        // XY 是两位状态码，未暂存修改是 " M"（首位为空格），因此不能 trim 整条记录，
        // 只能按固定位置取值：slice(0, 2) 是状态码，slice(3) 是路径。
        // 重命名/复制（R/C）条目后面还跟一条独立的“原路径”记录，需要跳过。
        const entries = statusOutput.split('\0').filter((entry) => entry.length > 0);
        const changedFiles = [];

        for (let i = 0; i < entries.length; i += 1) {
            const entry = entries[i];
            const statusCode = entry.slice(0, 2);
            const filePath = entry.slice(3);

            if (statusCode.startsWith('R') || statusCode.startsWith('C')) {
                i += 1;
            }

            if (!filePath) {
                continue;
            }

            changedFiles.push(normalizeRepoPath(path.relative(suiteRoot, path.join(repoRoot, filePath))));
        }

        return {
            mode: 'git-auto',
            repoRoot,
            changedFiles: changedFiles.filter((item) => item && !item.startsWith('..')).sort()
        };
    } catch {
        return {
            mode: 'none',
            repoRoot: null,
            changedFiles: []
        };
    }
}

function extractStructuredImplementations(docContent) {
    const lines = docContent.split('\n');
    const results = [];
    let inStructuredSection = false;

    for (const rawLine of lines) {
        const line = rawLine.trim();

        if (line === '- 结构化实现：') {
            inStructuredSection = true;
            continue;
        }

        if (!inStructuredSection) {
            continue;
        }

        if (line.startsWith('- 对应脚本：') || line.startsWith('- 平台注入入口：') || line === '维护原则：') {
            break;
        }

        const match = line.match(/^-\s+`(.+)`$/);
        if (match) {
            results.push(match[1]);
        }
    }

    return results;
}

function extractTraceabilityRuleSources(fileContent) {
    const match = fileContent.match(/\/\*\*([\s\S]*?)\*\//);
    if (!match || !match[1].includes('Traceability:')) {
        return [];
    }

    const lines = match[1].split('\n').map((line) => line.replace(/^\s*\*\s?/, '').trim());
    const sources = [];
    let inRuleSources = false;

    for (const line of lines) {
        if (line === 'Rule sources:') {
            inRuleSources = true;
            continue;
        }

        if (!inRuleSources) {
            continue;
        }

        if (/^[A-Za-z][A-Za-z ]+:$/.test(line)) {
            break;
        }

        const sourceMatch = line.match(/^-\s+(.+)$/);
        if (sourceMatch) {
            sources.push(sourceMatch[1].trim());
        }
    }

    return sources;
}

function collectStructuredFiles(suiteRoot) {
    const files = [];

    for (const relativeRoot of STRUCTURED_ROOTS) {
        const absoluteRoot = path.join(suiteRoot, relativeRoot);
        if (!fs.existsSync(absoluteRoot)) {
            continue;
        }

        for (const entry of fs.readdirSync(absoluteRoot, { withFileTypes: true })) {
            if (entry.isFile() && entry.name.endsWith('.js')) {
                files.push(path.join(absoluteRoot, entry.name));
            }
        }
    }

    return files.sort();
}

function analyzeChangeImpact(changedFiles = []) {
    const normalizedChangedFiles = changedFiles.map((item) => normalizeRepoPath(item));
    const impactedFamilies = [];
    const recommendedReviewFiles = new Set();
    const unmatchedChangedFiles = [];

    for (const changedFile of normalizedChangedFiles) {
        let matched = false;

        for (const [familyId, definition] of Object.entries(changeImpactMap)) {
            const relatedPool = [
                ...(definition.currentAuthority || []),
                ...(definition.targetAuthority || []),
                ...(definition.checkAlso || [])
            ].map((item) => normalizeRepoPath(item));

            if (!relatedPool.includes(changedFile)) {
                continue;
            }

            matched = true;

            let impactedFamily = impactedFamilies.find((item) => item.familyId === familyId);
            if (!impactedFamily) {
                impactedFamily = {
                    familyId,
                    description: definition.description,
                    triggeredBy: [],
                    currentAuthority: definition.currentAuthority || [],
                    targetAuthority: definition.targetAuthority || [],
                    checkAlso: definition.checkAlso || []
                };
                impactedFamilies.push(impactedFamily);
            }

            if (!impactedFamily.triggeredBy.includes(changedFile)) {
                impactedFamily.triggeredBy.push(changedFile);
            }

            for (const relatedFile of relatedPool) {
                if (relatedFile !== changedFile) {
                    recommendedReviewFiles.add(relatedFile);
                }
            }
        }

        if (!matched) {
            unmatchedChangedFiles.push(changedFile);
        }
    }

    impactedFamilies.sort((a, b) => a.familyId.localeCompare(b.familyId));

    return {
        changedFiles: normalizedChangedFiles,
        impactedFamilies,
        recommendedReviewFiles: Array.from(recommendedReviewFiles).sort(),
        unmatchedChangedFiles
    };
}

function checkProtocolAlignment({ suiteRoot = DEFAULT_SUITE_ROOT, changedFiles = [] }) {
    const resolvedSuiteRoot = path.resolve(suiteRoot);
    const issues = [];
    const protocolMap = {};
    const changeSource =
        changedFiles.length > 0
            ? {
                  mode: 'explicit',
                  repoRoot: null,
                  changedFiles: changedFiles.map((item) => normalizeRepoPath(item))
              }
            : detectGitChangedFiles(resolvedSuiteRoot);

    for (const relativeDocPath of PROTOCOL_DOCS) {
        const absoluteDocPath = path.join(resolvedSuiteRoot, relativeDocPath);
        if (!fs.existsSync(absoluteDocPath)) {
            issues.push(
                buildIssue('error', 'missing_protocol_doc', `Protocol doc not found: ${relativeDocPath}`, {
                    docPath: relativeDocPath
                })
            );
            continue;
        }

        const content = fs.readFileSync(absoluteDocPath, 'utf8');
        const structuredImplementations = extractStructuredImplementations(content);
        protocolMap[relativeDocPath] = structuredImplementations;

        if (structuredImplementations.length === 0) {
            issues.push(
                buildIssue('error', 'missing_structured_mapping', `No structured implementation mapping found in ${relativeDocPath}`, {
                    docPath: relativeDocPath
                })
            );
        }

        for (const relativeStructuredPath of structuredImplementations) {
            const absoluteStructuredPath = path.join(resolvedSuiteRoot, relativeStructuredPath);
            if (!fs.existsSync(absoluteStructuredPath)) {
                issues.push(
                    buildIssue(
                        'error',
                        'missing_structured_file',
                        `${relativeDocPath} references missing structured file ${relativeStructuredPath}`,
                        {
                            docPath: relativeDocPath,
                            structuredPath: relativeStructuredPath
                        }
                    )
                );
                continue;
            }

            const sources = extractTraceabilityRuleSources(fs.readFileSync(absoluteStructuredPath, 'utf8'));
            if (sources.length === 0) {
                issues.push(
                    buildIssue(
                        'error',
                        'missing_traceability_header',
                        `Structured file ${relativeStructuredPath} is missing Traceability rule sources`,
                        {
                            docPath: relativeDocPath,
                            structuredPath: relativeStructuredPath
                        }
                    )
                );
                continue;
            }

            if (!sources.includes(relativeDocPath)) {
                issues.push(
                    buildIssue(
                        'error',
                        'missing_reverse_link',
                        `Structured file ${relativeStructuredPath} does not point back to ${relativeDocPath}`,
                        {
                            docPath: relativeDocPath,
                            structuredPath: relativeStructuredPath,
                            traceabilitySources: sources
                        }
                    )
                );
            }
        }
    }

    const structuredFiles = collectStructuredFiles(resolvedSuiteRoot);
    for (const absoluteStructuredPath of structuredFiles) {
        const relativeStructuredPath = normalizeRelative(resolvedSuiteRoot, absoluteStructuredPath);
        const sources = extractTraceabilityRuleSources(fs.readFileSync(absoluteStructuredPath, 'utf8'));

        if (sources.length === 0) {
            continue;
        }

        for (const sourceDocPath of sources) {
            if (!PROTOCOL_DOCS.includes(sourceDocPath)) {
                continue;
            }

            const mappedFiles = protocolMap[sourceDocPath] || [];
            if (!mappedFiles.includes(relativeStructuredPath)) {
                issues.push(
                    buildIssue(
                        'error',
                        'missing_forward_link',
                        `Protocol doc ${sourceDocPath} does not list structured file ${relativeStructuredPath}`,
                        {
                            docPath: sourceDocPath,
                            structuredPath: relativeStructuredPath
                        }
                    )
                );
            }
        }
    }

    const summary = {
        errors: issues.filter((item) => item.severity === 'error').length,
        warnings: issues.filter((item) => item.severity === 'warning').length,
        infos: issues.filter((item) => item.severity === 'info').length
    };

    const changeImpact = {
        source: changeSource.mode,
        repoRoot: changeSource.repoRoot,
        ...analyzeChangeImpact(changeSource.changedFiles)
    };

    return {
        suiteRoot: resolvedSuiteRoot,
        protocolDocs: PROTOCOL_DOCS,
        protocolMap,
        scannedStructuredFiles: structuredFiles.map((item) => normalizeRelative(resolvedSuiteRoot, item)),
        changeImpact,
        issues,
        summary
    };
}

function formatTextReport(result) {
    const lines = [
        `Suite root: ${result.suiteRoot}`,
        `Protocol docs checked: ${result.protocolDocs.length}`,
        `Structured files scanned: ${result.scannedStructuredFiles.length}`,
        `Errors: ${result.summary.errors}`,
        `Warnings: ${result.summary.warnings}`,
        `Info: ${result.summary.infos}`
    ];

    lines.push('', 'Mappings:');
    for (const [docPath, structuredFiles] of Object.entries(result.protocolMap)) {
        lines.push(`- ${docPath}: ${structuredFiles.length > 0 ? structuredFiles.join(', ') : 'none'}`);
    }

    if (result.changeImpact.changedFiles.length > 0) {
        lines.push('', 'Change impact:');
        lines.push(`- Source: ${result.changeImpact.source}`);
        lines.push(`- Changed files: ${result.changeImpact.changedFiles.join(', ')}`);

        if (result.changeImpact.impactedFamilies.length === 0) {
            lines.push('- Impacted rule families: none matched');
        } else {
            lines.push('- Impacted rule families:');
            for (const family of result.changeImpact.impactedFamilies) {
                lines.push(
                    `  - ${family.familyId}: triggered by ${family.triggeredBy.join(', ')} | review ${family.checkAlso.join(', ')}`
                );
            }
        }

        lines.push(
            `- Recommended review files: ${
                result.changeImpact.recommendedReviewFiles.length > 0
                    ? result.changeImpact.recommendedReviewFiles.join(', ')
                    : 'none'
            }`
        );

        if (result.changeImpact.unmatchedChangedFiles.length > 0) {
            lines.push(`- Unmatched changed files: ${result.changeImpact.unmatchedChangedFiles.join(', ')}`);
        }
    } else if (result.changeImpact.source === 'git-auto') {
        lines.push('', 'Change impact:');
        lines.push('- Source: git-auto');
        lines.push('- Changed files: none detected in current git working tree');
    }

    lines.push('', 'Issues:');
    if (result.issues.length === 0) {
        lines.push('- none');
    } else {
        for (const issue of result.issues) {
            lines.push(`- [${issue.severity}] ${issue.code}: ${issue.message}`);
        }
    }

    return lines.join('\n');
}

function main() {
    const options = parseArgs(process.argv);
    const result = checkProtocolAlignment(options);

    if (options.json) {
        console.log(JSON.stringify(result, null, 2));
        return;
    }

    console.log(formatTextReport(result));

    if (result.summary.errors > 0) {
        process.exitCode = 1;
    }
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

export { checkProtocolAlignment, formatTextReport };
