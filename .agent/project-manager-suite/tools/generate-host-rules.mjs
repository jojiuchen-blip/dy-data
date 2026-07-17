#!/usr/bin/env node

/**
 * Traceability:
 * Rule sources:
 * - skills/00-01-ai-project-manager/references/core/global-files-protocol.md
 * - skills/00-01-ai-project-manager/references/core/routing.md
 * - skills/00-01-ai-project-manager/references/rules/*.md
 * Structured config:
 * - lib/ai-pm-protocol/rules-sync.js
 * Related tools:
 * - tools/bootstrap-host.mjs
 */
import fs from 'fs';
import path from 'path';
import process from 'process';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const suiteRoot = path.resolve(__dirname, '..');
const sourceDir = path.join(
    suiteRoot,
    'skills',
    '00-01-ai-project-manager',
    'references',
    'rules'
);

function printUsage() {
    console.log('Usage: node <suite-path>/tools/generate-host-rules.mjs <host-project-root> [--force] [--dry-run]');
    console.log(
        '<suite-path> 指套件根目录：源码仓库联调时为 project-manager-suite/，安装到宿主后为 .agent/project-manager-suite/；命令默认在宿主项目根目录执行。'
    );
}

function parseArgs(argv) {
    const args = argv.slice(2);
    const options = {
        force: false,
        dryRun: false,
        hostRoot: ''
    };

    for (const arg of args) {
        if (arg === '--force') {
            options.force = true;
            continue;
        }

        if (arg === '--dry-run') {
            options.dryRun = true;
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

function buildGeneratedContent(sourceFileName, sourceContent) {
    const normalized = sourceContent.endsWith('\n') ? sourceContent : `${sourceContent}\n`;
    return [
        '<!-- generated-by: ai-project-manager -->',
        `<!-- source: skills/00-01-ai-project-manager/references/rules/${sourceFileName} -->`,
        '',
        normalized
    ].join('\n');
}

function formatResults(hostRoot, targetDir, options, results) {
    const lines = [
        `Host root: ${hostRoot}`,
        `Source rules: ${sourceDir}`,
        `Target rules: ${targetDir}`,
        `Mode: ${options.dryRun ? 'dry-run' : options.force ? 'force' : 'default'}`,
        `Created: ${results.created.length}`,
        `Overwritten: ${results.overwritten.length}`,
        `Skipped: ${results.skipped.length}`
    ];

    for (const filePath of results.created) {
        lines.push(`CREATE ${filePath}`);
    }

    for (const filePath of results.overwritten) {
        lines.push(`OVERWRITE ${filePath}`);
    }

    for (const filePath of results.skipped) {
        lines.push(`SKIP ${filePath}`);
    }

    return lines;
}

function generateHostRules({ hostRoot, force = false, dryRun = false }) {
    const resolvedHostRoot = path.resolve(process.cwd(), hostRoot);
    const targetDir = path.join(resolvedHostRoot, 'docs', 'rules');

    if (!fs.existsSync(sourceDir)) {
        throw new Error(`Source rules directory not found: ${sourceDir}`);
    }

    const sourceFiles = fs
        .readdirSync(sourceDir, { withFileTypes: true })
        .filter((entry) => entry.isFile() && entry.name.endsWith('.md'))
        .map((entry) => entry.name)
        .sort();

    if (sourceFiles.length === 0) {
        throw new Error(`No source rule files found in: ${sourceDir}`);
    }

    const results = {
        created: [],
        overwritten: [],
        skipped: []
    };

    if (!dryRun) {
        fs.mkdirSync(targetDir, { recursive: true });
    }

    for (const sourceFileName of sourceFiles) {
        const sourcePath = path.join(sourceDir, sourceFileName);
        const targetPath = path.join(targetDir, sourceFileName);
        const exists = fs.existsSync(targetPath);

        if (exists && !force) {
            results.skipped.push(targetPath);
            continue;
        }

        const sourceContent = fs.readFileSync(sourcePath, 'utf8');
        const generatedContent = buildGeneratedContent(sourceFileName, sourceContent);

        if (!dryRun) {
            fs.mkdirSync(path.dirname(targetPath), { recursive: true });
            fs.writeFileSync(targetPath, generatedContent, 'utf8');
        }

        if (exists) {
            results.overwritten.push(targetPath);
        } else {
            results.created.push(targetPath);
        }
    }

    return {
        hostRoot: resolvedHostRoot,
        sourceDir,
        targetDir,
        results
    };
}

function main() {
    const options = parseArgs(process.argv);
    const output = generateHostRules(options);

    for (const line of formatResults(output.hostRoot, output.targetDir, options, output.results)) {
        console.log(line);
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

export { generateHostRules, formatResults };
