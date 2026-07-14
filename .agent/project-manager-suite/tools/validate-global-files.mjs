#!/usr/bin/env node

/**
 * Traceability:
 * Rule sources:
 * - skills/00-01-ai-project-manager/references/core/global-files-protocol.md
 * Structured config:
 * - lib/ai-pm-protocol/field-contracts.js
 * - lib/ai-pm-protocol/validation.js
 */
import fs from 'fs';
import path from 'path';
import process from 'process';
import { fileURLToPath } from 'url';
import {
    FILE_ROLE_IDS,
    fileRoles,
    fieldPackages,
    fileContracts,
    resolveDevlogDirectory,
    rulesSyncPolicy,
    validationPolicy
} from '../lib/ai-pm-protocol/index.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function printUsage() {
    console.log(
        'Usage: node <suite-path>/tools/validate-global-files.mjs <host-project-root> [--json]'
    );
    console.log(
        '<suite-path> 指套件根目录：源码仓库联调时为 project-manager-suite/，安装到宿主后为 .agent/project-manager-suite/；命令默认在宿主项目根目录执行。'
    );
}

function parseArgs(argv) {
    const args = argv.slice(2);
    const options = {
        hostRoot: '',
        json: false
    };

    for (const arg of args) {
        if (arg === '--json') {
            options.json = true;
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

    return options;
}

function normalizePathForMatch(hostRoot, targetPath) {
    return path.relative(hostRoot, targetPath).split(path.sep).join('/');
}

function shouldIgnoreDir(relativeDir) {
    return validationPolicy.scan.ignoredDirectories.some((ignored) => {
        return relativeDir === ignored || relativeDir.startsWith(`${ignored}/`);
    });
}

function walkMarkdownFiles(rootDir, maxDepth) {
    const results = [];

    function recurse(currentDir, depth) {
        if (depth > maxDepth) return;

        const entries = fs.readdirSync(currentDir, { withFileTypes: true });
        for (const entry of entries) {
            const fullPath = path.join(currentDir, entry.name);
            const relativePath = normalizePathForMatch(rootDir, fullPath);

            if (entry.isDirectory()) {
                if (shouldIgnoreDir(relativePath)) {
                    continue;
                }
                recurse(fullPath, depth + 1);
                continue;
            }

            if (
                entry.isFile() &&
                validationPolicy.scan.includeExtensions.some((ext) => entry.name.endsWith(ext))
            ) {
                results.push(fullPath);
            }
        }
    }

    recurse(rootDir, 0);
    return results.sort();
}

function scoreRoleCandidate(hostRoot, filePath, rolePolicy, content) {
    const relativePath = normalizePathForMatch(hostRoot, filePath);
    const baseName = path.basename(filePath);
    let score = 0;

    if ((rolePolicy.filenameMatchers || []).includes(baseName)) {
        score += 3;
    }

    if ((rolePolicy.pathMatchers || []).includes(relativePath)) {
        score += 3;
    }

    for (const marker of rolePolicy.contentMarkers || []) {
        if (content.includes(marker)) {
            score += 1;
        }
    }

    return score;
}

function findAuthorityCandidates(hostRoot, markdownFiles, roleId) {
    const rolePolicy = validationPolicy.roles[roleId];
    const candidates = [];

    for (const filePath of markdownFiles) {
        const content = fs.readFileSync(filePath, 'utf8');
        const score = scoreRoleCandidate(hostRoot, filePath, rolePolicy, content);

        if (score >= (rolePolicy.minimumScore || 0)) {
            candidates.push({
                filePath,
                relativePath: normalizePathForMatch(hostRoot, filePath),
                score
            });
        }
    }

    candidates.sort((a, b) => b.score - a.score || a.relativePath.localeCompare(b.relativePath));
    return candidates;
}

function resolveAuthority(candidates, roleId) {
    if (candidates.length === 0) {
        return {
            roleId,
            resolved: null,
            duplicates: []
        };
    }

    const [resolved, ...rest] = candidates;
    const rolePolicy = validationPolicy.roles[roleId];
    const duplicates = rest.filter((candidate) => {
        return resolved.score - candidate.score <= rolePolicy.duplicateThresholdDelta;
    });

    return {
        roleId,
        resolved,
        duplicates
    };
}

function validateRequiredMarkers(filePath, requiredMarkers) {
    const content = fs.readFileSync(filePath, 'utf8');
    return requiredMarkers.filter((marker) => !content.includes(marker));
}

function findLatestDevlog(hostRoot, devlogDirectory) {
    const logsDir = devlogDirectory.absolutePath;
    if (!fs.existsSync(logsDir) || !fs.statSync(logsDir).isDirectory()) {
        return {
            logDirExists: false,
            directory: devlogDirectory,
            allEntries: [],
            latestEntry: null
        };
    }

    const pattern = new RegExp(validationPolicy.roles[FILE_ROLE_IDS.DEVLOG].logFilePattern);
    const entries = fs
        .readdirSync(logsDir, { withFileTypes: true })
        .filter((entry) => entry.isFile() && entry.name.endsWith('.md') && pattern.test(entry.name))
        .map((entry) => {
            const fullPath = path.join(logsDir, entry.name);
            return {
                filePath: fullPath,
                relativePath: normalizePathForMatch(hostRoot, fullPath),
                mtimeMs: fs.statSync(fullPath).mtimeMs
            };
        })
        .sort((a, b) => b.mtimeMs - a.mtimeMs || a.relativePath.localeCompare(b.relativePath));

    return {
        logDirExists: true,
        directory: devlogDirectory,
        allEntries: entries,
        latestEntry: entries[0] || null
    };
}

function inspectRulesDirectory(hostRoot) {
    const sourceDir = path.resolve(__dirname, '..', rulesSyncPolicy.sourceDir);
    const targetDir = path.join(hostRoot, rulesSyncPolicy.targetDir);

    const defaultRuleFiles = fs.existsSync(sourceDir)
        ? fs.readdirSync(sourceDir).filter((name) => name.endsWith('.md')).sort()
        : [];

    const hostRuleFiles =
        fs.existsSync(targetDir) && fs.statSync(targetDir).isDirectory()
            ? fs.readdirSync(targetDir).filter((name) => name.endsWith('.md')).sort()
            : [];

    const missingDefaultRules = defaultRuleFiles.filter((name) => !hostRuleFiles.includes(name));

    return {
        sourceDir,
        targetDir,
        exists: fs.existsSync(targetDir),
        defaultRuleFiles,
        hostRuleFiles,
        missingDefaultRules
    };
}

function buildIssue(severity, code, message, details = {}) {
    return {
        severity,
        code,
        message,
        ...details
    };
}

function summarizeFieldPackages() {
    return Object.fromEntries(
        Object.entries(fieldPackages).map(([key, fields]) => [key, fields.length])
    );
}

function validateGlobalFiles({ hostRoot }) {
    const resolvedHostRoot = path.resolve(process.cwd(), hostRoot);

    if (!fs.existsSync(resolvedHostRoot) || !fs.statSync(resolvedHostRoot).isDirectory()) {
        throw new Error(`Host root is not a directory: ${resolvedHostRoot}`);
    }

    const markdownFiles = walkMarkdownFiles(resolvedHostRoot, validationPolicy.scan.maxDepth);
    const issues = [];

    const authorityByRole = {};
    for (const roleId of [FILE_ROLE_IDS.RULES, FILE_ROLE_IDS.PROFILE, FILE_ROLE_IDS.PLAN]) {
        const candidates = findAuthorityCandidates(resolvedHostRoot, markdownFiles, roleId);
        const authority = resolveAuthority(candidates, roleId);
        authorityByRole[roleId] = authority;

        if (!authority.resolved) {
            issues.push(
                buildIssue(
                    roleId === FILE_ROLE_IDS.PROFILE ? 'error' : 'warning',
                    'missing_authority',
                    `Missing authority file for role: ${roleId}`,
                    { roleId }
                )
            );
            continue;
        }

        if (authority.duplicates.length > 0) {
            issues.push(
                buildIssue(
                    'warning',
                    'duplicate_authority_candidates',
                    `Multiple authority candidates found for role: ${roleId}`,
                    {
                        roleId,
                        resolved: authority.resolved.relativePath,
                        duplicates: authority.duplicates.map((candidate) => candidate.relativePath)
                    }
                )
            );
        }

        const requiredMarkers = validationPolicy.roles[roleId].requiredMarkers || [];
        const missingMarkers = validateRequiredMarkers(authority.resolved.filePath, requiredMarkers);

        if (missingMarkers.length > 0) {
            issues.push(
                buildIssue(
                    'warning',
                    'missing_required_markers',
                    `Required structure markers missing for role: ${roleId}`,
                    {
                        roleId,
                        filePath: authority.resolved.relativePath,
                        missingMarkers
                    }
                )
            );
        }
    }

    const devlogDirectory = resolveDevlogDirectory({ hostRoot: resolvedHostRoot });
    const devlogState = findLatestDevlog(resolvedHostRoot, devlogDirectory);
    if (!devlogState.logDirExists) {
        issues.push(
            buildIssue(
                'warning',
                'missing_logs_directory',
                `Configured devlog directory is missing: ${devlogDirectory.relativePath}`,
                { roleId: FILE_ROLE_IDS.DEVLOG, targetDir: devlogDirectory.relativePath }
            )
        );
    } else if (!devlogState.latestEntry) {
        issues.push(
            buildIssue(
                'warning',
                'missing_devlog_entry',
                `Configured devlog directory has no recognized entry: ${devlogDirectory.relativePath}`,
                { roleId: FILE_ROLE_IDS.DEVLOG, targetDir: devlogDirectory.relativePath }
            )
        );
    }

    const rulesDirectory = inspectRulesDirectory(resolvedHostRoot);
    if (!rulesDirectory.exists) {
        issues.push(
            buildIssue(
                'warning',
                'missing_rules_directory',
                'Host docs/rules directory is missing.',
                { targetDir: normalizePathForMatch(resolvedHostRoot, rulesDirectory.targetDir) }
            )
        );
    } else if (rulesDirectory.missingDefaultRules.length > 0) {
        issues.push(
            buildIssue(
                'info',
                'missing_default_rule_files',
                'Host docs/rules directory is missing some default rule files.',
                { missingFiles: rulesDirectory.missingDefaultRules }
            )
        );
    }

    const summary = {
        errors: issues.filter((issue) => issue.severity === 'error').length,
        warnings: issues.filter((issue) => issue.severity === 'warning').length,
        infos: issues.filter((issue) => issue.severity === 'info').length
    };

    return {
        hostRoot: resolvedHostRoot,
        scannedMarkdownFiles: markdownFiles.length,
        fieldPackageSizes: summarizeFieldPackages(),
        authority: {
            [FILE_ROLE_IDS.RULES]: authorityByRole[FILE_ROLE_IDS.RULES]?.resolved?.relativePath || null,
            [FILE_ROLE_IDS.PROFILE]: authorityByRole[FILE_ROLE_IDS.PROFILE]?.resolved?.relativePath || null,
            [FILE_ROLE_IDS.PLAN]: authorityByRole[FILE_ROLE_IDS.PLAN]?.resolved?.relativePath || null,
            [FILE_ROLE_IDS.DEVLOG]: devlogState.latestEntry?.relativePath || null
        },
        duplicates: {
            [FILE_ROLE_IDS.RULES]:
                authorityByRole[FILE_ROLE_IDS.RULES]?.duplicates?.map((item) => item.relativePath) || [],
            [FILE_ROLE_IDS.PROFILE]:
                authorityByRole[FILE_ROLE_IDS.PROFILE]?.duplicates?.map((item) => item.relativePath) || [],
            [FILE_ROLE_IDS.PLAN]:
                authorityByRole[FILE_ROLE_IDS.PLAN]?.duplicates?.map((item) => item.relativePath) || []
        },
        rulesDirectory: {
            exists: rulesDirectory.exists,
            targetDir: normalizePathForMatch(resolvedHostRoot, rulesDirectory.targetDir),
            hostRuleFiles: rulesDirectory.hostRuleFiles,
            missingDefaultRules: rulesDirectory.missingDefaultRules
        },
        devlogDirectory: {
            path: devlogDirectory.relativePath,
            source: devlogDirectory.source,
            exists: devlogState.logDirExists
        },
        contracts: {
            [FILE_ROLE_IDS.RULES]: fileContracts[FILE_ROLE_IDS.RULES].length,
            [FILE_ROLE_IDS.PROFILE]: fileContracts[FILE_ROLE_IDS.PROFILE].length,
            [FILE_ROLE_IDS.PLAN]: fileContracts[FILE_ROLE_IDS.PLAN].length,
            [FILE_ROLE_IDS.DEVLOG]: fileContracts[FILE_ROLE_IDS.DEVLOG].length
        },
        issues,
        summary
    };
}

function formatTextReport(result) {
    const roleLabels = Object.fromEntries(fileRoles.map((role) => [role.id, role.defaultFileName]));
    const lines = [
        `Host root: ${result.hostRoot}`,
        `Scanned markdown files: ${result.scannedMarkdownFiles}`,
        `Errors: ${result.summary.errors}`,
        `Warnings: ${result.summary.warnings}`,
        `Info: ${result.summary.infos}`,
        '',
        'Authority resolution:',
        `- ${roleLabels[FILE_ROLE_IDS.RULES]}: ${result.authority[FILE_ROLE_IDS.RULES] || 'NOT FOUND'}`,
        `- ${roleLabels[FILE_ROLE_IDS.PROFILE]}: ${result.authority[FILE_ROLE_IDS.PROFILE] || 'NOT FOUND'}`,
        `- ${roleLabels[FILE_ROLE_IDS.PLAN]}: ${result.authority[FILE_ROLE_IDS.PLAN] || 'NOT FOUND'}`,
        `- ${FILE_ROLE_IDS.DEVLOG}: ${result.authority[FILE_ROLE_IDS.DEVLOG] || 'NOT FOUND'}`,
        `- ${FILE_ROLE_IDS.DEVLOG} directory: ${result.devlogDirectory.path} (${result.devlogDirectory.source})`,
        '',
        `Rules directory: ${result.rulesDirectory.targetDir} (${result.rulesDirectory.exists ? 'exists' : 'missing'})`
    ];

    if (result.rulesDirectory.missingDefaultRules.length > 0) {
        lines.push(`Missing default rules: ${result.rulesDirectory.missingDefaultRules.join(', ')}`);
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
    const result = validateGlobalFiles(options);

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

export { validateGlobalFiles, formatTextReport };
