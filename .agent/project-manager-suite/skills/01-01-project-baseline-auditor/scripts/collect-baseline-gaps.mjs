#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import process from 'process';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);

const ignoredDirectories = new Set([
    '.git',
    '.agent',
    '.claude',
    '.codex',
    '.cursor',
    '.agent/project-manager-suite',
    '.playwright-mcp',
    'project-manager-suite',
    'node_modules',
    'dist',
    'build',
    'target',
    'coverage',
    '.next',
    '.nuxt',
    '.vite',
    '.turbo',
    '.cache',
    '.pytest_cache',
    '.mypy_cache',
    '.ruff_cache',
    '__pycache__',
    '.venv',
    'venv'
]);

const ignoredFileExtensions = new Set(['.pyc', '.pyo', '.class', '.map']);

const allowedNextSkills = new Set([
    'brd-writer',
    'page-explainer',
    'foundation-builder',
    'prd-writer'
]);

const artifactOrder = ['PROJECT_PROFILE', 'BRD', 'PAGE_EXPLAINER', 'FOUNDATION', 'PRD'];

function printUsage() {
    console.log('Usage: node collect-baseline-gaps.mjs <host-project-root> [--slug <slug>] [--json] [--dry-run]');
}

function parseArgs(argv) {
    const args = argv.slice(2);
    const options = {
        hostRoot: '',
        slug: '',
        json: false,
        write: true
    };

    for (let index = 0; index < args.length; index += 1) {
        const arg = args[index];
        if (arg === '--json') {
            options.json = true;
            continue;
        }
        if (arg === '--dry-run') {
            options.write = false;
            continue;
        }
        if (arg === '--slug') {
            const slug = args[index + 1];
            if (!slug) {
                throw new Error('Missing value for --slug.');
            }
            options.slug = slug;
            index += 1;
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

function normalizePathForMatch(rootDir, targetPath) {
    return path.relative(rootDir, targetPath).split(path.sep).join('/');
}

function shouldIgnoreDir(relativeDir) {
    const normalizedRelative = relativeDir.split(path.sep).join('/');
    return [...ignoredDirectories].some((ignored) => {
        const normalizedIgnored = ignored.split(path.sep).join('/');
        const pathScopedMatch = normalizedRelative === normalizedIgnored ||
            normalizedRelative.startsWith(`${normalizedIgnored}/`) ||
            normalizedRelative.endsWith(`/${normalizedIgnored}`) ||
            normalizedRelative.includes(`/${normalizedIgnored}/`);

        if (pathScopedMatch) {
            return true;
        }

        if (!normalizedIgnored.includes('/')) {
            return normalizedRelative.split('/').includes(normalizedIgnored);
        }

        return false;
    });
}

function walkFiles(rootDir, maxDepth = 8) {
    const results = [];

    function recurse(currentDir, depth) {
        if (depth > maxDepth || !fs.existsSync(currentDir)) return;

        for (const entry of fs.readdirSync(currentDir, { withFileTypes: true })) {
            const fullPath = path.join(currentDir, entry.name);
            const relativePath = normalizePathForMatch(rootDir, fullPath);

            if (entry.isDirectory()) {
                if (!shouldIgnoreDir(relativePath)) {
                    recurse(fullPath, depth + 1);
                }
                continue;
            }

            if (entry.isFile()) {
                if (ignoredFileExtensions.has(path.extname(entry.name).toLowerCase())) {
                    continue;
                }
                results.push({
                    filePath: fullPath,
                    relativePath
                });
            }
        }
    }

    recurse(rootDir, 0);
    return results.sort((a, b) => a.relativePath.localeCompare(b.relativePath));
}

function readText(filePath) {
    return fs.readFileSync(filePath, 'utf8');
}

function readJson(filePath) {
    return JSON.parse(readText(filePath));
}

function safeReadJson(filePath) {
    try {
        return readJson(filePath);
    } catch {
        return null;
    }
}

function slugify(value) {
    const slug = String(value || '')
        .toLowerCase()
        .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 64);
    return slug || 'existing-project';
}

function findExistingAuditSlug(hostRoot) {
    const baselineDir = path.join(hostRoot, 'docs', 'baseline');
    if (!fs.existsSync(baselineDir)) {
        return '';
    }

    const candidates = fs
        .readdirSync(baselineDir)
        .map((name) => name.match(/^baseline-audit-(.+)\.json$/))
        .filter(Boolean)
        .map((match) => match[1]);

    if (candidates.length === 0) {
        return '';
    }

    return candidates
        .map((slug) => ({
            slug,
            mtimeMs: fs.statSync(path.join(baselineDir, `baseline-audit-${slug}.json`)).mtimeMs
        }))
        .sort((a, b) => b.mtimeMs - a.mtimeMs)[0].slug;
}

function resolveSlug({ explicitSlug, profile, packageInfo, hostRoot }) {
    if (explicitSlug) {
        return { slug: slugify(explicitSlug), source: 'explicit' };
    }

    const profileSlug = profile.fields.project_slug?.value;
    if (profileSlug && !isPlaceholder(profileSlug)) {
        return { slug: slugify(profileSlug), source: 'profile' };
    }

    const existingAuditSlug = findExistingAuditSlug(hostRoot);
    if (existingAuditSlug) {
        return { slug: existingAuditSlug, source: 'existing-audit' };
    }

    return {
        slug: slugify(packageInfo.name || profile.fields.project_name?.value || path.basename(hostRoot)),
        source: 'derived'
    };
}

function stripSourceMarker(value) {
    return String(value || '')
        .replace(/^`|`$/g, '')
        .replace(/`/g, '')
        .replace(/【(?:用户确认|系统推断|主入口回写)】/g, '')
        .trim();
}

function isPlaceholder(value) {
    const normalized = stripSourceMarker(value);
    return !normalized || /^(待填写|待建立|待确认)$/.test(normalized) || /^例如/.test(normalized);
}

function extractProfileField(content, label) {
    if (!content) return null;
    const escapedLabel = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const pattern = new RegExp(`^-\\s+${escapedLabel}：(.+)$`, 'm');
    const match = content.match(pattern);
    if (!match) return null;
    const raw = match[1].trim();
    return {
        raw,
        value: stripSourceMarker(raw),
        userConfirmed: raw.includes('【用户确认】')
    };
}

function existingProfileFields(hostRoot) {
    const profilePath = path.join(hostRoot, 'project-profile.md');
    if (!fs.existsSync(profilePath)) {
        return {
            path: profilePath,
            exists: false,
            content: '',
            fields: {}
        };
    }

    const content = readText(profilePath);
    const labels = {
        project_name: '项目名称',
        project_slug: '项目 slug',
        project_one_liner: '项目一句话目标',
        target_users: '目标使用者',
        main_problem: '主要问题',
        v1_core_goal: '第一版核心目标',
        coverage_scope: '项目覆盖对象',
        page_primary_user: '当前页面主要给谁用',
        page_primary_purpose: '当前页面主要用途',
        page_positioning_tag: '页面定位标签',
        core_feature_1: '核心功能 1',
        core_feature_2: '核心功能 2',
        core_feature_3: '核心功能 3'
    };

    const fields = {};
    for (const [key, label] of Object.entries(labels)) {
        fields[key] = extractProfileField(content, label);
    }

    return {
        path: profilePath,
        exists: true,
        content,
        fields
    };
}

function inferPackageInfo(hostRoot) {
    const packagePath = path.join(hostRoot, 'package.json');
    if (!fs.existsSync(packagePath)) {
        return {
            path: null,
            name: '',
            description: '',
            scripts: []
        };
    }

    const pkg = safeReadJson(packagePath) || {};
    return {
        path: 'package.json',
        name: pkg.name || '',
        description: pkg.description || '',
        scripts: Object.keys(pkg.scripts || {})
    };
}

function inferReadme(files) {
    const candidates = files.filter((file) => /^readme(\.[a-z]+)?$/i.test(path.basename(file.relativePath)));
    return candidates.sort((a, b) => {
        const aDepth = a.relativePath.split('/').length;
        const bDepth = b.relativePath.split('/').length;
        return aDepth - bDepth || a.relativePath.localeCompare(b.relativePath);
    })[0] || null;
}

function inferReadmeSummary(readmeFile) {
    if (!readmeFile) return '';
    const content = readText(readmeFile.filePath);
    return content
        .split('\n')
        .map((line) => line.trim())
        .find((line) => line && !line.startsWith('#') && !line.startsWith('![') && !line.startsWith('[')) || '';
}

function collectCodeEvidence(files) {
    const codeFiles = files.filter((file) => /\.(vue|tsx?|jsx?|java|py|go|rb|php|cs|sql)$/i.test(file.relativePath));

    const pages = codeFiles.filter((file) =>
        /(^|\/)(pages|views|screens)\//i.test(file.relativePath) ||
        /(^|\/)(page|screen|view)\.(vue|tsx|jsx)$/i.test(file.relativePath) ||
        /(?:Page|Screen|View)\.(vue|tsx|jsx)$/i.test(path.basename(file.relativePath))
    );
    const apis = codeFiles.filter((file) =>
        /(^|\/)src\/(api|apis)\//i.test(file.relativePath) ||
        /^(api|apis)\//i.test(file.relativePath) ||
        /(^|\/)(routes|controllers|handlers|endpoints)\//i.test(file.relativePath) ||
        /(?:controller|route|handler|endpoint)\.(vue|tsx?|jsx?|java|py|go|rb|php|cs)$/i.test(path.basename(file.relativePath))
    );
    const models = codeFiles.filter((file) =>
        /(^|\/)(models|model|entities|entity|schemas|schema|migrations|database|db|alembic\/versions)\//i.test(file.relativePath) ||
        /^(models?|entities?|schemas?)\.(vue|tsx?|jsx?|java|py|go|rb|php|cs)$/i.test(path.basename(file.relativePath)) ||
        /\.(sql)$/i.test(file.relativePath)
    );
    const configs = files.filter((file) =>
        /(^|\/)(\.env\.example|\.env\.sample|vite\.config|webpack\.config|tsconfig|jsconfig|application\.ya?ml|config)\b/i.test(
            file.relativePath
        ) ||
        /(^|\/)(config|configs)\//i.test(file.relativePath)
    );

    const apiEndpoints = codeFiles.reduce((count, file) => {
        const content = readText(file.filePath);
        const fastApiDecorators = content.match(/@\w+\.(?:get|post|put|patch|delete|options|head)\s*\(/gi) || [];
        const javaMappings = content.match(/@(?:Get|Post|Put|Patch|Delete|Request)Mapping\s*\(/g) || [];
        return count + fastApiDecorators.length + javaMappings.length;
    }, 0);
    const modelDefinitions = models.reduce((count, file) => {
        const content = readText(file.filePath);
        const pythonOrmClasses = content.match(/^\s*class\s+\w+\s*\([^\n)]*\bBase\b[^\n)]*\)\s*:/gm) || [];
        const javaEntities = content.match(/@Entity\b/g) || [];
        return count + pythonOrmClasses.length + javaEntities.length;
    }, 0);
    const migrationFiles = models.filter((file) =>
        /(^|\/)(migrations|alembic\/versions)\//i.test(file.relativePath) || /\.(sql)$/i.test(file.relativePath)
    );

    return {
        codeFiles,
        pages,
        apis,
        models,
        configs,
        counts: {
            page_files: pages.length,
            api_files: apis.length,
            api_endpoints: apiEndpoints,
            model_files: models.length,
            model_definitions: modelDefinitions,
            migration_files: migrationFiles.length
        }
    };
}

function findDocs(files, pattern, preferredPrefix, extraPrefixes = []) {
    return files
        .filter((file) => {
            if (!/\.md$/i.test(file.relativePath) || !pattern.test(path.basename(file.relativePath))) {
                return false;
            }
            return (
                file.relativePath.startsWith(preferredPrefix) ||
                extraPrefixes.some((prefix) => file.relativePath.startsWith(prefix)) ||
                !file.relativePath.includes('/')
            );
        })
        .sort((a, b) => {
            const aPreferred = preferredPrefix && a.relativePath.startsWith(preferredPrefix) ? 0 : 1;
            const bPreferred = preferredPrefix && b.relativePath.startsWith(preferredPrefix) ? 0 : 1;
            return aPreferred - bPreferred || a.relativePath.localeCompare(b.relativePath);
        });
}

function detectExistingArtifacts(files) {
    const brd = findDocs(files, /^BRD-.+\.md$/i, 'docs/brd/');
    const pageFallbackDirs = ['page-preview/', '可操作页面/'];
    const pageDelivery = findDocs(files, /^page-delivery-.+\.md$/i, 'src/frontend/page-preview/', pageFallbackDirs);
    const explainerFlow = findDocs(files, /^explainer-flow-.+\.md$/i, 'src/frontend/page-preview/', pageFallbackDirs);
    const interaction = findDocs(files, /^explainer-b-interaction-.+\.md$/i, 'src/frontend/page-preview/', pageFallbackDirs);
    const explainerDelivery = findDocs(files, /^explainer-delivery-.+\.md$/i, 'src/frontend/page-preview/', pageFallbackDirs);
    const foundationGlossary = findDocs(files, /^foundation-glossary-.+\.md$/i, 'docs/prd/foundation/');
    const foundationSchema = findDocs(files, /^foundation-schema-.+\.md$/i, 'docs/prd/foundation/');
    const foundationApi = findDocs(files, /^foundation-api-.+\.md$/i, 'docs/prd/foundation/');
    const foundationDelivery = findDocs(files, /^foundation-delivery-.+\.md$/i, 'docs/prd/foundation/');
    const prdFeatureList = findDocs(files, /^prd-feature-list-.+\.md$/i, 'docs/prd/');
    const mainprd = findDocs(files, /^mainprd-.+\.md$/i, 'docs/prd/');
    const subprd = findDocs(files, /^\d{2}-subprd-.+\.md$/i, 'docs/prd/subprd/');

    return {
        brd,
        pageDelivery,
        explainerFlow,
        interaction,
        explainerDelivery,
        foundationGlossary,
        foundationSchema,
        foundationApi,
        foundationDelivery,
        prdFeatureList,
        mainprd,
        subprd
    };
}

function sourceValue(value, source) {
    if (!value || isPlaceholder(value)) {
        return '`待确认`';
    }
    return `\`${source} ${value}\``;
}

function chooseField(existing, inferredValue, inferredSource = '【系统推断】') {
    if (existing?.userConfirmed && !isPlaceholder(existing.raw)) {
        return existing.raw;
    }
    if (!isPlaceholder(inferredValue)) {
        return sourceValue(inferredValue, inferredSource);
    }
    if (existing?.raw && !isPlaceholder(existing.raw)) {
        return existing.raw;
    }
    return '`待确认`';
}

function normalizeComparisonValue(value) {
    return stripSourceMarker(value).replace(/\s+/g, '').toLowerCase();
}

function profileConflict(profile, key, inferredValue, label) {
    const existing = profile.fields[key];
    if (!existing?.userConfirmed || isPlaceholder(existing.raw) || isPlaceholder(inferredValue)) {
        return null;
    }

    const existingValue = normalizeComparisonValue(existing.value);
    const inferred = normalizeComparisonValue(inferredValue);
    if (!existingValue || !inferred || existingValue === inferred) {
        return null;
    }

    return {
        field: key,
        label,
        user_confirmed: existing.value,
        system_inferred: inferredValue,
        question: `${label}画像为“${existing.value}”，代码推断为“${inferredValue}”，后续维护以哪个为准？`
    };
}

function collectProfileConflicts(profile, inferred) {
    return [
        profileConflict(profile, 'project_name', inferred.project_name, '项目名称'),
        profileConflict(profile, 'project_one_liner', inferred.project_one_liner, '项目一句话目标'),
        profileConflict(profile, 'page_primary_purpose', inferred.page_primary_purpose, '当前页面主要用途')
    ].filter(Boolean);
}

function buildProfileDraft({ hostRoot, profile, packageInfo, readmeSummary, evidence, docs, slug, slugSource }) {
    const inferredName = packageInfo.name || profile.fields.project_name?.value || slug || path.basename(hostRoot);
    const inferredOneLiner = packageInfo.description || readmeSummary;
    const pagePurpose = '';
    const pageTag = '';
    const conflicts = collectProfileConflicts(profile, {
        project_name: inferredName,
        project_one_liner: inferredOneLiner,
        page_primary_purpose: pagePurpose
    });
    const existingDocs = [
        ...docs.brd,
        ...docs.pageDelivery,
        ...docs.explainerFlow,
        ...docs.interaction,
        ...docs.explainerDelivery,
        ...docs.foundationGlossary,
        ...docs.foundationSchema,
        ...docs.foundationApi,
        ...docs.foundationDelivery,
        ...docs.prdFeatureList,
        ...docs.mainprd,
        ...docs.subprd
    ].map((file) => file.relativePath);

    const missingStartupFields = [
        ['project_name', '项目名称'],
        ['project_one_liner', '项目一句话目标'],
        ['target_users', '目标使用者'],
        ['main_problem', '主要问题']
    ].filter(([key]) => {
        const existing = profile.fields[key];
        if (existing?.userConfirmed && !isPlaceholder(existing.raw)) return false;
        if (key === 'project_name' && inferredName) return false;
        if (key === 'project_one_liner' && inferredOneLiner) return false;
        return true;
    });

    const highestMissingField = missingStartupFields[0] || null;
    const highestConflict = conflicts[0] || null;
    const largestUncertainty = highestMissingField
        ? `${highestMissingField[1]}待确认`
        : highestConflict
          ? `${highestConflict.label}存在代码推断冲突`
          : '关键维护文件缺口待确认';
    const nextQuestions = highestMissingField
        ? [
              {
                  field: highestMissingField[0],
                  question: `${highestMissingField[1]}是什么？`
              }
          ]
        : highestConflict
          ? [
                {
                    field: highestConflict.field,
                    question: highestConflict.question
                }
            ]
        : [];

    const fields = {
        project_name: chooseField(profile.fields.project_name, inferredName),
        project_slug: chooseField(profile.fields.project_slug, slug, slugSource === 'explicit' ? '【主入口回写】' : '【系统推断】'),
        project_one_liner: chooseField(profile.fields.project_one_liner, inferredOneLiner),
        target_users: chooseField(profile.fields.target_users, ''),
        main_problem: chooseField(profile.fields.main_problem, ''),
        v1_core_goal: chooseField(profile.fields.v1_core_goal, '补齐既有项目维护知识底座'),
        coverage_scope: chooseField(profile.fields.coverage_scope, '既有代码项目'),
        page_primary_user: chooseField(profile.fields.page_primary_user, ''),
        page_primary_purpose: chooseField(profile.fields.page_primary_purpose, pagePurpose),
        page_positioning_tag: chooseField(profile.fields.page_positioning_tag, pageTag, '【主入口回写】'),
        core_feature_1: chooseField(profile.fields.core_feature_1, '从代码结构继续反推'),
        core_feature_2: chooseField(profile.fields.core_feature_2, ''),
        core_feature_3: chooseField(profile.fields.core_feature_3, '')
    };

    const markdown = `# 项目画像

> 本文件由 project-baseline-auditor 基于既有代码受控生成或更新。用户确认字段优先，代码推断字段只作为后续补档线索。

## 1. 基本信息

- 项目名称：${fields.project_name}
- 项目 slug：${fields.project_slug}
- 项目一句话目标：${fields.project_one_liner}
- 当前阶段：\`【主入口回写】 S0.5\`
- 协作模式：\`【系统推断】 业务单人 + AI执行\`

## 2. 身份识别

- 身份识别口径：\`【系统推断】 待按宿主项目确认\`

## 3. 业务目标

- 目标使用者：${fields.target_users}
- 主要问题：${fields.main_problem}
- 第一版核心目标：${fields.v1_core_goal}

## 4. 页面与任务定位

- 项目覆盖对象：${fields.coverage_scope}
- 当前页面主要给谁用：${fields.page_primary_user}
- 当前页面主要用途：${fields.page_primary_purpose}
- 页面定位标签：${fields.page_positioning_tag}

## 5. 第一版范围

- 核心功能 1：${fields.core_feature_1}
- 核心功能 2：${fields.core_feature_2}
- 核心功能 3：${fields.core_feature_3}

## 6. 当前资产

- 已有文档：\`【系统推断】 ${existingDocs.length > 0 ? existingDocs.join('、') : '未发现 BRD / 页面说明 / foundation / PRD 权威文件'}\`
- 已有原型 / 截图：\`【系统推断】 未扫描到独立原型或截图\`
- 已有系统 / Excel / 流程：\`【系统推断】 既有代码文件 ${evidence.codeFiles.length} 个\`
- 其他可用材料：\`【系统推断】 页面文件 ${evidence.counts.page_files} 个，API 文件 ${evidence.counts.api_files} 个，API 端点 ${evidence.counts.api_endpoints} 个，模型定义 ${evidence.counts.model_definitions} 个，迁移 ${evidence.counts.migration_files} 个，配置线索 ${evidence.configs.length} 个\`

## 7. 项目入口与识别信息

- 规则入口文件：\`【系统推断】 project-rules.md 或 docs/rules/\`
- 计划入口文件：\`【系统推断】 docs/plans/execution-plan.md\`
- 最近状态入口：\`【系统推断】 logs/\`
- PRD 总入口：\`【系统推断】 docs/prd/mainprd-<slug>.md\`
- 身份识别方式：\`【系统推断】 待按宿主项目确认\`
- 任务类型规则入口：\`【系统推断】 docs/rules/\`
- 最近状态定位口径：\`【系统推断】 最近日志文件\`

## 8. 当前判断

- 当前最适合进入的阶段：\`【主入口回写】 S0.5\`
- 当前轮应输出的交付物：\`【主入口回写】 既有项目关键文件诊断清单\`
- 当前最大不确定项：\`【主入口回写】 ${largestUncertainty}\`
- 当前任务执行主体：\`【主入口回写】 project-baseline-auditor\`

## 9. 待确认

- ${nextQuestions[0]?.question || '无（启动最小字段包已具备，后续由对应 skill 继续确认正式文档内容）'}
`;

    return {
        markdown,
        fields,
        nextQuestions,
        conflicts
    };
}

function parseProfileFieldLabel(line) {
    const match = line.match(/^-\s+([^：]+)：/);
    return match ? match[1].trim() : null;
}

function isProtectedProfileLine(line) {
    return /【(?:用户确认|主入口回写)】/.test(line);
}

function insertFieldLinesIntoSection(lines, sectionHeading, fieldLines) {
    const headingIndex = lines.findIndex((line) => line.trim() === sectionHeading);
    if (headingIndex === -1) {
        return false;
    }

    let insertAt = headingIndex + 1;
    for (let index = headingIndex + 1; index < lines.length; index += 1) {
        if (/^##\s+/.test(lines[index])) {
            break;
        }
        if (lines[index].trim()) {
            insertAt = index + 1;
        }
    }

    lines.splice(insertAt, 0, ...fieldLines);
    return true;
}

function mergeProfileMarkdown(existingContent, draftMarkdown) {
    const draftLines = draftMarkdown.replace(/\n$/, '').split('\n');
    const existingLines = existingContent.replace(/\n$/, '').split('\n');

    const draftFieldLines = new Map();
    const draftSectionOfField = new Map();
    let currentDraftSection = '';
    for (const line of draftLines) {
        if (/^##\s+/.test(line)) {
            currentDraftSection = line.trim();
        }
        const label = parseProfileFieldLabel(line);
        if (label && !draftFieldLines.has(label)) {
            draftFieldLines.set(label, line);
            draftSectionOfField.set(label, currentDraftSection);
        }
    }

    const existingLabels = new Set();
    for (const line of existingLines) {
        const label = parseProfileFieldLabel(line);
        if (label) {
            existingLabels.add(label);
        }
    }

    const mergedLines = existingLines.map((line) => {
        const label = parseProfileFieldLabel(line);
        if (!label || isProtectedProfileLine(line)) {
            return line;
        }
        return draftFieldLines.get(label) || line;
    });

    const missingBySection = new Map();
    for (const [label, line] of draftFieldLines) {
        if (existingLabels.has(label)) {
            continue;
        }
        const section = draftSectionOfField.get(label) || '';
        if (!missingBySection.has(section)) {
            missingBySection.set(section, []);
        }
        missingBySection.get(section).push(line);
    }

    for (const [section, fieldLines] of missingBySection) {
        if (section && insertFieldLinesIntoSection(mergedLines, section, fieldLines)) {
            missingBySection.delete(section);
        }
    }

    for (const [section, fieldLines] of missingBySection) {
        mergedLines.push('');
        if (section) {
            mergedLines.push(section, '');
        }
        mergedLines.push(...fieldLines);
    }

    return `${mergedLines.join('\n')}\n`;
}

function artifactStatus(hasArtifact, evidencePaths) {
    return {
        status: hasArtifact ? 'present' : 'missing',
        evidence_paths: evidencePaths
    };
}

function buildArtifacts({ profileExistsAfterWrite, docs, evidence }) {
    const brdPresent = docs.brd.length > 0;
    const pagePresent = docs.explainerFlow.length > 0 && docs.interaction.length > 0 && docs.explainerDelivery.length > 0;
    const foundationPresent =
        docs.foundationGlossary.length > 0 &&
        docs.foundationSchema.length > 0 &&
        docs.foundationApi.length > 0 &&
        docs.foundationDelivery.length > 0;
    const prdPresent = docs.prdFeatureList.length > 0 && docs.mainprd.length > 0 && docs.subprd.length > 0;

    const artifacts = [
        {
            type: 'PROJECT_PROFILE',
            ...artifactStatus(profileExistsAfterWrite, profileExistsAfterWrite ? ['project-profile.md'] : []),
            expected_location: 'project-profile.md',
            recommended_skill: profileExistsAfterWrite ? null : 'project-baseline-auditor',
            reason: profileExistsAfterWrite ? '项目画像已存在或已生成草稿' : '缺少项目身份与维护语境入口'
        },
        {
            type: 'BRD',
            ...artifactStatus(brdPresent, docs.brd.map((file) => file.relativePath)),
            expected_location: 'docs/brd/',
            recommended_skill: brdPresent ? null : 'brd-writer',
            reason: brdPresent ? '已发现 BRD 文件' : '缺少业务背景、角色、核心场景的权威说明'
        },
        {
            type: 'PAGE_EXPLAINER',
            ...artifactStatus(pagePresent, [
                ...docs.explainerFlow,
                ...docs.interaction,
                ...docs.explainerDelivery
            ].map((file) => file.relativePath)),
            expected_location: 'src/frontend/page-preview/',
            recommended_skill: pagePresent ? null : 'page-explainer',
            reason: pagePresent
                ? '已发现页面交互说明文件'
                : `缺少页面流程与交互语义说明；代码中发现页面文件线索 ${evidence.counts.page_files} 个`
        },
        {
            type: 'FOUNDATION',
            ...artifactStatus(foundationPresent, [
                ...docs.foundationGlossary,
                ...docs.foundationSchema,
                ...docs.foundationApi,
                ...docs.foundationDelivery
            ].map((file) => file.relativePath)),
            expected_location: 'docs/prd/foundation/',
            recommended_skill: foundationPresent ? null : 'foundation-builder',
            reason: foundationPresent
                ? '已发现 foundation 文件'
                : `缺少术语表、Schema、API 与交付清单；代码中发现 API 端点线索 ${evidence.counts.api_endpoints} 个、模型定义 ${evidence.counts.model_definitions} 个、迁移 ${evidence.counts.migration_files} 个`
        },
        {
            type: 'PRD',
            ...artifactStatus(prdPresent, [
                ...docs.prdFeatureList,
                ...docs.mainprd,
                ...docs.subprd
            ].map((file) => file.relativePath)),
            expected_location: 'docs/prd/',
            recommended_skill: prdPresent ? null : 'prd-writer',
            reason: prdPresent ? '已发现 PRD 文件' : '缺少功能列表、mainprd 与 subprd'
        }
    ];

    return artifacts.sort((a, b) => artifactOrder.indexOf(a.type) - artifactOrder.indexOf(b.type));
}

function chooseRecommendedSkill(profileDraft, artifacts) {
    if (profileDraft.nextQuestions.length > 0) {
        return 'ai-project-manager';
    }

    const missing = artifacts.find((artifact) => {
        return artifact.status === 'missing' && allowedNextSkills.has(artifact.recommended_skill);
    });

    return missing?.recommended_skill || null;
}

function buildAuditMarkdown(result) {
    const rows = result.artifacts
        .map((artifact) => {
            return `| ${artifact.type} | ${artifact.status} | ${artifact.expected_location} | ${artifact.recommended_skill || '无'} | ${artifact.reason} |`;
        })
        .join('\n');

    return `# 既有项目关键文件诊断清单

- 模式：${result.mode}
- 范围：${result.scope}
- slug：${result.slug}
- 推荐下一步：${result.summary.recommended_next_skill || '无'}

## 1. 单焦点待确认

- ${result.profile.next_questions[0]?.question || '无'}

## 2. 关键文件缺口

| 类型 | 状态 | 期望位置 | 推荐 skill | 原因 |
|---|---|---|---|---|
${rows}

## 3. 代码证据摘要

- 页面线索：${result.evidence.pages.slice(0, 10).join('、') || '无'}
- 接口线索：${result.evidence.apis.slice(0, 10).join('、') || '无'}
- 数据模型线索：${result.evidence.models.slice(0, 10).join('、') || '无'}
- 配置线索：${result.evidence.configs.slice(0, 10).join('、') || '无'}

## 4. 边界

- 本清单不诊断测试用例。
- 本清单不诊断待开发任务。
- 本清单不推荐 delivery-planner 或 test-case 系列 skill。
`;
}

function ensureDir(dirPath) {
    fs.mkdirSync(dirPath, { recursive: true });
}

function collectBaselineGaps({ hostRoot, slug: explicitSlug = '', write = true }) {
    const resolvedHostRoot = path.resolve(hostRoot);
    const files = walkFiles(resolvedHostRoot);
    const packageInfo = inferPackageInfo(resolvedHostRoot);
    const readme = inferReadme(files);
    const readmeSummary = inferReadmeSummary(readme);
    const evidence = collectCodeEvidence(files);
    const docs = detectExistingArtifacts(files);
    const profile = existingProfileFields(resolvedHostRoot);
    const { slug, source: slugSource } = resolveSlug({
        explicitSlug,
        profile,
        packageInfo,
        hostRoot: resolvedHostRoot
    });
    const profileDraft = buildProfileDraft({
        hostRoot: resolvedHostRoot,
        profile,
        packageInfo,
        readmeSummary,
        evidence,
        docs,
        slug,
        slugSource
    });

    if (write) {
        const profileMarkdown = profile.exists
            ? mergeProfileMarkdown(profile.content, profileDraft.markdown)
            : profileDraft.markdown;
        fs.writeFileSync(profile.path, profileMarkdown, 'utf8');
    }

    const artifacts = buildArtifacts({
        profileExistsAfterWrite: write || profile.exists,
        docs,
        evidence
    });
    const recommendedSkill = chooseRecommendedSkill(profileDraft, artifacts);
    const result = {
        mode: 'existing-project-baseline',
        scope: 'maintenance-docs-only',
        slug,
        hostRoot: '.',
        summary: {
            status: artifacts.some((artifact) => artifact.status === 'missing')
                ? 'missing_required_artifacts'
                : 'ready',
            recommended_next_skill: recommendedSkill
        },
        profile: {
            path: 'project-profile.md',
            next_questions: profileDraft.nextQuestions,
            conflicts: profileDraft.conflicts
        },
        artifacts,
        evidence: {
            package: packageInfo.path,
            readme: readme?.relativePath || null,
            pages: evidence.pages.map((file) => file.relativePath),
            apis: evidence.apis.map((file) => file.relativePath),
            models: evidence.models.map((file) => file.relativePath),
            configs: evidence.configs.map((file) => file.relativePath),
            counts: evidence.counts
        }
    };

    if (write) {
        const outputDir = path.join(resolvedHostRoot, 'docs', 'baseline');
        ensureDir(outputDir);
        fs.writeFileSync(path.join(outputDir, `baseline-audit-${slug}.json`), JSON.stringify(result, null, 2), 'utf8');
        fs.writeFileSync(path.join(outputDir, `baseline-audit-${slug}.md`), buildAuditMarkdown(result), 'utf8');
    }

    return result;
}

function main() {
    const options = parseArgs(process.argv);
    const result = collectBaselineGaps(options);

    if (options.json) {
        console.log(JSON.stringify(result, null, 2));
        return;
    }

    console.log(buildAuditMarkdown(result));
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

export { collectBaselineGaps };
