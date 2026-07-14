import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { fileURLToPath } from 'node:url';

import { checkProtocolAlignment } from '../tools/check-protocol-alignment.mjs';

const TEST_FILE_PATH = fileURLToPath(import.meta.url);
const CURRENT_SUITE_ROOT = path.resolve(path.dirname(TEST_FILE_PATH), '..');

function makeTempDir(prefix) {
    return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function writeFile(targetPath, content) {
    fs.mkdirSync(path.dirname(targetPath), { recursive: true });
    fs.writeFileSync(targetPath, content, 'utf8');
}

function buildProtocolDoc(structuredFiles) {
    const fileLines = structuredFiles.map((item) => `  - \`${item}\``).join('\n');
    return `# 示例协议

## 对应实现与执行入口

对应关系：

- 结构化实现：
${fileLines}
- 对应脚本：
  - \`tools/example.mjs\`
`;
}

function buildStructuredFile(ruleSources) {
    const sourceLines = ruleSources.map((item) => ` * - ${item}`).join('\n');
    return `/**
 * Traceability:
 * Rule sources:
${sourceLines}
 * Consumed by:
 * - tools/example.mjs
 */
export const example = true;
`;
}

test('check-protocol-alignment passes on the current suite', () => {
    const result = checkProtocolAlignment({ suiteRoot: CURRENT_SUITE_ROOT });

    assert.equal(result.summary.errors, 0);
});

test('check-protocol-alignment detects missing reverse link in a synthetic fixture', () => {
    const suiteRoot = makeTempDir('pm-suite-alignment-');
    const docPath = 'skills/00-01-ai-project-manager/references/core/runtime.md';
    const structuredPath = 'lib/ai-pm-protocol/stages.js';

    writeFile(path.join(suiteRoot, docPath), buildProtocolDoc([structuredPath]));
    writeFile(
        path.join(suiteRoot, 'skills/00-01-ai-project-manager/SKILL.md'),
        buildProtocolDoc(['lib/ai-pm-protocol/bootstrap.js'])
    );
    writeFile(
        path.join(suiteRoot, 'skills/00-01-ai-project-manager/references/core/global-files-protocol.md'),
        buildProtocolDoc(['lib/ai-pm-protocol/field-contracts.js'])
    );
    writeFile(
        path.join(suiteRoot, 'skills/00-01-ai-project-manager/references/core/routing.md'),
        buildProtocolDoc(['lib/ai-pm-protocol/routing.js'])
    );

    writeFile(path.join(suiteRoot, structuredPath), buildStructuredFile(['skills/00-01-ai-project-manager/references/core/routing.md']));
    writeFile(
        path.join(suiteRoot, 'lib/ai-pm-protocol/bootstrap.js'),
        buildStructuredFile(['skills/00-01-ai-project-manager/SKILL.md'])
    );
    writeFile(
        path.join(suiteRoot, 'lib/ai-pm-protocol/field-contracts.js'),
        buildStructuredFile(['skills/00-01-ai-project-manager/references/core/global-files-protocol.md'])
    );
    writeFile(
        path.join(suiteRoot, 'lib/ai-pm-protocol/routing.js'),
        buildStructuredFile(['skills/00-01-ai-project-manager/references/core/routing.md'])
    );

    const result = checkProtocolAlignment({ suiteRoot });

    assert.ok(result.summary.errors > 0);
    assert.ok(result.issues.some((item) => item.code === 'missing_reverse_link'));
});

test('check-protocol-alignment degrades safely when suite root is not in a git repo', () => {
    const suiteRoot = makeTempDir('pm-suite-no-git-');
    const docPath = 'skills/00-01-ai-project-manager/references/core/runtime.md';
    const skillPath = 'skills/00-01-ai-project-manager/SKILL.md';
    const protocolPath = 'skills/00-01-ai-project-manager/references/core/global-files-protocol.md';
    const routingPath = 'skills/00-01-ai-project-manager/references/core/routing.md';

    writeFile(path.join(suiteRoot, docPath), buildProtocolDoc(['lib/ai-pm-protocol/stages.js']));
    writeFile(path.join(suiteRoot, skillPath), buildProtocolDoc(['lib/ai-pm-protocol/bootstrap.js']));
    writeFile(path.join(suiteRoot, protocolPath), buildProtocolDoc(['lib/ai-pm-protocol/field-contracts.js']));
    writeFile(path.join(suiteRoot, routingPath), buildProtocolDoc(['lib/ai-pm-protocol/routing.js']));

    writeFile(path.join(suiteRoot, 'lib/ai-pm-protocol/stages.js'), buildStructuredFile([docPath]));
    writeFile(path.join(suiteRoot, 'lib/ai-pm-protocol/bootstrap.js'), buildStructuredFile([skillPath]));
    writeFile(path.join(suiteRoot, 'lib/ai-pm-protocol/field-contracts.js'), buildStructuredFile([protocolPath]));
    writeFile(path.join(suiteRoot, 'lib/ai-pm-protocol/routing.js'), buildStructuredFile([routingPath]));

    const result = checkProtocolAlignment({ suiteRoot });

    assert.equal(result.summary.errors, 0);
    assert.equal(result.changeImpact.source, 'none');
    assert.deepEqual(result.changeImpact.changedFiles, []);
});

test('check-protocol-alignment reports impacted files for changed startup interview sources', () => {
    const result = checkProtocolAlignment({
        suiteRoot: CURRENT_SUITE_ROOT,
        changedFiles: ['skills/00-01-ai-project-manager/references/core/runtime.md']
    });

    assert.ok(result.changeImpact.impactedFamilies.some((item) => item.familyId === 'startupInterview'));
    assert.ok(
        result.changeImpact.recommendedReviewFiles.includes(
            'skills/00-01-ai-project-manager/assets/global-files/project-profile.md'
        )
    );
    assert.ok(
        result.changeImpact.recommendedReviewFiles.includes('lib/ai-pm-protocol/field-contracts.js')
    );
});

test('check-protocol-alignment matches ai-project-manager SKILL.md changes to an impact family', () => {
    const result = checkProtocolAlignment({
        suiteRoot: CURRENT_SUITE_ROOT,
        changedFiles: ['skills/00-01-ai-project-manager/SKILL.md']
    });

    assert.ok(result.changeImpact.impactedFamilies.some((item) => item.familyId === 'entryIdentity'));
    assert.equal(result.changeImpact.unmatchedChangedFiles.includes('skills/00-01-ai-project-manager/SKILL.md'), false);
    assert.ok(
        result.changeImpact.recommendedReviewFiles.includes('skills/00-01-ai-project-manager/references/core/runtime.md')
    );
});
