#!/usr/bin/env node

import process from 'process';
import fs from 'fs';
import {
    buildAdvanceCheck,
    buildNewLedger,
    DELIVERY_PHASE,
    findBrd,
    findLedger,
    getLedgerPath,
    getScreenshotsDir,
    nowTimestamp,
    parseGapFiles,
    parsePhase,
    readLedger,
    resolveHostDir,
    writeLedger
} from './page-ledger-io.mjs';

function parseArgs(argv) {
    const [subcommand, ...rest] = argv;
    const flags = {};

    for (let i = 0; i < rest.length; i++) {
        const current = rest[i];
        if (!current.startsWith('--')) {
            continue;
        }
        flags[current.slice(2)] = rest[i + 1] ?? null;
        i++;
    }

    return { subcommand, flags };
}

function ok(payload) {
    process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
}

function fail(error, message, extra = {}) {
    process.stderr.write(`${JSON.stringify({
        success: false,
        error,
        message,
        ...extra
    }, null, 2)}\n`);
    process.exit(1);
}

function requireLedger(hostDir) {
    const ledgerPath = findLedger(hostDir);
    if (!ledgerPath) {
        fail('ledger_not_found', `no page ledger found under ${resolveHostDir(hostDir)}`);
    }
    return { ledgerPath, ledger: readLedger(ledgerPath) };
}

function cmdBoot(flags) {
    const hostDir = resolveHostDir(flags['host-dir']);
    const existingLedgerPath = findLedger(hostDir);

    if (existingLedgerPath) {
        const ledger = readLedger(existingLedgerPath);
        ok({
            success: true,
            action: 'resumed',
            ledgerPath: existingLedgerPath,
            brdFile: ledger.brdFile,
            phase: ledger.phase,
            loopRound: ledger.loopRound,
            screenshotAsked: ledger.screenshotAsked
        });
        return;
    }

    const brdFile = findBrd(hostDir);
    if (!brdFile) {
        fail('brd_not_found', 'failed to locate BRD file under docs/brd or host root');
    }

    const ledger = buildNewLedger(hostDir, brdFile);
    const ledgerPath = getLedgerPath(hostDir, ledger.slug);

    fs.mkdirSync(getScreenshotsDir(hostDir), { recursive: true });
    writeLedger(ledgerPath, ledger);

    ok({
        success: true,
        action: 'created',
        ledgerPath,
        brdFile: ledger.brdFile,
        phase: ledger.phase,
        loopRound: ledger.loopRound,
        screenshotAsked: ledger.screenshotAsked
    });
}

function cmdMarkAsked(flags) {
    const hostDir = resolveHostDir(flags['host-dir']);
    const field = flags['field'];

    if (field !== 'screenshot') {
        fail('unknown_field', `unsupported field for mark-asked: ${field ?? 'null'}`);
    }

    const { ledgerPath, ledger } = requireLedger(hostDir);
    ledger.screenshotAsked = true;
    ledger.updatedAt = nowTimestamp();
    writeLedger(ledgerPath, ledger);

    ok({
        success: true,
        action: 'mark-asked',
        ledgerPath,
        screenshotAsked: ledger.screenshotAsked
    });
}

function cmdAdvance(flags) {
    const hostDir = resolveHostDir(flags['host-dir']);
    const toPhase = parsePhase(flags['to']);
    const { ledgerPath, ledger } = requireLedger(hostDir);
    const check = buildAdvanceCheck(ledger, hostDir, toPhase);

    if (!check.canAdvance) {
        fail(check.error, check.reason, {
            from: ledger.phase,
            to: toPhase
        });
    }

    ledger.phase = toPhase;
    ledger.updatedAt = nowTimestamp();
    writeLedger(ledgerPath, ledger);

    ok({
        success: true,
        action: 'advance',
        ledgerPath,
        phase: ledger.phase,
        loopRound: ledger.loopRound
    });
}

function cmdStartLoop(flags) {
    const hostDir = resolveHostDir(flags['host-dir']);
    const { ledgerPath, ledger } = requireLedger(hostDir);

    if (ledger.phase !== DELIVERY_PHASE) {
        fail(
            'invalid_loop_start',
            `loop can only start from delivered phase ${DELIVERY_PHASE}`,
            {
                phase: ledger.phase
            }
        );
    }

    const gapFiles = parseGapFiles(flags['gap-files']);
    const missingGapFiles = gapFiles.filter((file) => !fs.existsSync(file));
    if (missingGapFiles.length > 0) {
        fail('gap_file_not_found', `gap files not found: ${missingGapFiles.join(', ')}`);
    }

    ledger.loopRound += 1;
    ledger.gapFilesConsumed = gapFiles;
    ledger.phase = 1;
    ledger.updatedAt = nowTimestamp();
    writeLedger(ledgerPath, ledger);

    ok({
        success: true,
        action: 'start-loop',
        ledgerPath,
        phase: ledger.phase,
        loopRound: ledger.loopRound,
        gapFilesConsumed: ledger.gapFilesConsumed
    });
}

function main() {
    const { subcommand, flags } = parseArgs(process.argv.slice(2));

    try {
        switch (subcommand) {
            case 'boot':
                cmdBoot(flags);
                return;
            case 'mark-asked':
                cmdMarkAsked(flags);
                return;
            case 'advance':
                cmdAdvance(flags);
                return;
            case 'start-loop':
                cmdStartLoop(flags);
                return;
            default:
                fail('unknown_subcommand', `unsupported subcommand: ${subcommand ?? 'null'}`);
        }
    } catch (error) {
        fail('unexpected_error', error.message);
    }
}

main();
