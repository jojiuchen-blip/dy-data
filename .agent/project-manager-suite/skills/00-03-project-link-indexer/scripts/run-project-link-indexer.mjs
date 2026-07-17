#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import process from 'process';
import { fileURLToPath } from 'url';

import { collectProjectLinks, OUTPUTS } from './collect-project-links.mjs';

const __filename = fileURLToPath(import.meta.url);

const DIAGNOSTIC_TRIGGERS = new Set([
    'need_broken_link_or_reverse_link_check',
    'need_file_relationship_diagnosis',
    'need_impact_lookup'
]);

const REFRESH_TRIGGERS = new Set([
    'after_existing_project_baseline_audit',
    'artifact_files_added_or_split'
]);

const KEY_ARTIFACT_KINDS = new Set([
    'baseline_audit',
    'brd',
    'brd_ledger',
    'page_delivery',
    'page_explainer',
    'page_ledger',
    'foundation',
    'prd_feature_list',
    'mainprd',
    'subprd',
    'delivery_plan',
    'acceptance',
    'test_case',
    'test_review'
]);

function printUsage() {
    console.log('Usage: node run-project-link-indexer.mjs <host-project-root> --trigger <trigger> [--json]');
}

function parseArgs(argv) {
    const args = argv.slice(2);
    const options = {
        hostRoot: '',
        trigger: '',
        json: false
    };

    for (let index = 0; index < args.length; index += 1) {
        const arg = args[index];

        if (arg === '--json') {
            options.json = true;
            continue;
        }

        if (arg === '--trigger') {
            const trigger = args[index + 1];
            if (!trigger) {
                throw new Error('Missing value for --trigger.');
            }
            options.trigger = trigger;
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

    if (!options.trigger) {
        throw new Error('Missing --trigger.');
    }

    return options;
}

function readExistingGraph(graphPath) {
    if (!fs.existsSync(graphPath)) {
        return {
            exists: false,
            parseable: false,
            graph: null
        };
    }

    try {
        return {
            exists: true,
            parseable: true,
            graph: JSON.parse(fs.readFileSync(graphPath, 'utf8'))
        };
    } catch (error) {
        return {
            exists: true,
            parseable: false,
            graph: null,
            error: error.message
        };
    }
}

function keyArtifactNodes(graph) {
    return graph.nodes.filter((node) => KEY_ARTIFACT_KINDS.has(node.kind));
}

function existingNodePathSet(existingGraph) {
    if (!existingGraph || !Array.isArray(existingGraph.nodes)) {
        return null;
    }
    return new Set(existingGraph.nodes.map((node) => node.path).filter(Boolean));
}

function compactResult({ mode, trigger, graph, missingNodePaths = [], reason = '' }) {
    return {
        mode,
        trigger,
        hostRoot: graph.hostRoot,
        outputs: graph.outputs,
        summary: graph.summary,
        issues: graph.issues,
        missingNodePaths,
        reason
    };
}

function runProjectLinkIndexer({ hostRoot, trigger } = {}) {
    if (!hostRoot) {
        throw new Error('hostRoot is required.');
    }
    if (!trigger) {
        throw new Error('trigger is required.');
    }

    if (!DIAGNOSTIC_TRIGGERS.has(trigger) && !REFRESH_TRIGGERS.has(trigger)) {
        console.warn(`Warning: unknown trigger "${trigger}"; treating it as a refresh trigger, index files under docs/index/ may be rewritten.`);
    }

    const resolvedHostRoot = path.resolve(hostRoot);
    const currentGraph = collectProjectLinks({ hostRoot: resolvedHostRoot, write: false });

    if (DIAGNOSTIC_TRIGGERS.has(trigger)) {
        return compactResult({
            mode: 'validate-only',
            trigger,
            graph: currentGraph,
            reason: 'diagnostic trigger requested link validation without rewriting index files'
        });
    }

    const currentKeyNodes = keyArtifactNodes(currentGraph);
    if (currentKeyNodes.length === 0) {
        return compactResult({
            mode: 'noop',
            trigger,
            graph: currentGraph,
            reason: 'no key project artifacts found'
        });
    }

    const graphPath = path.join(resolvedHostRoot, OUTPUTS.graphJson);
    const existing = readExistingGraph(graphPath);

    if (!existing.exists) {
        const writtenGraph = collectProjectLinks({ hostRoot: resolvedHostRoot, write: true });
        return compactResult({
            mode: 'build',
            trigger,
            graph: writtenGraph,
            reason: 'project link index was missing'
        });
    }

    if (!existing.parseable) {
        const writtenGraph = collectProjectLinks({ hostRoot: resolvedHostRoot, write: true });
        return compactResult({
            mode: 'refresh',
            trigger,
            graph: writtenGraph,
            reason: 'project link index JSON was not parseable'
        });
    }

    const existingPaths = existingNodePathSet(existing.graph);
    if (!existingPaths) {
        const writtenGraph = collectProjectLinks({ hostRoot: resolvedHostRoot, write: true });
        return compactResult({
            mode: 'refresh',
            trigger,
            graph: writtenGraph,
            reason: 'project link index node list was invalid'
        });
    }

    const missingNodePaths = currentKeyNodes.map((node) => node.path).filter((nodePath) => !existingPaths.has(nodePath));
    if (missingNodePaths.length > 0) {
        const writtenGraph = collectProjectLinks({ hostRoot: resolvedHostRoot, write: true });
        return compactResult({
            mode: 'refresh',
            trigger,
            graph: writtenGraph,
            missingNodePaths,
            reason: 'project link index missed current key artifact nodes'
        });
    }

    return compactResult({
        mode: 'noop',
        trigger,
        graph: currentGraph,
        reason: 'project link index already covers current key artifacts'
    });
}

function formatRunReport(result) {
    const lines = [
        `Host root: ${result.hostRoot}`,
        `Mode: ${result.mode}`,
        `Trigger: ${result.trigger}`,
        `Nodes: ${result.summary.nodes}`,
        `Edges: ${result.summary.edges}`,
        `Issues: ${result.summary.issues}`
    ];

    if (result.missingNodePaths.length > 0) {
        lines.push('', 'Missing nodes:');
        for (const nodePath of result.missingNodePaths) {
            lines.push(`- ${nodePath}`);
        }
    }

    if (result.reason) {
        lines.push('', `Reason: ${result.reason}`);
    }

    return lines.join('\n');
}

function main() {
    const options = parseArgs(process.argv);
    const result = runProjectLinkIndexer(options);

    if (options.json) {
        console.log(JSON.stringify(result, null, 2));
        return;
    }

    console.log(formatRunReport(result));
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
    DIAGNOSTIC_TRIGGERS,
    KEY_ARTIFACT_KINDS,
    REFRESH_TRIGGERS,
    formatRunReport,
    runProjectLinkIndexer
};
