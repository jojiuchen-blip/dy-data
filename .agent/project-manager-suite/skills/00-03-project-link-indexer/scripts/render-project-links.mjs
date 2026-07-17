#!/usr/bin/env node

import path from 'path';
import process from 'process';
import { fileURLToPath } from 'url';

import { collectProjectLinks, renderGraphMarkdown } from './collect-project-links.mjs';

const __filename = fileURLToPath(import.meta.url);

function printUsage() {
    console.log('Usage: node render-project-links.mjs <host-project-root> [--json] [--dry-run]');
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

function renderProjectLinks({ hostRoot, write = true } = {}) {
    return collectProjectLinks({ hostRoot, write });
}

function main() {
    const options = parseArgs(process.argv);
    const result = renderProjectLinks(options);

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

export { renderProjectLinks };
