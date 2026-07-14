import fs from 'fs';
import path from 'path';
import process from 'process';

export const SCHEMA_VERSION = '2.0.0';

// Linear phase graph for the single 4-Phase delivery flow.
// 0: boot → 1: phase 1 done → 3: phase 3 done → 4: delivery done.
// Phase 2 (design system generation) is implicit — covered by the 1 → 3 transition.
export const PHASE_GRAPH = {
    0: [1],
    1: [3],
    3: [4],
    4: []
};

export const DELIVERY_PHASE = 4;

export function nowTimestamp() {
    const current = new Date();
    const yyyy = current.getFullYear();
    const mm = String(current.getMonth() + 1).padStart(2, '0');
    const dd = String(current.getDate()).padStart(2, '0');
    const hh = String(current.getHours()).padStart(2, '0');
    const mi = String(current.getMinutes()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
}

export function resolveHostDir(hostDir) {
    if (!hostDir) {
        throw new Error('missing required flag --host-dir');
    }
    return path.resolve(hostDir);
}

export function getPagePreviewSearchDirs(hostDir) {
    const absoluteHostDir = resolveHostDir(hostDir);
    return [
        path.join(absoluteHostDir, 'src', 'frontend', 'page-preview'),
        path.join(absoluteHostDir, 'page-preview'),
        path.join(absoluteHostDir, '可操作页面')
    ];
}

export function getPagePreviewDir(hostDir) {
    return getPagePreviewSearchDirs(hostDir)[0];
}

export function getScreenshotsDir(hostDir) {
    return path.join(getPagePreviewDir(hostDir), 'screenshots');
}

// Search dirs are ordered by priority (new layout first, legacy fallbacks after).
// Ledgers in several dirs at once: take the highest-priority dir and print a notice
// to stderr, so legacy projects mid-migration keep working instead of hard-failing.
// Multiple ledgers inside one dir are still ambiguous: fail and list the candidates.
export function findLedger(hostDir) {
    const dirGroups = getPagePreviewSearchDirs(hostDir)
        .filter((previewDir) => fs.existsSync(previewDir))
        .map((previewDir) =>
            fs.readdirSync(previewDir)
                .filter((name) => /^page-ledger-.*\.json$/.test(name))
                .sort()
                .map((name) => path.join(previewDir, name))
        )
        .filter((matches) => matches.length > 0);

    if (dirGroups.length === 0) {
        return null;
    }

    const [primary, ...ignoredGroups] = dirGroups;

    if (primary.length > 1) {
        throw new Error(`multiple page ledgers found in the same directory: ${primary.join(', ')}; keep exactly one ledger there`);
    }

    if (ignoredGroups.length > 0) {
        const ignored = ignoredGroups.flat().join(', ');
        process.stderr.write(`notice: page ledgers found in multiple page-preview directories; using ${primary[0]} (highest priority), ignoring: ${ignored}\n`);
    }

    return primary[0];
}

export function findBrd(hostDir) {
    const absoluteHostDir = resolveHostDir(hostDir);
    const docsBrdDir = path.join(absoluteHostDir, 'docs', 'brd');
    const docsMatches = listBrdFiles(docsBrdDir);
    if (docsMatches.length > 0) {
        return path.join(docsBrdDir, pickBrdFile(docsMatches, docsBrdDir));
    }

    const rootMatches = listBrdFiles(absoluteHostDir);
    if (rootMatches.length > 0) {
        return path.join(absoluteHostDir, pickBrdFile(rootMatches, absoluteHostDir));
    }

    return null;
}

function listBrdFiles(targetDir) {
    if (!fs.existsSync(targetDir)) {
        return [];
    }

    return fs.readdirSync(targetDir)
        .filter((name) => /^BRD-.*\.md$/.test(name))
        .sort();
}

// Same anti-conflict policy as findLedger: one slug with several timestamps is
// fine (take the newest by filename timestamp), but different slugs are ambiguous —
// fail and list the candidates so the user keeps a single project's BRD files.
function pickBrdFile(names, targetDir) {
    const slugs = new Set(names.map((name) => deriveSlugFromBrd(name)));

    if (slugs.size > 1) {
        const candidates = names.map((name) => path.join(targetDir, name)).join(', ');
        throw new Error(`multiple BRD slugs found under ${targetDir}: ${candidates}; keep only one project's BRD files before running page-designer`);
    }

    const timestampOf = (name) => name.match(/-(\d{8}-\d{4})\.md$/)?.[1] ?? '';
    return [...names].sort(
        (a, b) => timestampOf(a).localeCompare(timestampOf(b)) || a.localeCompare(b)
    ).at(-1);
}

export function deriveSlugFromBrd(brdPath) {
    const fileName = path.basename(brdPath);
    const timestampMatch = fileName.match(/^BRD-(.+)-\d{8}-\d{4}\.md$/);
    if (timestampMatch) {
        return timestampMatch[1];
    }

    const genericMatch = fileName.match(/^BRD-(.+)\.md$/);
    if (genericMatch) {
        return genericMatch[1];
    }

    throw new Error(`unable to derive slug from BRD filename: ${fileName}`);
}

export function getLedgerPath(hostDir, slug) {
    return path.join(getPagePreviewDir(hostDir), `page-ledger-${slug}.json`);
}

export function readLedger(filePath) {
    if (!filePath || !fs.existsSync(filePath)) {
        throw new Error(`ledger not found: ${filePath}`);
    }

    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

export function writeLedger(filePath, data) {
    const outputDir = path.dirname(filePath);
    fs.mkdirSync(outputDir, { recursive: true });

    const tempPath = `${filePath}.tmp-${process.pid}-${Date.now()}`;
    fs.writeFileSync(tempPath, `${JSON.stringify(data, null, 2)}\n`, 'utf8');
    fs.renameSync(tempPath, filePath);
}

export function isValidAdvance(from, to) {
    if (from === to) {
        return true;
    }

    return PHASE_GRAPH[from]?.includes(to) ?? false;
}

export function buildNewLedger(hostDir, brdFile) {
    const slug = deriveSlugFromBrd(brdFile);
    const timestamp = nowTimestamp();
    return {
        schemaVersion: SCHEMA_VERSION,
        slug,
        brdFile,
        screenshotAsked: false,
        screenshotDir: getScreenshotsDir(hostDir),
        phase: 0,
        loopRound: 0,
        gapFilesConsumed: [],
        createdAt: timestamp,
        updatedAt: timestamp
    };
}

export function getDeliveryFilePath(hostDir, slug) {
    return path.join(getPagePreviewDir(hostDir), `page-delivery-${slug}.md`);
}

export function findPagePreviewArtifact(hostDir, fileName) {
    for (const previewDir of getPagePreviewSearchDirs(hostDir)) {
        const candidate = path.join(previewDir, fileName);
        if (fs.existsSync(candidate)) {
            return candidate;
        }
    }

    return null;
}

export function parsePhase(value) {
    const parsed = Number(value);
    if (!Number.isInteger(parsed)) {
        throw new Error(`invalid phase: ${value}`);
    }
    return parsed;
}

export function buildAdvanceCheck(ledger, hostDir, toPhase) {
    if (ledger.phase === toPhase) {
        return { canAdvance: true, reason: 'already_at_target_phase', error: null };
    }

    if (toPhase === 1) {
        if (ledger.screenshotAsked !== true) {
            return { canAdvance: false, reason: 'screenshot has not been asked', error: 'precondition_failed' };
        }
    }

    if (!isValidAdvance(ledger.phase, toPhase)) {
        return {
            canAdvance: false,
            reason: `invalid transition from ${ledger.phase} to ${toPhase}`,
            error: 'invalid_transition'
        };
    }

    if (toPhase === DELIVERY_PHASE) {
        const deliveryFile =
            findPagePreviewArtifact(hostDir, `page-delivery-${ledger.slug}.md`) ??
            getDeliveryFilePath(hostDir, ledger.slug);
        if (!fs.existsSync(deliveryFile)) {
            return {
                canAdvance: false,
                reason: `delivery file is missing: ${deliveryFile}`,
                error: 'precondition_failed'
            };
        }
    }

    return { canAdvance: true, reason: 'ok', error: null };
}

export function parseGapFiles(raw) {
    if (!raw) {
        return [];
    }
    return raw.split(',')
        .map((item) => item.trim())
        .filter(Boolean)
        .map((item) => path.resolve(item));
}
