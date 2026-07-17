#!/usr/bin/env node

/**
 * collect-upstream-context.mjs
 *
 * Traceability:
 *   Rule sources:
 *     - skills/05-01-delivery-planner/SKILL.md (Step 0.5)
 *     - skills/05-01-delivery-planner/references/source-loading-order.md (Section 十)
 *   Pipeline naming conventions:
 *     - PIPELINE.md (prd-writer / foundation-builder product naming)
 *
 * Location:
 *   skills/05-01-delivery-planner/scripts/collect-upstream-context.mjs
 *   （delivery-planner 专属前置脚本，不属于全局 tools/）
 *
 * Purpose:
 *   Scan the host project's docs/prd/ directory, docs/prd/foundation/
 *   and src/frontend/page-preview/
 *   and discover upstream PRD + foundation + page explainer documents that
 *   delivery-planner must ingest before drafting a development plan.
 *
 *   Supports two modes:
 *     - pipeline mode: precise matching based on PIPELINE.md naming conventions
 *     - fallback mode: keyword-based fuzzy classification for non-pipeline projects
 *
 *   Outputs a structured JSON blob with:
 *     - mainprd      – the mainprd-<slug>.md file (highest priority)
 *     - prdFeatureList – prd-feature-list-<slug>.md
 *     - subprd       – numbered files under docs/prd/subprd/
 *     - foundations  – foundation-{glossary,schema,api,delivery}-<slug>.md
 *     - explainers   – explainer-{flow,*-interaction,*-gap,delivery}-<slug>.md
 *     - missingExpected – files that SHOULD exist per PIPELINE.md but don't
 *     - warnings     – soft issues (naming irregularities, large files, etc.)
 *
 * Usage:
 *   node <suite-path>/skills/05-01-delivery-planner/scripts/collect-upstream-context.mjs <hostRoot> [--docs-dir <rel-path>] [--json] [--verbose]
 *
 * Exit codes:
 *   0 – success (even if missingExpected is non-empty; that's a warning, not an error)
 *   1 – fatal error (hostRoot missing, docs dir unreadable, etc.)
 */

import fs from 'fs';
import path from 'path';
import process from 'process';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);

// ─── Constants ───────────────────────────────────────────────────────────────

/** File size threshold (bytes) above which we add a warning. */
const LARGE_FILE_THRESHOLD = 40_000;
const PAGE_PREVIEW_DIR = path.join('src', 'frontend', 'page-preview');
const FOUNDATION_SUBDIR = 'foundation';
const SUBPRD_SUBDIR = 'subprd';

/**
 * Precise patterns – compiled from PIPELINE.md naming conventions.
 * Used in "pipeline" mode (the default happy path).
 */
const PATTERNS = {
    mainprd:            /^mainprd-(?<slug>[a-z0-9-]+)\.md$/,
    prdFeatureList:     /^prd-feature-list-(?<slug>[a-z0-9-]+)\.md$/,
    subprd:             /^(?<order>\d{2})-subprd-(?<block>[^/.]+)\.md$/u,
    foundationGlossary: /^foundation-glossary-(?<slug>[a-z0-9-]+)\.md$/,
    foundationSchema:   /^foundation-schema-(?<slug>[a-z0-9-]+)(?:-part\d+)?\.md$/,
    foundationApi:      /^foundation-api-(?<slug>[a-z0-9-]+)(?:-part\d+)?\.md$/,
    foundationDelivery: /^foundation-delivery-(?<slug>[a-z0-9-]+)\.md$/,
    explainerFlow:       /^explainer-flow-(?<slug>[a-z0-9-]+)\.md$/,
    explainerInteraction:/^explainer-(?<side>[a-z]+)-interaction-(?<slug>[a-z0-9-]+)\.md$/,
    explainerGap:        /^explainer-(?<side>[a-z]+)-gap-(?<slug>[a-z0-9-]+)\.md$/,
    explainerDelivery:   /^explainer-delivery-(?<slug>[a-z0-9-]+)\.md$/,
};

/**
 * Fallback keyword mapping – used when no file matches PIPELINE naming.
 * Covers both Chinese and English terms for maximum compatibility.
 */
const FALLBACK_KEYWORDS = {
    prd: {
        filePatterns: [/prd/i, /需求/i, /requirement/i, /feature/i],
        titlePatterns: [/产品需求/i, /PRD/i, /需求文档/i, /功能/i, /Feature/i, /Requirement/i],
    },
    foundation: {
        filePatterns: [/schema/i, /数据库/i, /database/i, /api/i, /接口/i, /glossary/i, /术语/i, /foundation/i],
        titlePatterns: [/数据库/i, /Schema/i, /API/i, /接口设计/i, /术语表/i, /Glossary/i, /数据模型/i],
    },
    explainer: {
        filePatterns: [/flow/i, /流程/i, /interaction/i, /交互/i, /gap/i, /差异/i, /delivery/i, /交付/i, /explainer/i],
        titlePatterns: [/用户流程/i, /交互/i, /差异/i, /交付/i, /User Flow/i, /Interaction/i, /Gap/i, /Delivery/i],
    },
};

// ─── Arg parsing ─────────────────────────────────────────────────────────────

function printUsage() {
    console.log(
        'Usage: node <suite-path>/skills/05-01-delivery-planner/scripts/collect-upstream-context.mjs <hostRoot> [--docs-dir <rel-path>] [--json] [--verbose]'
    );
    console.log('');
    console.log('Options:');
    console.log('  <hostRoot>          Absolute or relative path to the host project root.');
    console.log('  --docs-dir <path>   Relative path from hostRoot to the docs directory. Default: docs/prd');
    console.log('  --json              Output JSON instead of human-readable text.');
    console.log('  --verbose           Include per-file detail in text output.');
}

function parseArgs(argv) {
    const args = argv.slice(2);
    const options = {
        hostRoot: '',
        docsDir: 'docs/prd',
        json: false,
        verbose: false,
    };

    for (let i = 0; i < args.length; i++) {
        const arg = args[i];

        if (arg === '--json') { options.json = true; continue; }
        if (arg === '--verbose') { options.verbose = true; continue; }

        if (arg === '--docs-dir') {
            const next = args[i + 1];
            if (!next) throw new Error('Missing value for --docs-dir');
            options.docsDir = next;
            i++;
            continue;
        }

        if (!options.hostRoot) { options.hostRoot = arg; continue; }

        throw new Error(`Unknown argument: ${arg}`);
    }

    if (!options.hostRoot) throw new Error('Missing <hostRoot> argument.');
    return options;
}

// ─── File system helpers ─────────────────────────────────────────────────────

function readDocsDir(docsPath) {
    if (!fs.existsSync(docsPath)) return [];
    return fs.readdirSync(docsPath).filter((name) => name.endsWith('.md'));
}

/**
 * 拆分产物（PIPELINE.md「产物拆分约定」）：主文件 `<name>.md` 旁存在同名子目录 `<name>/`，
 * 权威内容在子目录下的 *.md。枚举这些子文件，使下游读取清单完整。
 * 与 coding-standards/verify-task-context.mjs 同口径：拆分子文件按 <docsDir>/<name>/<sub>.md 定位。
 */
function enumerateSplitSubfiles(docsPath, indexFilename) {
    const subdir = indexFilename.replace(/\.md$/, '');
    const subdirPath = path.join(docsPath, subdir);
    try {
        if (!fs.statSync(subdirPath).isDirectory()) return [];
    } catch {
        return []; // 无同名子目录 → 单文件模式
    }
    return fs.readdirSync(subdirPath)
        .filter((name) => name.endsWith('.md'))
        .map((name) => {
            const abs = path.join(subdirPath, name);
            let stat;
            try {
                stat = fs.statSync(abs);
            } catch {
                return null; // 损坏的符号链接等无法 stat 的条目 → 跳过，不让整次发现崩溃
            }
            if (!stat.isFile()) return null; // 名字像 *.md 的目录/符号链接不是权威子文件
            return {
                filename: path.join(subdir, name),
                path: abs,
                sizeBytes: stat.size,
                isLarge: stat.size > LARGE_FILE_THRESHOLD,
            };
        })
        .filter(Boolean);
}

function mergePagePreviewExplainers(classified, pagePreviewClassified) {
    if (!classified.explainerFlow && pagePreviewClassified.explainerFlow) {
        classified.explainerFlow = pagePreviewClassified.explainerFlow;
    }
    if (!classified.explainerDelivery && pagePreviewClassified.explainerDelivery) {
        classified.explainerDelivery = pagePreviewClassified.explainerDelivery;
    }

    classified.explainerInteraction.push(...pagePreviewClassified.explainerInteraction);
    classified.explainerGap.push(...pagePreviewClassified.explainerGap);

    return classified;
}

function mergeFoundationArtifacts(classified, foundationClassified) {
    if (!classified.foundationGlossary && foundationClassified.foundationGlossary) {
        classified.foundationGlossary = foundationClassified.foundationGlossary;
    }
    if (!classified.foundationDelivery && foundationClassified.foundationDelivery) {
        classified.foundationDelivery = foundationClassified.foundationDelivery;
    }

    classified.foundationSchema.push(...foundationClassified.foundationSchema);
    classified.foundationApi.push(...foundationClassified.foundationApi);

    return classified;
}

function mergeSubprdArtifacts(classified, subprdClassified) {
    classified.subprd.push(...subprdClassified.subprd);
    classified.subprd.sort((a, b) => a.order - b.order || a.filename.localeCompare(b.filename));

    return classified;
}

function fileMeta(docsPath, filename) {
    const abs = path.join(docsPath, filename);
    const stat = fs.statSync(abs);
    return {
        filename,
        path: abs,
        sizeBytes: stat.size,
        isLarge: stat.size > LARGE_FILE_THRESHOLD,
        modifiedAt: stat.mtime.toISOString(),
    };
}

/** Extract the H1 title from a markdown file (first line starting with `# `). */
function extractTitle(filePath) {
    try {
        const content = fs.readFileSync(filePath, 'utf8');
        const match = content.match(/^#\s+(.+)$/m);
        return match ? match[1].trim() : null;
    } catch {
        return null;
    }
}

/**
 * Extract upstream reference table from mainprd-<slug>.md.
 * Looks for markdown tables that mention filenames matching our patterns.
 */
function extractPrdMainRefs(filePath) {
    try {
        const content = fs.readFileSync(filePath, 'utf8');
        const refs = [];
        const cellRe = /`([a-z][a-z0-9-]*\.md)`/g;
        let m;
        while ((m = cellRe.exec(content)) !== null) {
            refs.push(m[1]);
        }
        return [...new Set(refs)];
    } catch {
        return [];
    }
}

// ─── Pipeline mode: precise classification ────────────────────────────────────

function classifyFiles(files, docsPath, options = {}) {
    const {
        includePrd = true,
        includeSubprd = true,
        includeFoundation = true,
        includeExplainer = true,
    } = options;
    const result = {
        mainprd: null,
        prdFeatureList: null,
        subprd: [],
        foundationGlossary: null,
        foundationSchema: [],
        foundationApi: [],
        foundationDelivery: null,
        explainerFlow: null,
        explainerInteraction: [],
        explainerGap: [],
        explainerDelivery: null,
        unrecognized: [],
    };

    for (const filename of files) {
        const meta = fileMeta(docsPath, filename);

        if (includePrd && PATTERNS.mainprd.test(filename)) {
            const slug = filename.match(PATTERNS.mainprd).groups.slug;
            result.mainprd = { ...meta, slug, title: extractTitle(meta.path), upstreamRefs: [] };
            continue;
        }

        if (includePrd && PATTERNS.prdFeatureList.test(filename)) {
            const slug = filename.match(PATTERNS.prdFeatureList).groups.slug;
            result.prdFeatureList = { ...meta, slug, title: extractTitle(meta.path) };
            continue;
        }

        if (includeSubprd && PATTERNS.subprd.test(filename)) {
            const m = filename.match(PATTERNS.subprd);
            result.subprd.push({
                ...meta,
                order: Number(m.groups.order),
                block: m.groups.block,
                title: extractTitle(meta.path),
            });
            continue;
        }

        if (includeFoundation && PATTERNS.foundationGlossary.test(filename)) {
            const slug = filename.match(PATTERNS.foundationGlossary).groups.slug;
            result.foundationGlossary = { ...meta, slug, title: extractTitle(meta.path) };
            continue;
        }

        if (includeFoundation && PATTERNS.foundationSchema.test(filename)) {
            const slug = filename.match(PATTERNS.foundationSchema).groups.slug;
            result.foundationSchema.push({ ...meta, slug, title: extractTitle(meta.path), subfiles: enumerateSplitSubfiles(docsPath, filename) });
            continue;
        }

        if (includeFoundation && PATTERNS.foundationApi.test(filename)) {
            const slug = filename.match(PATTERNS.foundationApi).groups.slug;
            result.foundationApi.push({ ...meta, slug, title: extractTitle(meta.path), subfiles: enumerateSplitSubfiles(docsPath, filename) });
            continue;
        }

        if (includeFoundation && PATTERNS.foundationDelivery.test(filename)) {
            const slug = filename.match(PATTERNS.foundationDelivery).groups.slug;
            result.foundationDelivery = { ...meta, slug, title: extractTitle(meta.path) };
            continue;
        }

        if (includeExplainer && PATTERNS.explainerFlow.test(filename)) {
            const slug = filename.match(PATTERNS.explainerFlow).groups.slug;
            result.explainerFlow = { ...meta, slug, title: extractTitle(meta.path) };
            continue;
        }

        if (includeExplainer && PATTERNS.explainerInteraction.test(filename)) {
            const m = filename.match(PATTERNS.explainerInteraction);
            result.explainerInteraction.push({ ...meta, slug: m.groups.slug, side: m.groups.side, title: extractTitle(meta.path) });
            continue;
        }

        if (includeExplainer && PATTERNS.explainerGap.test(filename)) {
            const m = filename.match(PATTERNS.explainerGap);
            result.explainerGap.push({ ...meta, slug: m.groups.slug, side: m.groups.side, title: extractTitle(meta.path) });
            continue;
        }

        if (includeExplainer && PATTERNS.explainerDelivery.test(filename)) {
            const slug = filename.match(PATTERNS.explainerDelivery).groups.slug;
            result.explainerDelivery = { ...meta, slug, title: extractTitle(meta.path) };
            continue;
        }

        result.unrecognized.push(filename);
    }

    if (result.mainprd) {
        result.mainprd.upstreamRefs = extractPrdMainRefs(result.mainprd.path);
    }

    return result;
}

/**
 * Check whether pipeline mode found at least one PIPELINE-named artifact.
 * Hits in the foundation/ and subprd/ subdirectories also count: a host that
 * only has foundation docs must stay in pipeline mode so that detectMissing
 * can report the missing mainprd/subprd instead of silently falling back.
 * If yes → pipeline mode is valid; if no → should fallback.
 */
function hasPipelineHits(classified) {
    return !!(
        classified.mainprd ||
        classified.prdFeatureList ||
        classified.subprd.length > 0 ||
        classified.foundationGlossary ||
        classified.foundationSchema.length > 0 ||
        classified.foundationApi.length > 0 ||
        classified.foundationDelivery
    );
}

// ─── Fallback mode: keyword-based fuzzy classification ────────────────────────

/**
 * When no file matches PIPELINE naming conventions, classify docs by
 * matching filenames and H1 titles against FALLBACK_KEYWORDS.
 *
 * Returns { prd: [...], foundation: [...], explainer: [...], other: [...] }
 */
function fallbackClassify(files, docsPath) {
    const buckets = {
        prd: [],
        foundation: [],
        explainer: [],
        other: [],
    };

    for (const filename of files) {
        const meta = fileMeta(docsPath, filename);
        const title = extractTitle(meta.path) || '';
        let matched = false;

        for (const [category, keywords] of Object.entries(FALLBACK_KEYWORDS)) {
            const fileMatch = keywords.filePatterns.some((re) => re.test(filename));
            const titleMatch = keywords.titlePatterns.some((re) => re.test(title));

            if (fileMatch || titleMatch) {
                buckets[category].push({
                    path: meta.path,
                    filename: meta.filename,
                    title,
                    sizeBytes: meta.sizeBytes,
                    isLarge: meta.isLarge,
                    matchedBy: fileMatch ? 'filename' : 'title',
                });
                matched = true;
                break; // first match wins – avoid double-bucketing
            }
        }

        if (!matched) {
            buckets.other.push({
                path: meta.path,
                filename: meta.filename,
                title,
                sizeBytes: meta.sizeBytes,
                isLarge: meta.isLarge,
            });
        }
    }

    return buckets;
}

// ─── Missing-file detection (pipeline mode only) ─────────────────────────────

function detectMissing(classified) {
    const missing = [];

    if (!classified.mainprd) {
        missing.push({
            file: 'mainprd-<slug>.md',
            reason: 'mainprd 是 delivery-planner 的最高优先级入口，缺失时无法建立需求地图',
            severity: 'required',
        });
    }

    if (classified.subprd.length === 0) {
        missing.push({
            file: 'docs/prd/subprd/0X-subprd-<block>.md',
            reason: '至少需要一份 subprd，否则无法进行字段级任务拆解',
            severity: 'required',
        });
    }

    if (classified.foundationSchema.length === 0) {
        missing.push({
            file: 'docs/prd/foundation/foundation-schema-<slug>.md',
            reason: 'Schema 是数据库类任务完成标准的依据，缺失将导致字段口径无法核查',
            severity: 'required',
        });
    }

    if (classified.foundationApi.length === 0) {
        missing.push({
            file: 'docs/prd/foundation/foundation-api-<slug>.md',
            reason: 'API 设计文档是接口任务核心文件的来源，缺失将导致核心文件列举不实',
            severity: 'required',
        });
    }

    if (!classified.prdFeatureList) {
        missing.push({
            file: 'prd-feature-list-<slug>.md',
            reason: '功能列表提供页面全景与区块索引，缺失会降低任务拆解的完整性',
            severity: 'expected',
        });
    }

    if (!classified.foundationGlossary) {
        missing.push({
            file: 'docs/prd/foundation/foundation-glossary-<slug>.md',
            reason: '术语表提供统一命名口径，缺失时风险较低但建议补充',
            severity: 'expected',
        });
    }

    if (!classified.foundationDelivery) {
        missing.push({
            file: 'docs/prd/foundation/foundation-delivery-<slug>.md',
            reason: '交付清单包含产物索引，缺失时可从 mainprd 回推',
            severity: 'expected',
        });
    }

    return missing;
}

// ─── Warnings ─────────────────────────────────────────────────────────────────

function collectWarnings(classified) {
    const warnings = [];

    const largeFiles = [
        classified.mainprd,
        classified.prdFeatureList,
        classified.foundationGlossary,
        classified.foundationDelivery,
        classified.explainerFlow,
        classified.explainerDelivery,
        ...classified.foundationSchema,
        ...classified.foundationApi,
        ...classified.subprd,
        ...classified.explainerInteraction,
        ...classified.explainerGap,
    ]
        .filter(Boolean)
        .filter((f) => f.isLarge)
        .map((f) => f.filename);

    if (largeFiles.length > 0) {
        warnings.push({
            code: 'large_files_detected',
            message: '以下文件超过 40KB，请按章节定位读取，不要整包拉入上下文',
            files: largeFiles,
        });
    }

    if (classified.unrecognized.length > 0) {
        warnings.push({
            code: 'unrecognized_docs',
            message: '以下 .md 文件不符合 PIPELINE.md 命名约定，无法自动分类，请手动确认是否需要纳入读取范围',
            files: classified.unrecognized,
        });
    }

    const splitSubfiles = [
        ...classified.foundationSchema,
        ...classified.foundationApi,
    ]
        .flatMap((f) => f.subfiles || [])
        .map((s) => s.filename);

    if (splitSubfiles.length > 0) {
        warnings.push({
            code: 'split_subfiles_detected',
            message: '检测到拆分产物同名子目录：主文件仅为索引，下游必须读入以下全部子文件作为权威来源（PIPELINE.md 产物拆分约定）',
            files: splitSubfiles,
        });
    }

    return warnings;
}

function collectFallbackWarnings(buckets) {
    const warnings = [];

    warnings.push({
        code: 'fallback_mode_active',
        message: '未检测到 PIPELINE.md 命名约定的文件，已按关键词模糊分类。分类结果仅供参考，AI 需要自行打开文件头部确认文件类型后再决定读取深度。',
    });

    const allFiles = [...buckets.prd, ...buckets.foundation, ...buckets.explainer, ...buckets.other];
    const largeFiles = allFiles.filter((f) => f.isLarge).map((f) => f.filename);

    if (largeFiles.length > 0) {
        warnings.push({
            code: 'large_files_detected',
            message: '以下文件超过 40KB，请按章节定位读取，不要整包拉入上下文',
            files: largeFiles,
        });
    }

    return warnings;
}

// ─── Output builders ──────────────────────────────────────────────────────────

function buildPipelineOutput({ hostRoot, docsPath, classified, missingExpected, warnings }) {
    const foundations = [
        classified.foundationGlossary,
        ...classified.foundationSchema,
        ...classified.foundationApi,
        classified.foundationDelivery,
    ].filter(Boolean);

    const explainers = [
        classified.explainerFlow,
        ...classified.explainerInteraction,
        ...classified.explainerGap,
        classified.explainerDelivery,
    ].filter(Boolean);

    const slug =
        classified.mainprd?.slug ||
        classified.prdFeatureList?.slug ||
        foundations[0]?.slug ||
        null;

    return {
        meta: {
            hostRoot,
            docsPath,
            scannedAt: new Date().toISOString(),
            slug,
            mode: 'pipeline',
        },
        mainprd: classified.mainprd
            ? {
                path: classified.mainprd.path,
                title: classified.mainprd.title,
                sizeBytes: classified.mainprd.sizeBytes,
                isLarge: classified.mainprd.isLarge,
                upstreamRefs: classified.mainprd.upstreamRefs,
              }
            : null,
        prdFeatureList: classified.prdFeatureList
            ? {
                path: classified.prdFeatureList.path,
                title: classified.prdFeatureList.title,
                sizeBytes: classified.prdFeatureList.sizeBytes,
                isLarge: classified.prdFeatureList.isLarge,
              }
            : null,
        subprd: classified.subprd.map((f) => ({
            path: f.path,
            order: f.order,
            block: f.block,
            title: f.title,
            sizeBytes: f.sizeBytes,
            isLarge: f.isLarge,
        })),
        foundations: foundations.map((f) => ({
            path: f.path,
            type: f.filename.match(/^foundation-([a-z]+)-/)?.[1] ?? 'unknown',
            title: f.title,
            sizeBytes: f.sizeBytes,
            isLarge: f.isLarge,
            // 拆分模式：主文件仅为索引，子文件才是权威来源，必须纳入读取清单。
            subfiles: (f.subfiles || []).map((s) => ({ path: s.path, sizeBytes: s.sizeBytes, isLarge: s.isLarge })),
        })),
        explainers: explainers.map((f) => ({
            path: f.path,
            type: (() => {
                if (PATTERNS.explainerFlow.test(f.filename)) return 'flow';
                if (PATTERNS.explainerInteraction.test(f.filename)) return `${f.side}-interaction`;
                if (PATTERNS.explainerGap.test(f.filename)) return `${f.side}-gap`;
                if (PATTERNS.explainerDelivery.test(f.filename)) return 'delivery';
                return 'unknown';
            })(),
            title: f.title,
            sizeBytes: f.sizeBytes,
            isLarge: f.isLarge,
        })),
        missingExpected,
        warnings,
        canProceed: missingExpected.filter((m) => m.severity === 'required').length === 0,
        requiredMissing: missingExpected.filter((m) => m.severity === 'required'),
    };
}

function buildFallbackOutput({ hostRoot, docsPath, buckets, warnings }) {
    return {
        meta: {
            hostRoot,
            docsPath,
            scannedAt: new Date().toISOString(),
            slug: null,
            mode: 'fallback',
        },
        prdDocs: buckets.prd,
        foundationDocs: buckets.foundation,
        explainerDocs: buckets.explainer,
        otherDocs: buckets.other,
        missingExpected: [],
        warnings,
        // Fallback mode always allows proceeding – we can't assess "required" set
        canProceed: true,
        requiredMissing: [],
    };
}

// ─── Text formatters ──────────────────────────────────────────────────────────

function formatPipelineReport(output, verbose) {
    const lines = [];

    lines.push('=== collect-upstream-context (pipeline mode) ===');
    lines.push(`Host root : ${output.meta.hostRoot}`);
    lines.push(`Docs dir  : ${output.meta.docsPath}`);
    lines.push(`Slug      : ${output.meta.slug ?? '(未检测到)'}`);
    lines.push(`Scanned   : ${output.meta.scannedAt}`);
    lines.push('');

    lines.push('── mainprd ──');
    if (output.mainprd) {
        lines.push(`  ✅ ${output.mainprd.path}`);
        if (output.mainprd.title) lines.push(`     标题: ${output.mainprd.title}`);
        if (output.mainprd.isLarge) lines.push(`     ⚠️  文件较大 (${(output.mainprd.sizeBytes / 1024).toFixed(1)} KB)，请按章节读取`);
        if (verbose && output.mainprd.upstreamRefs.length > 0) {
            lines.push(`     上游引用: ${output.mainprd.upstreamRefs.join(', ')}`);
        }
    } else {
        lines.push('  ❌ 未找到 mainprd-<slug>.md');
    }
    lines.push('');

    lines.push('── PRD 功能列表 ──');
    if (output.prdFeatureList) {
        lines.push(`  ✅ ${output.prdFeatureList.path}`);
    } else {
        lines.push('  ⚠️  未找到 prd-feature-list-<slug>.md');
    }
    lines.push('');

    lines.push(`── subprd (${output.subprd.length} 份) ──`);
    if (output.subprd.length === 0) {
        lines.push('  ❌ 未找到任何 docs/prd/subprd/0X-subprd-*.md');
    } else {
        for (const c of output.subprd) {
            const sizeTag = c.isLarge ? ` ⚠️(${(c.sizeBytes / 1024).toFixed(1)} KB)` : '';
            lines.push(`  ✅ [${c.block}] ${c.path}${sizeTag}`);
        }
    }
    lines.push('');

    lines.push(`── Foundation 文档 (${output.foundations.length} 份) ──`);
    if (output.foundations.length === 0) {
        lines.push('  ❌ 未找到任何 foundation-*.md');
    } else {
        for (const f of output.foundations) {
            const sizeTag = f.isLarge ? ` ⚠️(${(f.sizeBytes / 1024).toFixed(1)} KB)` : '';
            lines.push(`  ✅ [${f.type}] ${f.path}${sizeTag}`);
            for (const s of f.subfiles ?? []) {
                const subTag = s.isLarge ? ` ⚠️(${(s.sizeBytes / 1024).toFixed(1)} KB)` : '';
                lines.push(`       └─ 拆分子文件（必读）: ${s.path}${subTag}`);
            }
        }
    }
    lines.push('');

    lines.push(`── Explainer 文档 (${output.explainers.length} 份) ──`);
    for (const e of output.explainers) {
        lines.push(`  ✅ [${e.type}] ${e.path}`);
    }
    if (output.explainers.length === 0) lines.push('  (无)');
    lines.push('');

    const requiredMissing = output.missingExpected.filter((m) => m.severity === 'required');
    const expectedMissing = output.missingExpected.filter((m) => m.severity === 'expected');

    if (requiredMissing.length > 0) {
        lines.push('── ❌ 必需文档缺失（进入失败分支）──');
        for (const m of requiredMissing) {
            lines.push(`  • ${m.file}`);
            lines.push(`    原因: ${m.reason}`);
        }
        lines.push('');
    }

    if (expectedMissing.length > 0) {
        lines.push('── ⚠️  建议文档缺失（降级模式可继续）──');
        for (const m of expectedMissing) {
            lines.push(`  • ${m.file}`);
        }
        lines.push('');
    }

    if (output.warnings.length > 0) {
        lines.push('── 警告 ──');
        for (const w of output.warnings) {
            lines.push(`  [${w.code}] ${w.message}`);
            if (w.files) {
                for (const f of w.files) lines.push(`    - ${f}`);
            }
        }
        lines.push('');
    }

    lines.push('── 结论 ──');
    if (output.canProceed) {
        lines.push('  ✅ 可以进入 delivery-planner 写作流程');
        lines.push('     请将以上文件路径作为 Step 1 的读取清单（按优先级: mainprd → foundations → subprd）');
    } else {
        lines.push('  ❌ 进入失败分支：必需上游文档缺失，请先补齐后再运行 delivery-planner');
    }

    return lines.join('\n');
}

function formatFallbackReport(output) {
    const lines = [];

    lines.push('=== collect-upstream-context (fallback mode) ===');
    lines.push(`Host root : ${output.meta.hostRoot}`);
    lines.push(`Docs dir  : ${output.meta.docsPath}`);
    lines.push(`Scanned   : ${output.meta.scannedAt}`);
    lines.push('');
    lines.push('⚠️  未检测到 PIPELINE.md 命名约定，已按关键词模糊分类。');
    lines.push('    以下分类仅供参考，AI 需自行确认文件类型。');
    lines.push('');

    const sections = [
        { label: 'PRD / 需求类', items: output.prdDocs },
        { label: 'Foundation / 基础设施类', items: output.foundationDocs },
        { label: 'Explainer / 流程交互类', items: output.explainerDocs },
        { label: '未分类', items: output.otherDocs },
    ];

    for (const section of sections) {
        lines.push(`── ${section.label} (${section.items.length} 份) ──`);
        if (section.items.length === 0) {
            lines.push('  (无)');
        } else {
            for (const item of section.items) {
                const sizeTag = item.isLarge ? ` ⚠️(${(item.sizeBytes / 1024).toFixed(1)} KB)` : '';
                const matchTag = item.matchedBy ? ` [匹配: ${item.matchedBy}]` : '';
                lines.push(`  📄 ${item.filename}${matchTag}${sizeTag}`);
                if (item.title) lines.push(`     标题: ${item.title}`);
            }
        }
        lines.push('');
    }

    if (output.warnings.length > 0) {
        lines.push('── 警告 ──');
        for (const w of output.warnings) {
            lines.push(`  [${w.code}] ${w.message}`);
            if (w.files) {
                for (const f of w.files) lines.push(`    - ${f}`);
            }
        }
        lines.push('');
    }

    lines.push('── 结论 ──');
    lines.push('  ⚠️  兜底模式：可以继续写计划，但 missingExpected 检测被禁用。');
    lines.push('     建议 AI 自行打开每个文件头部（前 30 行）确认类型后再决定读取深度。');

    return lines.join('\n');
}

// ─── Main ────────────────────────────────────────────────────────────────────

function main() {
    const options = parseArgs(process.argv);

    const hostRoot = path.resolve(options.hostRoot);
    if (!fs.existsSync(hostRoot)) {
        throw new Error(`Host root does not exist: ${hostRoot}`);
    }

    const docsPath = path.join(hostRoot, options.docsDir);
    if (!fs.existsSync(docsPath)) {
        throw new Error(`Docs directory does not exist: ${docsPath}`);
    }

    const files = readDocsDir(docsPath);
    const foundationPath = path.join(docsPath, FOUNDATION_SUBDIR);
    const foundationFiles = readDocsDir(foundationPath);
    const subprdPath = path.join(docsPath, SUBPRD_SUBDIR);
    const subprdFiles = readDocsDir(subprdPath);
    const pagePreviewPath = path.join(hostRoot, PAGE_PREVIEW_DIR);
    const pagePreviewFiles =
        path.resolve(pagePreviewPath) === path.resolve(docsPath)
            ? []
            : readDocsDir(pagePreviewPath);

    // Step 1: try pipeline mode (precise matching)
    const classified = classifyFiles(files, docsPath, { includeSubprd: false, includeFoundation: false, includeExplainer: false });
    if (foundationFiles.length > 0) {
        mergeFoundationArtifacts(
            classified,
            classifyFiles(foundationFiles, foundationPath, { includePrd: false, includeSubprd: false, includeExplainer: false })
        );
    }
    if (subprdFiles.length > 0) {
        mergeSubprdArtifacts(
            classified,
            classifyFiles(subprdFiles, subprdPath, { includePrd: false, includeFoundation: false, includeExplainer: false })
        );
    }
    if (pagePreviewFiles.length > 0) {
        mergePagePreviewExplainers(
            classified,
            classifyFiles(pagePreviewFiles, pagePreviewPath, { includePrd: false, includeSubprd: false, includeFoundation: false })
        );
    }

    // Step 2: check if pipeline mode found any PRD hits
    if (hasPipelineHits(classified)) {
        // Pipeline mode – use precise results
        const missingExpected = detectMissing(classified);
        const warnings = collectWarnings(classified);
        const output = buildPipelineOutput({ hostRoot, docsPath, classified, missingExpected, warnings });

        if (options.json) {
            console.log(JSON.stringify(output, null, 2));
        } else {
            console.log(formatPipelineReport(output, options.verbose));
        }
    } else {
        // Fallback mode – keyword-based fuzzy classification.
        // foundation/ 与 subprd/ 子目录同样纳入扫描（以相对路径参与分类），
        // 避免子目录里的文档在兜底清单中凭空消失。
        const fallbackFiles = [
            ...files,
            ...foundationFiles.map((name) => path.join(FOUNDATION_SUBDIR, name)),
            ...subprdFiles.map((name) => path.join(SUBPRD_SUBDIR, name)),
        ];
        const buckets = fallbackClassify(fallbackFiles, docsPath);
        const warnings = collectFallbackWarnings(buckets);
        const output = buildFallbackOutput({ hostRoot, docsPath, buckets, warnings });

        if (options.json) {
            console.log(JSON.stringify(output, null, 2));
        } else {
            console.log(formatFallbackReport(output));
        }
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

export { main as collectUpstreamContext };
