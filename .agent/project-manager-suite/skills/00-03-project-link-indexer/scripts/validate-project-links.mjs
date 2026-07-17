#!/usr/bin/env node

import path from 'path';
import process from 'process';
import { fileURLToPath } from 'url';

import { collectProjectLinks } from './collect-project-links.mjs';

const __filename = fileURLToPath(import.meta.url);

function printUsage() {
    console.log('Usage: node validate-project-links.mjs <host-project-root> [--json]');
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

function validateProjectLinks({ hostRoot } = {}) {
    const graph = collectProjectLinks({ hostRoot, write: false });
    const errors = graph.issues.filter((item) => item.severity === 'error');

    return {
        mode: 'project-link-validation',
        hostRoot: graph.hostRoot,
        valid: errors.length === 0,
        summary: graph.summary,
        issues: graph.issues,
        graph
    };
}

function formatValidationReport(result) {
    const lines = [
        `Host root: ${result.hostRoot}`,
        `Valid: ${result.valid ? 'yes' : 'no'}`,
        `Nodes: ${result.summary.nodes}`,
        `Edges: ${result.summary.edges}`,
        `Errors: ${result.summary.errors}`,
        `Warnings: ${result.summary.warnings}`,
        '',
        'Issues:'
    ];

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
    const result = validateProjectLinks(options);

    if (options.json) {
        console.log(JSON.stringify(result, null, 2));
    } else {
        console.log(formatValidationReport(result));
    }

    if (!result.valid) {
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

export { formatValidationReport, validateProjectLinks };
