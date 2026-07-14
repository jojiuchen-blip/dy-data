import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const TEST_FILE_PATH = fileURLToPath(import.meta.url);
const SUITE_ROOT = path.resolve(path.dirname(TEST_FILE_PATH), '..');
const PAGE_DESIGNER_SCRIPTS_DIR = path.join(SUITE_ROOT, 'skills', '03-02-page-designer', 'scripts');

function makeTempDir(prefix) {
    return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function writeFile(targetPath, content) {
    fs.mkdirSync(path.dirname(targetPath), { recursive: true });
    fs.writeFileSync(targetPath, content, 'utf8');
}

function readJson(filePath) {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function runCli(scriptName, ...args) {
    const scriptPath = path.join(PAGE_DESIGNER_SCRIPTS_DIR, scriptName);
    const stdout = execFileSync('node', [scriptPath, ...args], {
        cwd: SUITE_ROOT,
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'pipe']
    });
    return JSON.parse(stdout);
}

function runCliExpectFailure(scriptName, ...args) {
    const scriptPath = path.join(PAGE_DESIGNER_SCRIPTS_DIR, scriptName);
    try {
        execFileSync('node', [scriptPath, ...args], {
            cwd: SUITE_ROOT,
            encoding: 'utf8',
            stdio: ['ignore', 'pipe', 'pipe']
        });
        assert.fail(`expected ${scriptName} to fail`);
    } catch (error) {
        if (error.stdout) {
            try {
                return JSON.parse(error.stdout);
            } catch {}
        }
        if (error.stderr) {
            try {
                return JSON.parse(error.stderr);
            } catch {}
        }
        throw error;
    }
}

function createHostWithBrd({ withDocsBrd = true } = {}) {
    const hostRoot = makeTempDir('page-ledger-');
    const slug = 'demo';
    const brdFilename = `BRD-${slug}-20260408-1000.md`;
    const brdPath = withDocsBrd
        ? path.join(hostRoot, 'docs', 'brd', brdFilename)
        : path.join(hostRoot, brdFilename);
    writeFile(brdPath, `# BRD: demo\n`);
    return { hostRoot, brdPath, slug };
}

function writeDelivery(hostRoot, slug) {
    writeFile(
        path.join(hostRoot, 'src', 'frontend', 'page-preview', `page-delivery-${slug}.md`),
        '# Delivery\n\n- 文件路径：/abs/path/demo\n'
    );
}

test('status returns exists false when ledger is absent', () => {
    const hostRoot = makeTempDir('page-ledger-empty-');
    const result = runCli('page-ledger-query.mjs', 'status', '--host-dir', hostRoot);
    assert.equal(result.exists, false);
});

test('boot creates ledger when BRD exists in docs/brd', () => {
    const { hostRoot, slug } = createHostWithBrd();

    const result = runCli('page-ledger-mutate.mjs', 'boot', '--host-dir', hostRoot);
    assert.equal(result.success, true);
    assert.equal(result.action, 'created');
    assert.equal(result.phase, 0);
    assert.equal(result.loopRound, 0);
    assert.equal(result.screenshotAsked, false);

    const ledgerPath = path.join(hostRoot, 'src', 'frontend', 'page-preview', `page-ledger-${slug}.json`);
    const screenshotDir = path.join(hostRoot, 'src', 'frontend', 'page-preview', 'screenshots');
    assert.ok(fs.existsSync(ledgerPath));
    assert.ok(fs.existsSync(screenshotDir));

    const ledger = readJson(ledgerPath);
    assert.equal(ledger.slug, slug);
    assert.equal(ledger.schemaVersion, '2.0.0');
    assert.equal(ledger.phase, 0);
    assert.deepEqual(ledger.gapFilesConsumed, []);
});

test('boot resumes existing ledger without creating new', () => {
    const { hostRoot } = createHostWithBrd();
    const first = runCli('page-ledger-mutate.mjs', 'boot', '--host-dir', hostRoot);
    const second = runCli('page-ledger-mutate.mjs', 'boot', '--host-dir', hostRoot);
    assert.equal(first.action, 'created');
    assert.equal(second.action, 'resumed');
    assert.equal(second.ledgerPath, first.ledgerPath);
});

test('advance to phase 1 requires screenshotAsked first', () => {
    const { hostRoot } = createHostWithBrd();
    runCli('page-ledger-mutate.mjs', 'boot', '--host-dir', hostRoot);

    const failure = runCliExpectFailure('page-ledger-mutate.mjs', 'advance', '--host-dir', hostRoot, '--to', '1');
    assert.equal(failure.success, false);
    assert.equal(failure.error, 'precondition_failed');
    assert.match(failure.message, /screenshot/i);

    runCli('page-ledger-mutate.mjs', 'mark-asked', '--host-dir', hostRoot, '--field', 'screenshot');
    const result = runCli('page-ledger-mutate.mjs', 'advance', '--host-dir', hostRoot, '--to', '1');
    assert.equal(result.success, true);
    assert.equal(result.phase, 1);
});

test('advance follows linear phase graph 0 -> 1 -> 3 -> 4', () => {
    const { hostRoot, slug } = createHostWithBrd();
    runCli('page-ledger-mutate.mjs', 'boot', '--host-dir', hostRoot);
    runCli('page-ledger-mutate.mjs', 'mark-asked', '--host-dir', hostRoot, '--field', 'screenshot');
    runCli('page-ledger-mutate.mjs', 'advance', '--host-dir', hostRoot, '--to', '1');
    runCli('page-ledger-mutate.mjs', 'advance', '--host-dir', hostRoot, '--to', '3');

    // advance to 4 requires delivery file
    const missingDelivery = runCliExpectFailure('page-ledger-mutate.mjs', 'advance', '--host-dir', hostRoot, '--to', '4');
    assert.equal(missingDelivery.error, 'precondition_failed');
    assert.match(missingDelivery.message, /delivery/i);

    writeDelivery(hostRoot, slug);
    const result = runCli('page-ledger-mutate.mjs', 'advance', '--host-dir', hostRoot, '--to', '4');
    assert.equal(result.phase, 4);
});

test('advance rejects invalid transitions like 0 -> 3', () => {
    const { hostRoot } = createHostWithBrd();
    runCli('page-ledger-mutate.mjs', 'boot', '--host-dir', hostRoot);
    runCli('page-ledger-mutate.mjs', 'mark-asked', '--host-dir', hostRoot, '--field', 'screenshot');

    const failure = runCliExpectFailure('page-ledger-mutate.mjs', 'advance', '--host-dir', hostRoot, '--to', '3');
    assert.equal(failure.error, 'invalid_transition');
});

test('start-loop resets to phase 1 from delivered phase 4', () => {
    const { hostRoot, slug } = createHostWithBrd();
    runCli('page-ledger-mutate.mjs', 'boot', '--host-dir', hostRoot);
    runCli('page-ledger-mutate.mjs', 'mark-asked', '--host-dir', hostRoot, '--field', 'screenshot');
    runCli('page-ledger-mutate.mjs', 'advance', '--host-dir', hostRoot, '--to', '1');
    runCli('page-ledger-mutate.mjs', 'advance', '--host-dir', hostRoot, '--to', '3');
    writeDelivery(hostRoot, slug);
    runCli('page-ledger-mutate.mjs', 'advance', '--host-dir', hostRoot, '--to', '4');

    const gapFile = path.join(hostRoot, 'src', 'frontend', 'page-preview', `explainer-b-gap-${slug}.md`);
    writeFile(gapFile, '# gap\n');

    const result = runCli(
        'page-ledger-mutate.mjs',
        'start-loop',
        '--host-dir',
        hostRoot,
        '--gap-files',
        gapFile
    );
    assert.equal(result.success, true);
    assert.equal(result.phase, 1);
    assert.equal(result.loopRound, 1);
    assert.equal(result.gapFilesConsumed.length, 1);
});

test('start-loop rejects when phase is not the delivery phase', () => {
    const { hostRoot } = createHostWithBrd();
    runCli('page-ledger-mutate.mjs', 'boot', '--host-dir', hostRoot);
    runCli('page-ledger-mutate.mjs', 'mark-asked', '--host-dir', hostRoot, '--field', 'screenshot');
    runCli('page-ledger-mutate.mjs', 'advance', '--host-dir', hostRoot, '--to', '1');

    const failure = runCliExpectFailure('page-ledger-mutate.mjs', 'start-loop', '--host-dir', hostRoot);
    assert.equal(failure.error, 'invalid_loop_start');
});

test('boot fails when BRD is missing entirely', () => {
    const hostRoot = makeTempDir('page-ledger-no-brd-');
    const failure = runCliExpectFailure('page-ledger-mutate.mjs', 'boot', '--host-dir', hostRoot);
    assert.equal(failure.error, 'brd_not_found');
});
