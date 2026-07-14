#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import process from 'process';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);

const OUTPUTS = {
    graphJson: 'docs/index/project-link-graph.json',
    graphMarkdown: 'docs/index/project-link-graph.md',
    wikiSchemaJson: 'docs/index/project-wiki-schema.json'
};

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

const textExtensions = new Set([
    '.md',
    '.mdx',
    '.json',
    '.yml',
    '.yaml',
    '.js',
    '.jsx',
    '.mjs',
    '.cjs',
    '.ts',
    '.tsx',
    '.vue',
    '.css',
    '.scss',
    '.html',
    '.py',
    '.java',
    '.sql'
]);

const relationDefinitions = [
    {
        id: 'indexes',
        description: '索引文件列出并指向子文件，子文件仍保留自身内容权威'
    },
    {
        id: 'depends_on',
        description: '下游文件在执行、理解或生成时需要读取上游文件'
    },
    {
        id: 'links_to',
        description: '普通引用或导航关系'
    },
    {
        id: 'implements',
        description: '代码文件实现某个规格、计划或页面说明'
    },
    {
        id: 'verifies',
        description: '验收或测试文件验证某个需求、验收条目或实现文件'
    },
    {
        id: 'derived_from',
        description: '文件内容由上游材料推导而来'
    }
];

const fileKindDefinitions = {
    project_profile: {
        owner_skill: 'ai-project-manager',
        authority: true,
        description: '项目画像与当前阶段入口'
    },
    project_rules: {
        owner_skill: 'ai-project-manager',
        authority: true,
        description: '宿主项目协作规则入口'
    },
    baseline_audit: {
        owner_skill: 'project-baseline-auditor',
        authority: false,
        description: '既有项目基线诊断清单'
    },
    brd: {
        owner_skill: 'brd-writer',
        authority: true,
        description: '业务需求文档'
    },
    brd_ledger: {
        owner_skill: 'brd-writer',
        authority: false,
        description: 'BRD 决策台账'
    },
    page_delivery: {
        owner_skill: 'page-designer',
        authority: false,
        description: '页面交付清单'
    },
    page_explainer: {
        owner_skill: 'page-explainer',
        authority: true,
        description: '页面流程、交互语义或差异说明'
    },
    page_ledger: {
        owner_skill: 'page-designer',
        authority: false,
        description: '页面台账'
    },
    foundation: {
        owner_skill: 'foundation-builder',
        authority: true,
        description: '术语表、Schema、API 或 foundation 交付清单'
    },
    prd_feature_list: {
        owner_skill: 'prd-writer',
        authority: true,
        description: 'PRD 功能列表'
    },
    mainprd: {
        owner_skill: 'prd-writer',
        authority: true,
        description: 'mainprd 索引'
    },
    subprd: {
        owner_skill: 'prd-writer',
        authority: true,
        description: '按功能区块拆分的 subprd'
    },
    delivery_plan: {
        owner_skill: 'delivery-planner',
        authority: true,
        description: '开发执行计划'
    },
    source_code: {
        owner_skill: 'coding-standards',
        authority: true,
        description: '宿主项目代码文件'
    },
    acceptance: {
        owner_skill: 'prd-acceptance-reviewer',
        authority: true,
        description: '验收文档'
    },
    test_case: {
        owner_skill: 'test-case-writer',
        authority: true,
        description: '测试用例或测试数据'
    },
    test_review: {
        owner_skill: 'test-case-reviewer',
        authority: false,
        description: '测试用例核查问题清单'
    },
    config: {
        owner_skill: 'host-project',
        authority: true,
        description: '宿主配置文件'
    },
    readme: {
        owner_skill: 'host-project',
        authority: false,
        description: '宿主 README 或说明入口'
    },
    project_index: {
        owner_skill: 'project-link-indexer',
        authority: false,
        description: '由索引器生成的关系图与 wiki schema'
    },
    doc: {
        owner_skill: 'host-project',
        authority: false,
        description: '其他宿主文档'
    },
    data_file: {
        owner_skill: 'host-project',
        authority: false,
        description: '结构化数据文件'
    }
};

function printUsage() {
    console.log('Usage: node collect-project-links.mjs <host-project-root> [--json] [--dry-run]');
}

function parseArgs(argv) {
    const args = argv.slice(2);
    const options = {
        hostRoot: '',
        json: false,
        write: true
    };

    for (const arg of args) {
        if (arg === '--json') {
            options.json = true;
            continue;
        }
        if (arg === '--dry-run') {
            options.write = false;
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

function normalizeRelative(rootDir, targetPath) {
    return path.relative(rootDir, targetPath).split(path.sep).join('/');
}

function normalizePosix(inputPath) {
    return path.posix.normalize(String(inputPath || '').split(path.sep).join('/')).replace(/^\.\//, '');
}

function shouldIgnoreDir(relativeDir) {
    const normalizedDir = normalizePosix(relativeDir);
    const segments = normalizedDir.split('/').filter(Boolean);

    return [...ignoredDirectories].some((ignored) => {
        if (!ignored.includes('/')) {
            return segments.includes(ignored);
        }

        return (
            normalizedDir === ignored ||
            normalizedDir.startsWith(`${ignored}/`) ||
            normalizedDir.endsWith(`/${ignored}`) ||
            normalizedDir.includes(`/${ignored}/`)
        );
    });
}

function isAllowedFile(relativePath) {
    const baseName = path.basename(relativePath);
    const ext = path.extname(relativePath).toLowerCase();

    if (relativePath === OUTPUTS.graphJson || relativePath === OUTPUTS.graphMarkdown || relativePath === OUTPUTS.wikiSchemaJson) {
        return true;
    }

    if (baseName === 'package.json') {
        return true;
    }

    return textExtensions.has(ext);
}

function walkFiles(rootDir, maxDepth = 12) {
    const results = [];

    function recurse(currentDir, depth) {
        if (depth > maxDepth || !fs.existsSync(currentDir)) return;

        for (const entry of fs.readdirSync(currentDir, { withFileTypes: true })) {
            const fullPath = path.join(currentDir, entry.name);
            const relativePath = normalizeRelative(rootDir, fullPath);

            if (entry.isDirectory()) {
                if (!shouldIgnoreDir(relativePath)) {
                    recurse(fullPath, depth + 1);
                }
                continue;
            }

            if (entry.isFile() && isAllowedFile(relativePath)) {
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

function safeReadText(filePath, maxBytes = 512 * 1024) {
    try {
        const stat = fs.statSync(filePath);
        if (stat.size > maxBytes) {
            return '';
        }
        return fs.readFileSync(filePath, 'utf8');
    } catch {
        return '';
    }
}

function extractTitle(content, relativePath) {
    const heading = content.match(/^#\s+(.+)$/m);
    if (heading) {
        return heading[1].trim();
    }
    return path.basename(relativePath);
}

function extractSlug(kind, relativePath) {
    const baseName = path.basename(relativePath, path.extname(relativePath));
    const matchers = [
        /^BRD-(.+?)-\d{8}/,
        /^brd-ledger-(.+)$/,
        /^baseline-audit-(.+)$/,
        /^page-(?:delivery|ledger)-(.+)$/,
        /^explainer-(?:flow|b-interaction|b-gap|delivery)-(.+)$/,
        /^foundation-(?:glossary|schema|api|delivery)-(.+)$/,
        /^prd-feature-list-(.+)$/,
        /^mainprd-(.+)$/,
        /^main-delivery-plan-(.+)$/,
        /^task-kanban-(.+)$/,
        /^acceptance-(.+)$/,
        /^tc-main-(.+)$/
    ];

    for (const matcher of matchers) {
        const match = baseName.match(matcher);
        if (match) return match[1];
    }

    if (kind === 'subprd') {
        const match = baseName.match(/^\d{2}-subprd-(.+)$/);
        if (match) return match[1];
    }

    if (kind === 'delivery_plan') {
        const match = baseName.match(/^sub-delivery-plan-(.+?)-T\d+\.\d+-.+$/);
        if (match) return match[1];
    }

    return null;
}

function classifyFile(relativePath) {
    const ext = path.extname(relativePath).toLowerCase();
    const baseName = path.basename(relativePath);

    if (relativePath === 'project-profile.md') return 'project_profile';
    if (relativePath === 'project-rules.md') return 'project_rules';
    if (relativePath.startsWith('docs/index/project-link-')) return 'project_index';
    if (/^docs\/baseline\/baseline-audit-.+\.(?:json|md)$/.test(relativePath)) return 'baseline_audit';
    if (/^docs\/brd\/brd-ledger-.+\.md$/.test(relativePath)) return 'brd_ledger';
    if (/^docs\/brd\/BRD-.+\.md$/.test(relativePath)) return 'brd';
    if (/^src\/frontend\/page-preview\/page-delivery-.+\.md$/.test(relativePath)) return 'page_delivery';
    if (/^src\/frontend\/page-preview\/page-ledger-.+\.json$/.test(relativePath)) return 'page_ledger';
    if (/^src\/frontend\/page-preview\/explainer-.+\.md$/.test(relativePath)) return 'page_explainer';
    if (/^docs\/prd\/(?:foundation\/)?foundation-.+\.md$/.test(relativePath)) return 'foundation';
    if (/^docs\/prd\/prd-feature-list-.+\.md$/.test(relativePath)) return 'prd_feature_list';
    if (/^docs\/prd\/mainprd-.+\.md$/.test(relativePath)) return 'mainprd';
    if (/^docs\/prd\/subprd\/\d{2}-subprd-.+\.md$/.test(relativePath)) return 'subprd';
    if (/^docs\/plans\/delivery-plans\/(?:main-delivery-plan|sub-delivery-plan|task-kanban)-.+\.md$/.test(relativePath)) return 'delivery_plan';
    if (/^docs\/test-case\/acceptance-.+\.md$/.test(relativePath)) return 'acceptance';
    if (/^docs\/test-case\/acceptance-.+\/.+\.md$/.test(relativePath)) return 'acceptance';
    if (/^docs\/test-case\/tc-main-.+\.md$/.test(relativePath)) return 'test_case';
    if (/^docs\/test-case\/tc-reviews\/.+\.md$/.test(relativePath)) return 'test_review';
    if (/^docs\/test-case\/.+\/(?:tc-.+\.md|sql\/.+\.sql)$/.test(relativePath)) return 'test_case';
    if (/^readme(?:\.[a-z]+)?$/i.test(baseName)) return 'readme';
    if (baseName === 'package.json' || ['.json', '.yml', '.yaml'].includes(ext)) return 'config';
    if (relativePath.startsWith('src/') || ['.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '.vue', '.py', '.java'].includes(ext)) {
        return 'source_code';
    }
    if (['.json', '.sql'].includes(ext)) return 'data_file';
    return 'doc';
}

function buildNode(file, content) {
    const kind = classifyFile(file.relativePath);
    const definition = fileKindDefinitions[kind] || fileKindDefinitions.doc;

    return {
        id: file.relativePath,
        path: file.relativePath,
        kind,
        owner_skill: definition.owner_skill,
        authority: definition.authority,
        slug: extractSlug(kind, file.relativePath),
        title: extractTitle(content, file.relativePath)
    };
}

function stripTarget(rawTarget) {
    let target = String(rawTarget || '').trim();
    if (!target) return null;

    target = target.replace(/^<|>$/g, '').trim();
    target = target.replace(/^['"]|['"]$/g, '').trim();

    const firstWhitespace = target.search(/\s/);
    if (firstWhitespace > -1) {
        target = target.slice(0, firstWhitespace);
    }

    if (/^(?:https?:|mailto:|tel:|#)/i.test(target)) {
        return null;
    }

    const hashIndex = target.indexOf('#');
    const anchor = hashIndex >= 0 ? target.slice(hashIndex + 1) : '';
    const withoutAnchor = hashIndex >= 0 ? target.slice(0, hashIndex) : target;
    if (!withoutAnchor) return null;

    try {
        target = decodeURIComponent(withoutAnchor);
    } catch {
        target = withoutAnchor;
    }

    return {
        target,
        anchor
    };
}

function buildFileIndexes(files) {
    const byPath = new Map();
    const byBase = new Map();

    for (const file of files) {
        byPath.set(file.relativePath, file);
        const base = path.basename(file.relativePath);
        if (!byBase.has(base)) byBase.set(base, []);
        byBase.get(base).push(file.relativePath);
    }

    return { byPath, byBase };
}

function resolveTarget({ sourcePath, rawTarget, indexes }) {
    const stripped = stripTarget(rawTarget);
    if (!stripped) return null;

    const sourceDir = path.posix.dirname(sourcePath);
    const target = stripped.target.split('\\').join('/');
    const candidates = [];

    function addCandidate(candidate) {
        if (!candidate) return;
        const normalized = normalizePosix(candidate).replace(/^\/+/, '');
        if (!normalized || normalized.startsWith('../')) return;
        if (!candidates.includes(normalized)) candidates.push(normalized);
    }

    if (target.startsWith('/')) {
        addCandidate(target.slice(1));
    } else if (target.startsWith('./') || target.startsWith('../')) {
        addCandidate(path.posix.join(sourceDir, target));
    } else {
        addCandidate(path.posix.join(sourceDir, target));
        addCandidate(target);

        if (!target.includes('/')) {
            addCandidate(path.posix.join('docs/prd', target));
            addCandidate(path.posix.join('docs/brd', target));
            addCandidate(path.posix.join('docs/plans/delivery-plans', target));
            addCandidate(path.posix.join('src/frontend/page-preview', target));
            for (const byBaseMatch of indexes.byBase.get(path.basename(target)) || []) {
                addCandidate(byBaseMatch);
            }
        }
    }

    const resolvedPath = candidates.find((candidate) => indexes.byPath.has(candidate));
    return {
        rawTarget,
        normalizedTarget: candidates[0] || normalizePosix(target),
        resolvedPath: resolvedPath || null,
        anchor: stripped.anchor,
        candidates
    };
}

function extractReferences(sourcePath, content) {
    const references = [];
    const ext = path.extname(sourcePath).toLowerCase();
    if (!['.md', '.mdx'].includes(ext)) {
        return references;
    }

    const lines = content.split('\n');
    let inPrdDoubleLink = false;

    for (let index = 0; index < lines.length; index += 1) {
        const lineNumber = index + 1;
        const line = lines[index];
        const trimmed = line.trim();

        if (/^#{1,6}\s+/.test(trimmed) || /^\*\*[^*]+?\*\*[:：]\s*$/.test(trimmed)) {
            inPrdDoubleLink = /\*\*PRD\s*双链[·.]?\s*读\*\*/.test(trimmed);
        }

        for (const match of line.matchAll(/(?<!!)\[[^\]]+\]\(([^)]+)\)/g)) {
            references.push({
                rawTarget: match[1],
                line: lineNumber,
                text: line.trim(),
                syntax: 'markdown'
            });
        }

        for (const match of line.matchAll(/\[\[([^\]|]+)(?:\|[^\]]+)?\]\]/g)) {
            references.push({
                rawTarget: match[1],
                line: lineNumber,
                text: line.trim(),
                syntax: 'wiki'
            });
        }

        for (const match of line.matchAll(/`([^`]+\.md(?:#[^`]*)?)`/g)) {
            references.push({
                rawTarget: match[1],
                line: lineNumber,
                text: line.trim(),
                syntax: inPrdDoubleLink || /PRD\s*双链[·.]?\s*读/.test(line) ? 'prd_double_link' : 'backtick'
            });
        }
    }

    return references;
}

function inferRelation(sourceNode, targetNode, reference) {
    if (reference.syntax === 'prd_double_link') return 'depends_on';
    if (!targetNode) return 'links_to';

    if (sourceNode.kind === 'mainprd' && targetNode.kind === 'subprd') return 'indexes';
    if (sourceNode.kind === 'delivery_plan' && ['mainprd', 'subprd', 'foundation', 'page_explainer', 'page_delivery', 'brd'].includes(targetNode.kind)) {
        return 'depends_on';
    }
    if (['page_delivery', 'page_explainer', 'foundation', 'prd_feature_list', 'mainprd', 'subprd'].includes(sourceNode.kind) && targetNode.authority) {
        return 'depends_on';
    }
    if (sourceNode.kind === 'source_code' && ['mainprd', 'subprd', 'delivery_plan', 'page_explainer', 'foundation'].includes(targetNode.kind)) {
        return 'implements';
    }
    if (['acceptance', 'test_case', 'test_review'].includes(sourceNode.kind) && ['mainprd', 'subprd', 'acceptance', 'source_code'].includes(targetNode.kind)) {
        return 'verifies';
    }
    return 'links_to';
}

function addEdge(edgeMap, edge) {
    const key = `${edge.from}::${edge.to || edge.target}::${edge.relation}`;
    const existing = edgeMap.get(key);
    if (existing) {
        existing.evidence.push(...edge.evidence);
        return;
    }
    edgeMap.set(key, edge);
}

function buildBrokenLinkIssue(sourceNode, reference, resolved) {
    return {
        severity: 'error',
        code: 'broken_link',
        message: `${sourceNode.path}:${reference.line} references missing file ${resolved.normalizedTarget}`,
        from: sourceNode.path,
        target: resolved.normalizedTarget,
        evidence: {
            path: sourceNode.path,
            line: reference.line,
            text: reference.text,
            syntax: reference.syntax
        }
    };
}

function hasEdge(edges, from, to) {
    return edges.some((edge) => edge.from === from && edge.to === to && edge.status === 'resolved');
}

function buildValidationIssues(nodes, edges) {
    const issues = [];
    const byPath = new Map(nodes.map((node) => [node.path, node]));

    for (const edge of edges) {
        if (edge.status === 'missing') {
            issues.push({
                severity: 'error',
                code: 'broken_link',
                message: `${edge.from} references missing file ${edge.target}`,
                from: edge.from,
                target: edge.target,
                evidence: edge.evidence[0] || null
            });
        }
    }

    for (const edge of edges.filter((item) => item.relation === 'indexes' && item.status === 'resolved')) {
        const source = byPath.get(edge.from);
        const target = byPath.get(edge.to);
        if (!source || !target) continue;
        if (source.kind !== 'mainprd' || target.kind !== 'subprd') continue;
        if (!hasEdge(edges, target.path, source.path)) {
            issues.push({
                severity: 'warning',
                code: 'missing_reverse_link',
                message: `${target.path} should link back to ${source.path}`,
                from: target.path,
                to: source.path,
                requiredBy: 'mainprd_to_subprd_bidirectional_index'
            });
        }
    }

    for (const node of nodes) {
        if (!['brd', 'page_explainer', 'foundation', 'mainprd', 'subprd', 'delivery_plan'].includes(node.kind)) {
            continue;
        }
        const connected = edges.some((edge) => edge.status === 'resolved' && (edge.from === node.path || edge.to === node.path));
        if (!connected) {
            issues.push({
                severity: 'info',
                code: 'orphan_artifact',
                message: `${node.path} has no discovered file-level relationship`,
                path: node.path
            });
        }
    }

    return issues.sort((a, b) => `${a.severity}:${a.code}:${a.message}`.localeCompare(`${b.severity}:${b.code}:${b.message}`));
}

function buildWikiSchema() {
    return {
        schemaVersion: '1.0.0',
        principle: 'project-link-indexer compiles a rebuildable LLM wiki style file graph from existing host artifacts; source artifacts remain authoritative.',
        outputs: OUTPUTS,
        nodeFields: ['id', 'path', 'kind', 'owner_skill', 'authority', 'slug', 'title'],
        edgeFields: ['id', 'from', 'to', 'target', 'relation', 'status', 'anchor', 'evidence'],
        relationTypes: relationDefinitions,
        fileKinds: fileKindDefinitions,
        requiredRelations: [
            {
                from_kind: 'mainprd',
                relation: 'indexes',
                to_kind: 'subprd',
                reverse_required: true,
                reverse_relation: 'links_to',
                missing_issue: 'missing_reverse_link'
            }
        ],
        writePolicy: {
            mayRewrite: Object.values(OUTPUTS),
            mustNotRewriteAsSourceOfTruth: true,
            sourceOfTruth: 'project-profile.md, docs/brd, src/frontend/page-preview, docs/prd, docs/plans/delivery-plans, docs/test-case, and host code files'
        }
    };
}

function wikiLinkForNode(node) {
    return `[[${node.path}|${node.title}]]`;
}

function markdownLinkFromIndex(targetPath, title) {
    const relative = normalizePosix(path.posix.relative('docs/index', targetPath));
    return `[${title}](${relative})`;
}

function renderGraphMarkdown(graph) {
    const lines = [
        '# 项目文件引用索引',
        '',
        '> 本文件由 project-link-indexer 编译生成。它是给人和 LLM 读取的索引，不替代原始需求、PRD、计划或代码文件。',
        '',
        '## 1. 摘要',
        '',
        `- 文件节点：${graph.summary.nodes}`,
        `- 文件关系：${graph.summary.edges}`,
        `- 诊断问题：${graph.summary.issues}`,
        `- 机器索引：\`${graph.outputs.graphJson}\``,
        `- 关系 schema：\`${graph.outputs.wikiSchemaJson}\``,
        '',
        '## 2. Wiki 入口',
        '',
        '| 文件 | 类型 | owner skill | wiki 链接 | markdown 链接 |',
        '|---|---|---|---|---|'
    ];

    for (const node of graph.nodes.filter((item) => item.kind !== 'project_index').slice(0, 80)) {
        lines.push(
            `| ${node.title} | ${node.kind} | ${node.owner_skill} | ${wikiLinkForNode(node)} | ${markdownLinkFromIndex(node.path, node.title)} |`
        );
    }

    lines.push('', '## 3. 关系', '', '| 来源 | 关系 | 目标 | 证据 |', '|---|---|---|---|');
    for (const edge of graph.edges.filter((item) => item.status === 'resolved').slice(0, 120)) {
        const evidence = edge.evidence[0] ? `${edge.evidence[0].path}:${edge.evidence[0].line}` : '';
        lines.push(`| ${edge.from} | ${edge.relation} | ${edge.to} | ${evidence} |`);
    }

    lines.push('', '## 4. 诊断问题', '', '| 级别 | code | 位置 | 说明 |', '|---|---|---|---|');
    if (graph.issues.length === 0) {
        lines.push('| info | none | - | 未发现索引级问题 |');
    } else {
        for (const issue of graph.issues) {
            lines.push(`| ${issue.severity} | ${issue.code} | ${issue.from || issue.path || '-'} | ${issue.message} |`);
        }
    }

    return `${lines.join('\n')}\n`;
}

function summarize(nodes, edges, issues) {
    const nodesByKind = {};
    const edgesByRelation = {};
    for (const node of nodes) {
        nodesByKind[node.kind] = (nodesByKind[node.kind] || 0) + 1;
    }
    for (const edge of edges) {
        edgesByRelation[edge.relation] = (edgesByRelation[edge.relation] || 0) + 1;
    }
    return {
        nodes: nodes.length,
        edges: edges.length,
        issues: issues.length,
        errors: issues.filter((item) => item.severity === 'error').length,
        warnings: issues.filter((item) => item.severity === 'warning').length,
        nodesByKind,
        edgesByRelation
    };
}

function ensureDir(dirPath) {
    fs.mkdirSync(dirPath, { recursive: true });
}

function collectProjectLinks({ hostRoot, write = true } = {}) {
    if (!hostRoot) {
        throw new Error('hostRoot is required.');
    }

    const resolvedHostRoot = path.resolve(hostRoot);
    const files = walkFiles(resolvedHostRoot);
    const fileContents = new Map();
    const nodes = [];

    for (const file of files) {
        const content = safeReadText(file.filePath);
        fileContents.set(file.relativePath, content);
        nodes.push(buildNode(file, content));
    }

    const indexes = buildFileIndexes(files);
    const nodeByPath = new Map(nodes.map((node) => [node.path, node]));
    const edgeMap = new Map();

    for (const node of nodes) {
        if (node.kind === 'project_index') continue;
        const content = fileContents.get(node.path) || '';
        if (!content) continue;

        for (const reference of extractReferences(node.path, content)) {
            const resolved = resolveTarget({
                sourcePath: node.path,
                rawTarget: reference.rawTarget,
                indexes
            });
            if (!resolved) continue;

            const targetNode = resolved.resolvedPath ? nodeByPath.get(resolved.resolvedPath) : null;
            if (!resolved.resolvedPath && reference.syntax === 'backtick') {
                continue;
            }

            const relation = inferRelation(node, targetNode, reference);
            const evidence = [
                {
                    path: node.path,
                    line: reference.line,
                    text: reference.text,
                    syntax: reference.syntax
                }
            ];

            addEdge(edgeMap, {
                id: `${node.path}->${resolved.resolvedPath || resolved.normalizedTarget}:${relation}`,
                from: node.path,
                to: resolved.resolvedPath,
                target: resolved.resolvedPath || resolved.normalizedTarget,
                relation,
                status: resolved.resolvedPath ? 'resolved' : 'missing',
                anchor: resolved.anchor || null,
                evidence
            });
        }
    }

    const edges = Array.from(edgeMap.values()).sort((a, b) => a.id.localeCompare(b.id));
    const issues = buildValidationIssues(nodes, edges);
    const graph = {
        mode: 'project-link-index',
        schemaVersion: '1.0.0',
        generatedAt: new Date().toISOString(),
        hostRoot: '.',
        outputs: OUTPUTS,
        summary: summarize(nodes, edges, issues),
        nodes: nodes.sort((a, b) => a.path.localeCompare(b.path)),
        edges,
        issues,
        wikiSchema: buildWikiSchema()
    };

    if (write) {
        const outputDir = path.join(resolvedHostRoot, 'docs', 'index');
        ensureDir(outputDir);
        fs.writeFileSync(path.join(resolvedHostRoot, OUTPUTS.graphJson), JSON.stringify(graph, null, 2), 'utf8');
        fs.writeFileSync(path.join(resolvedHostRoot, OUTPUTS.graphMarkdown), renderGraphMarkdown(graph), 'utf8');
        fs.writeFileSync(path.join(resolvedHostRoot, OUTPUTS.wikiSchemaJson), JSON.stringify(graph.wikiSchema, null, 2), 'utf8');
    }

    return graph;
}

function main() {
    const options = parseArgs(process.argv);
    const result = collectProjectLinks(options);

    if (options.json) {
        console.log(JSON.stringify(result, null, 2));
        return;
    }

    console.log(renderGraphMarkdown(result));
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

export {
    OUTPUTS,
    buildWikiSchema,
    collectProjectLinks,
    renderGraphMarkdown,
    relationDefinitions,
    fileKindDefinitions
};
