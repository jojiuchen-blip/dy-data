#!/usr/bin/env node
/**
 * ledger-render.mjs — CLI for product output operations.
 *
 * Subcommands:
 *   chapters plan      --ledger <path>
 *   chapters finalize  --ledger <path> --include "1,2,3,6,8,11,12,13"
 *                      (--include lists TEMPLATE chapter numbers — valid: 1,2,3,4,6,8,9,10,11,12,13;
 *                       output renumbers the included chapters consecutively from 1)
 *   save-brd           --ledger <path> --content <path> --output-dir <dir>
 *   markdown           --ledger <path>
 */

import fs from 'fs';
import path from 'path';

import {
  readLedger,
  writeLedger,
  renderMarkdown,
  getChapterPlan,
  APPENDIX_DEPENDENCIES,
  CHAPTER_MATRIX,
} from './ledger-io.mjs';

// ─────────────────────────────────────────────
// Arg parser
// ─────────────────────────────────────────────

/**
 * Parse --key value pairs from an argv slice.
 * Supports: --foo bar  and  --foo=bar
 * @param {string[]} argv
 * @returns {Object}
 */
function parseArgs(argv) {
  const opts = {};
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg.startsWith('--')) {
      const eqIdx = arg.indexOf('=');
      if (eqIdx !== -1) {
        const key = arg.slice(2, eqIdx);
        opts[key] = arg.slice(eqIdx + 1);
      } else {
        const key = arg.slice(2);
        const next = argv[i + 1];
        if (next !== undefined && !next.startsWith('--')) {
          opts[key] = next;
          i++;
        } else {
          opts[key] = true;
        }
      }
    }
  }
  return opts;
}

// ─────────────────────────────────────────────
// Timestamp helpers
// ─────────────────────────────────────────────

/**
 * Current local time as "YYYYMMDD-HHMM" for BRD filename.
 * @returns {string}
 */
function nowFileTimestamp() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm   = String(d.getMonth() + 1).padStart(2, '0');
  const dd   = String(d.getDate()).padStart(2, '0');
  const hh   = String(d.getHours()).padStart(2, '0');
  const mi   = String(d.getMinutes()).padStart(2, '0');
  return `${yyyy}${mm}${dd}-${hh}${mi}`;
}

// ─────────────────────────────────────────────
// Subcommand: chapters plan
// ─────────────────────────────────────────────

function cmdChaptersPlan(opts) {
  const ledgerPath = opts['ledger'];
  if (!ledgerPath) throw new Error('--ledger is required');

  const data = readLedger(path.resolve(ledgerPath));
  const { project_type, has_pages } = data.header;

  const chapters = getChapterPlan(project_type, has_pages);
  console.log(JSON.stringify({ chapters }, null, 2));
}

// ─────────────────────────────────────────────
// Subcommand: chapters finalize
// ─────────────────────────────────────────────

function cmdChaptersFinalize(opts) {
  const ledgerPath = opts['ledger'];
  if (!ledgerPath) throw new Error('--ledger is required');

  const includeRaw = opts['include'];
  if (!includeRaw) throw new Error('--include is required');

  const absLedgerPath = path.resolve(ledgerPath);
  const data = readLedger(absLedgerPath);
  const { project_type, has_pages, slug } = data.header;

  // Parse included template numbers
  const includedTemplateNums = new Set(
    String(includeRaw).split(',').map((s) => Number(s.trim())).filter((n) => !isNaN(n))
  );

  // Get chapter plan from ledger context
  const plan = getChapterPlan(project_type, has_pages);

  // Build final_chapters: only chapters in the included set
  let finalNumber = 0;
  const final_chapters = [];
  const templateToFinalMap = {}; // template_number → final_number

  for (const ch of plan) {
    if (includedTemplateNums.has(ch.template_number)) {
      finalNumber++;
      final_chapters.push({
        final_number:    finalNumber,
        template_number: ch.template_number,
        title:           ch.title,
        status:          ch.status,
      });
      templateToFinalMap[ch.template_number] = finalNumber;
    }
  }

  // Build appendix
  const appendix_rows = [];
  const appendix_removed_rows = [];

  for (const dep of APPENDIX_DEPENDENCIES) {
    let requiredMissingCount = 0;
    let requiredTotalCount = 0;
    const cleanFields = [];

    for (const field of dep.fields) {
      if (!field.optional) requiredTotalCount++;

      if (!field.template_chapters || field.template_chapters.length === 0) {
        cleanFields.push({
          semantic_name: field.semantic_name,
          optional:      field.optional,
          status:        'present',
          chapter_ref:   '头部',
        });
        continue;
      }

      const matchingTemplateNum = field.template_chapters.find((n) =>
        includedTemplateNums.has(n)
      );

      if (matchingTemplateNum !== undefined) {
        const finalNum = templateToFinalMap[matchingTemplateNum];
        cleanFields.push({
          semantic_name: field.semantic_name,
          optional:      field.optional,
          status:        'present',
          chapter_ref:   `§${finalNum}`,
        });
      } else if (field.optional) {
        cleanFields.push({
          semantic_name: field.semantic_name,
          optional:      true,
          status:        'not_applicable',
          note:          '本次不适用',
        });
      } else {
        // required and not present → missing
        requiredMissingCount++;
        // Don't include in cleanFields (filtered out per spec)
      }
    }

    // Row removal: if ALL non-optional fields are 'missing' → put in removed
    if (requiredTotalCount > 0 && requiredMissingCount === requiredTotalCount) {
      appendix_removed_rows.push({
        downstream_skill: dep.downstream_skill,
        reason:           'all required fields missing',
      });
    } else {
      appendix_rows.push({
        downstream_skill: dep.downstream_skill,
        fields:           cleanFields,
      });
    }
  }

  // Build heading outline
  const heading_outline = final_chapters
    .map((ch) => `## ${ch.final_number}. ${ch.title}`)
    .join('\n');

  // Build chapter_plan result
  const chapter_plan = {
    final_chapters,
    appendix: {
      rows:         appendix_rows,
      removed_rows: appendix_removed_rows,
    },
    heading_outline,
  };

  // Persist to ledger
  data.chapter_plan = chapter_plan;
  writeLedger(absLedgerPath, data, slug);

  console.log(JSON.stringify(chapter_plan, null, 2));
}

// ─────────────────────────────────────────────
// Subcommand: save-brd
// ─────────────────────────────────────────────

function cmdSaveBrd(opts) {
  const ledgerPath = opts['ledger'];
  if (!ledgerPath) throw new Error('--ledger is required');

  const contentPath = opts['content'];
  if (!contentPath) throw new Error('--content is required');

  const outputDir = opts['output-dir'];
  if (!outputDir) throw new Error('--output-dir is required');

  const absLedgerPath = path.resolve(ledgerPath);
  const absOutputDir  = path.resolve(outputDir);
  const data = readLedger(absLedgerPath);
  const { header } = data;

  // Phase guard
  if (header.current_phase !== 'F') {
    throw new Error(`Phase guard failed: current phase is '${header.current_phase}', expected 'F'`);
  }

  // chapter_plan check
  if (!data.chapter_plan) {
    throw new Error('Run chapters finalize first (chapter_plan is null)');
  }

  const { slug } = header;

  // Idempotent recovery
  if (header.pending_brd_filename) {
    const pendingPath = path.join(absOutputDir, header.pending_brd_filename);
    if (fs.existsSync(pendingPath)) {
      // File already written — just mark DONE
      header.brd_filename = header.pending_brd_filename;
      header.pending_brd_filename = null;
      header.current_phase = 'DONE';
      writeLedger(absLedgerPath, data, slug);
      console.log(JSON.stringify({ recovered: true, path: pendingPath }));
      return;
    }
    // File not found — reuse the pending filename
  }

  // Read BRD content
  const absContentPath = path.resolve(contentPath);
  const brdContent = fs.readFileSync(absContentPath, 'utf8');

  // ── Structure validation ──────────────────────

  const errors = [];

  // Extract ## headings
  const headingLines = brdContent
    .split('\n')
    .filter((line) => /^## /.test(line))
    .map((line) => line.trim());

  // Separate numbered chapters from appendix headings
  const numberedHeadings = headingLines.filter((h) => /^## \d+\./.test(h));
  const appendixHeadings = headingLines.filter((h) => h.includes('附录'));

  // Build a map: final_number → heading text
  const headingByNum = {};
  for (const h of numberedHeadings) {
    const m = h.match(/^## (\d+)\./);
    if (m) headingByNum[Number(m[1])] = h;
  }

  const finalChapters = data.chapter_plan.final_chapters;

  // Chapter completeness: each final_chapter must have a matching heading
  for (const ch of finalChapters) {
    if (!headingByNum[ch.final_number]) {
      errors.push(`Missing heading for chapter ${ch.final_number}: "${ch.title}"`);
    }
  }

  // Extra numbered headings not in final_chapters
  const expectedNums = new Set(finalChapters.map((ch) => ch.final_number));
  for (const num of Object.keys(headingByNum).map(Number)) {
    if (!expectedNums.has(num)) {
      errors.push(`Extra numbered heading found: ${headingByNum[num]}`);
    }
  }

  // Sequential numbering: actual numbers must match final_chapters sequence exactly
  const actualNums = numberedHeadings
    .map((h) => { const m = h.match(/^## (\d+)\./); return m ? Number(m[1]) : null; })
    .filter((n) => n !== null)
    .sort((a, b) => a - b);
  const expectedNumsSorted = finalChapters.map((ch) => ch.final_number);

  if (JSON.stringify(actualNums) !== JSON.stringify(expectedNumsSorted)) {
    errors.push(
      `Sequential numbering mismatch. Expected: [${expectedNumsSorted.join(',')}], got: [${actualNums.join(',')}]`
    );
  }

  // Appendix must exist
  if (appendixHeadings.length === 0) {
    errors.push('Missing appendix (no heading containing "附录")');
  }

  // (v2.0.0: legacy architecture check removed.)

  if (errors.length > 0) {
    console.log(JSON.stringify({ success: false, error: 'structure_validation', errors }));
    return;
  }

  // ── Two-phase commit ───────────────────────────

  // Determine filename
  let brdFilename;
  if (header.pending_brd_filename) {
    // Reuse existing pending filename (file not found case handled above)
    brdFilename = header.pending_brd_filename;
  } else {
    brdFilename = `BRD-${slug}-${nowFileTimestamp()}.md`;
  }

  const brdAbsPath = path.join(absOutputDir, brdFilename);

  // Phase 1: Record pending filename, write ledger (phase still F)
  header.pending_brd_filename = brdFilename;
  writeLedger(absLedgerPath, data, slug);

  // Phase 2: Write BRD file, update ledger to DONE
  fs.mkdirSync(absOutputDir, { recursive: true });
  fs.writeFileSync(brdAbsPath, brdContent, 'utf8');

  header.brd_filename = brdFilename;
  header.pending_brd_filename = null;
  header.current_phase = 'DONE';
  writeLedger(absLedgerPath, data, slug);

  // Delete draft file (best-effort)
  try {
    fs.unlinkSync(absContentPath);
  } catch {
    // best-effort
  }

  console.log(JSON.stringify({ success: true, action: 'save-brd', path: brdAbsPath }));
}

// ─────────────────────────────────────────────
// Subcommand: markdown
// ─────────────────────────────────────────────

function cmdMarkdown(opts) {
  const ledgerPath = opts['ledger'];
  if (!ledgerPath) throw new Error('--ledger is required');

  const absLedgerPath = path.resolve(ledgerPath);
  const data = readLedger(absLedgerPath);
  const { slug } = data.header;

  const mdContent = renderMarkdown(data);
  const dir = path.dirname(absLedgerPath);
  const mdPath = path.join(dir, `brd-ledger-${slug}.md`);
  fs.writeFileSync(mdPath, mdContent, 'utf8');

  console.log(JSON.stringify({ success: true, action: 'markdown', path: mdPath }));
}

// ─────────────────────────────────────────────
// Main dispatcher
// ─────────────────────────────────────────────

const args = process.argv.slice(2);

try {
  if (args[0] === 'chapters') {
    const sub = args[1]; // 'plan' or 'finalize'
    const opts = parseArgs(args.slice(2));

    if (sub === 'plan') {
      cmdChaptersPlan(opts);
    } else if (sub === 'finalize') {
      cmdChaptersFinalize(opts);
    } else {
      throw new Error(`Unknown chapters subcommand: "${sub}". Use 'plan' or 'finalize'.`);
    }
  } else if (args[0] === 'save-brd') {
    const opts = parseArgs(args.slice(1));
    cmdSaveBrd(opts);
  } else if (args[0] === 'markdown') {
    const opts = parseArgs(args.slice(1));
    cmdMarkdown(opts);
  } else {
    const cmd = args[0] ?? '(none)';
    throw new Error(
      `Unknown command: "${cmd}". Available: chapters plan, chapters finalize, save-brd, markdown`
    );
  }
} catch (err) {
  console.error(`[ledger-render] Error: ${err.message}`);
  process.exit(1);
}
