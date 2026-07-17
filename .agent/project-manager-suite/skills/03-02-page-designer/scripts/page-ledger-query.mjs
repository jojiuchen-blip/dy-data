#!/usr/bin/env node

import process from 'process';
import {
    buildAdvanceCheck,
    findLedger,
    parsePhase,
    readLedger,
    resolveHostDir
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

function fail(error, message) {
    process.stderr.write(`${JSON.stringify({ success: false, error, message }, null, 2)}\n`);
    process.exit(1);
}

function readLedgerOrNull(hostDir) {
    const ledgerPath = findLedger(hostDir);
    if (!ledgerPath) {
        return null;
    }

    return {
        ledgerPath,
        ledger: readLedger(ledgerPath)
    };
}

function cmdStatus(flags) {
    const hostDir = resolveHostDir(flags['host-dir']);
    const found = readLedgerOrNull(hostDir);

    if (!found) {
        ok({ exists: false });
        return;
    }

    const { ledgerPath, ledger } = found;
    ok({
        exists: true,
        phase: ledger.phase,
        loopRound: ledger.loopRound,
        screenshotAsked: ledger.screenshotAsked,
        ledgerPath
    });
}

function cmdCanAdvance(flags) {
    const hostDir = resolveHostDir(flags['host-dir']);
    const found = readLedgerOrNull(hostDir);
    if (!found) {
        fail('ledger_not_found', `no page ledger found under ${hostDir}`);
    }

    const toPhase = parsePhase(flags['to']);
    const result = buildAdvanceCheck(found.ledger, hostDir, toPhase);

    ok({
        canAdvance: result.canAdvance,
        reason: result.reason
    });
}

function main() {
    const { subcommand, flags } = parseArgs(process.argv.slice(2));

    try {
        switch (subcommand) {
            case 'status':
                cmdStatus(flags);
                return;
            case 'can-advance':
                cmdCanAdvance(flags);
                return;
            default:
                fail('unknown_subcommand', `unsupported subcommand: ${subcommand ?? 'null'}`);
        }
    } catch (error) {
        fail('unexpected_error', error.message);
    }
}

main();
