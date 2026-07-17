#!/usr/bin/env node
/**
 * ledger-query.mjs — Read-only CLI for BRD ledger queries.
 *
 * Subcommands:
 *   status           --ledger <path>
 *   gaps             --ledger <path>
 *   progress         --ledger <path>
 *   summary          --ledger <path>
 *   lint             --ledger <path>
 *   alignment-check  --refs-dir <path>
 *
 * All output is JSON to stdout. Never writes to the ledger.
 */

import fs from 'fs';
import path from 'path';
import {
  readLedger,
  UNIVERSAL_P0,
  TYPE_SPECIFIC_P0,
  PAGE_FIELDS,
  CHAPTER_MATRIX,
  APPENDIX_DEPENDENCIES,
} from './ledger-io.mjs';

// ─────────────────────────────────────────────
// Arg parser
// ─────────────────────────────────────────────

/**
 * Parse process.argv into { subcommand, flags }.
 * flags is a plain object: { '--ledger': '/path/to/file', ... }
 */
function parseArgs() {
  const args = process.argv.slice(2);
  const subcommand = args[0] ?? null;
  const flags = {};
  for (let i = 1; i < args.length; i++) {
    const arg = args[i];
    if (arg.startsWith('--')) {
      const value = args[i + 1] ?? null;
      flags[arg] = value;
      if (value !== null) i++;
    }
  }
  return { subcommand, flags };
}

function requireFlag(flags, name) {
  const v = flags[name];
  if (!v) {
    process.stderr.write(`Error: missing required flag ${name}\n`);
    process.exit(1);
  }
  return v;
}

// ─────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────

function getLockedFields(ledger) {
  return (ledger.fields ?? []).filter((f) => f.status === 'locked');
}

function getOpenFields(ledger) {
  return (ledger.fields ?? []).filter((f) => f.status !== 'locked');
}

function countUnresolvedConflicts(ledger) {
  return (ledger.conflicts ?? []).filter((c) => c.status !== 'resolved').length;
}

// ─────────────────────────────────────────────
// Subcommand: status
// ─────────────────────────────────────────────

function cmdStatus(ledger) {
  const locked = getLockedFields(ledger);
  return {
    locked_fields: locked.map((f) => ({
      id: f.id,
      display_name: f.display_name,
      value: f.value,
      lock_round: f.lock_round,
    })),
  };
}

// ─────────────────────────────────────────────
// Subcommand: gaps
// ─────────────────────────────────────────────

function cmdGaps(ledger) {
  const open = getOpenFields(ledger);
  return {
    open_fields: open.map((f) => ({
      id: f.id,
      display_name: f.display_name,
      field_type: f.field_type,
    })),
  };
}

// ─────────────────────────────────────────────
// Subcommand: progress
// ─────────────────────────────────────────────

function cmdProgress(ledger) {
  const fields = ledger.fields ?? [];
  const totalFields = fields.length;
  const lockedCount = fields.filter((f) => f.status === 'locked').length;
  const openCount = totalFields - lockedCount;
  const rate = totalFields > 0 ? `${Math.round((lockedCount / totalFields) * 100)}%` : '0%';

  const header = ledger.header ?? {};
  const currentPhase = header.current_phase ?? null;
  const currentRound = header.current_round ?? 0;
  const d5State = header.d5_state ?? {
    last_result: null,
    last_triggered_at_round: null,
    fields_changed_since_last_d5: false,
  };

  const openFieldIds = fields.filter((f) => f.status !== 'locked').map((f) => f.id);
  const unresolvedConflicts = countUnresolvedConflicts(ledger);

  // should_trigger_d5 logic:
  // true IFF ALL of:
  //   1. current_phase === 'C'
  //   2. open_fields === 0
  //   3. unresolved_conflicts === 0
  //   4. EITHER: d5_state.last_result === null (never triggered)
  //      OR: d5_state.fields_changed_since_last_d5 === true
  // A previous pass stays valid only while no locked fields changed after that D.5 run.
  let shouldTriggerD5 = false;
  if (
    currentPhase === 'C' &&
    openCount === 0 &&
    unresolvedConflicts === 0
  ) {
    const { last_result, fields_changed_since_last_d5 } = d5State;
    if (last_result === null) {
      shouldTriggerD5 = true;
    } else if (fields_changed_since_last_d5 === true) {
      shouldTriggerD5 = true;
    }
  }

  return {
    total_fields: totalFields,
    locked_fields: lockedCount,
    open_fields: openCount,
    rate,
    current_phase: currentPhase,
    current_round: currentRound,
    open_field_ids: openFieldIds,
    unresolved_conflicts: unresolvedConflicts,
    should_trigger_d5: shouldTriggerD5,
    d5_state: {
      last_result: d5State.last_result ?? null,
      last_triggered_at_round: d5State.last_triggered_at_round ?? null,
      fields_changed_since_last_d5: d5State.fields_changed_since_last_d5 ?? false,
    },
  };
}

// ─────────────────────────────────────────────
// Subcommand: summary
// ─────────────────────────────────────────────

function cmdSummary(ledger) {
  const locked = getLockedFields(ledger);
  return {
    fields: locked.map((f) => ({
      id: f.id,
      display_name: f.display_name,
      value: f.value,
      methodology: f.methodology,
    })),
  };
}

// ─────────────────────────────────────────────
// Subcommand: lint
// ─────────────────────────────────────────────

function cmdLint(ledger) {
  const pass = [];
  const fail = [];
  const needs_ai_review = [];
  const details = {};

  const header = ledger.header ?? {};
  const fields = ledger.fields ?? [];
  const gates = ledger.gates ?? [];
  const hasPages = Boolean(header.has_pages);

  // Helper: check if a gate is applicable from the stored gates array
  function isGateApplicable(gateId) {
    const gate = gates.find((g) => g.id === gateId);
    return gate ? gate.applicable !== false : true;
  }

  // ── Gate 1: field_completeness ──
  // Script check: all fields locked
  {
    const openFields = getOpenFields(ledger);
    if (openFields.length === 0) {
      pass.push('field_completeness');
    } else {
      fail.push('field_completeness');
      details.field_completeness = {
        reason: `${openFields.length} 个字段未锁定: ${openFields.map((f) => f.id).join(', ')}`,
      };
    }
  }

  // ── Gate 2: consistency ──
  // Script check: unresolved conflicts === 0
  {
    const unresolved = countUnresolvedConflicts(ledger);
    if (unresolved === 0) {
      pass.push('consistency');
    } else {
      fail.push('consistency');
      details.consistency = { reason: `存在 ${unresolved} 个未解决冲突` };
    }
  }

  // ── Gate 3: measurement ──
  // Script check: structured fields — all sub-fields non-empty; text fields — non-empty
  // AI reviews: quality
  {
    const lockedFields = getLockedFields(ledger);
    const failedMeasurement = [];

    for (const f of lockedFields) {
      if (f.value_type === 'structured') {
        // value should be an object; check all sub-fields
        const val = f.value;
        const schema = f.value_schema ?? [];
        if (!val || typeof val !== 'object') {
          failedMeasurement.push(f.id);
        } else {
          const missingKeys = schema.filter(
            (key) => val[key] === null || val[key] === undefined || val[key] === ''
          );
          if (missingKeys.length > 0) {
            failedMeasurement.push(f.id);
          }
        }
      } else {
        // text field: non-empty
        const val = f.value;
        if (val === null || val === undefined || val === '') {
          failedMeasurement.push(f.id);
        }
      }
    }

    if (failedMeasurement.length === 0) {
      needs_ai_review.push('measurement');
    } else {
      fail.push('measurement');
      details.measurement = {
        reason: `字段值为空或结构不完整: ${failedMeasurement.join(', ')}`,
      };
      needs_ai_review.push('measurement');
    }
  }

  // ── Gate 5: scope ──
  // Script check: scope_definition field locked
  {
    const scopeField = fields.find((f) => f.id === 'scope_definition');
    if (scopeField && scopeField.status === 'locked') {
      pass.push('scope');
    } else {
      fail.push('scope');
      details.scope = { reason: 'scope_definition 字段未锁定' };
    }
  }

  // ── Gate 6: methodology ──
  // Script check: all decision-type locked fields have non-empty methodology
  // AI reviews: quality
  {
    const decisionLockedFields = getLockedFields(ledger).filter(
      (f) => f.field_type === 'decision'
    );
    const missingMethodology = decisionLockedFields.filter(
      (f) => !f.methodology || f.methodology.trim() === ''
    );

    if (missingMethodology.length === 0) {
      needs_ai_review.push('methodology');
    } else {
      fail.push('methodology');
      details.methodology = {
        reason: `字段 ${missingMethodology.map((f) => f.id).join(', ')} 的 methodology 列为空`,
      };
      needs_ai_review.push('methodology');
    }
  }

  // ── Gate 7: role ──
  // Script check: stakeholder_roles AND core_pain_points both locked
  // AI reviews: quality
  {
    const roleField = fields.find((f) => f.id === 'stakeholder_roles');
    const painField = fields.find((f) => f.id === 'core_pain_points');
    const bothLocked =
      roleField && roleField.status === 'locked' &&
      painField && painField.status === 'locked';

    if (bothLocked) {
      needs_ai_review.push('role');
    } else {
      fail.push('role');
      const missing = [];
      if (!roleField || roleField.status !== 'locked') missing.push('stakeholder_roles');
      if (!painField || painField.status !== 'locked') missing.push('core_pain_points');
      details.role = { reason: `字段 ${missing.join(', ')} 未锁定` };
      needs_ai_review.push('role');
    }
  }

  // ── Gate 8: page ──
  // Script check: all page_ fields locked (if has_pages)
  {
    const applicable = hasPages;
    if (!applicable) {
      // Auto-pass: no pages, gate not applicable
      pass.push('page');
    } else {
      const pageFields = fields.filter((f) => f.id.startsWith('page_'));
      const unlocked = pageFields.filter((f) => f.status !== 'locked');
      if (unlocked.length === 0) {
        pass.push('page');
      } else {
        fail.push('page');
        details.page = {
          reason: `页面字段未锁定: ${unlocked.map((f) => f.id).join(', ')}`,
        };
      }
    }
  }

  return { pass, fail, needs_ai_review, details };
}

// ─────────────────────────────────────────────
// Subcommand: alignment-check
// ─────────────────────────────────────────────

function cmdAlignmentCheck(refsDir) {
  const diffs = [];

  // ── Parse p0-fields.md ──
  const p0Path = path.join(refsDir, 'p0-fields.md');
  let p0Content = '';
  try {
    p0Content = fs.readFileSync(p0Path, 'utf8');
  } catch (err) {
    return { aligned: false, diffs: [`Cannot read ${p0Path}: ${err.message}`] };
  }

  // Count universal P0 items: numbered list items before any "## XX型追加 P0" section
  // We look for items like "1. " at the start of lines in the universal section
  const universalSection = p0Content.split(/^##\s+\S+型/m)[0] ?? p0Content;
  const universalCount = (universalSection.match(/^\d+\.\s/gm) ?? []).length;
  const expectedUniversal = UNIVERSAL_P0.length;
  if (universalCount !== expectedUniversal) {
    diffs.push(
      `UNIVERSAL_P0: registry=${expectedUniversal}, p0-fields.md counted=${universalCount}`
    );
  }

  // Count type-specific items per type
  // Section headers look like "## 创新型追加 P0" or "## 运营型追加P0" etc.
  // We match sections by type keyword
  const typeKeyMap = {
    innovation:     '创新',
    transformation: '改造',
    extension:      '扩展',
    integration:    '集成',
    operational:    '运营',
    compliance:     '合规',
  };

  for (const [typeKey, chineseKey] of Object.entries(typeKeyMap)) {
    // Find the section for this type
    const sectionRegex = new RegExp(
      `##\\s+${chineseKey}型[^\\n]*\\n([\\s\\S]*?)(?=\\n##\\s|$)`
    );
    const match = p0Content.match(sectionRegex);
    if (!match) {
      // Section not found — skip if type has 0 fields
      const expected = (TYPE_SPECIFIC_P0[typeKey] ?? []).length;
      if (expected > 0) {
        diffs.push(
          `TYPE_SPECIFIC_P0[${typeKey}]: registry=${expected}, p0-fields.md section not found`
        );
      }
      continue;
    }

    const sectionContent = match[1];
    const itemCount = (sectionContent.match(/^\d+\.\s/gm) ?? []).length;
    const expected = (TYPE_SPECIFIC_P0[typeKey] ?? []).length;
    if (itemCount !== expected) {
      diffs.push(
        `TYPE_SPECIFIC_P0[${typeKey}]: registry=${expected}, p0-fields.md counted=${itemCount}`
      );
    }
  }

  // ── Parse brd-template.md ──
  const tplPath = path.join(refsDir, 'brd-template.md');
  let tplContent = '';
  try {
    tplContent = fs.readFileSync(tplPath, 'utf8');
  } catch (err) {
    return { aligned: false, diffs: [`Cannot read ${tplPath}: ${err.message}`] };
  }

  // Count chapter rows in the cropping matrix table
  // Rows look like "| §1 ... |" — count data rows (those with §N in first column)
  const chapterMatrixRows = (tplContent.match(/^\|\s*§\d+/gm) ?? []).length;
  const expectedChapters = Object.keys(CHAPTER_MATRIX).length;
  if (chapterMatrixRows !== expectedChapters) {
    diffs.push(
      `CHAPTER_MATRIX: registry=${expectedChapters}, brd-template.md counted=${chapterMatrixRows}`
    );
  }

  // Count appendix downstream skill rows
  // Look for rows that match skill names in the appendix table
  // Each downstream skill appears as a row in the appendix table
  const appendixSection = tplContent.split(/##\s+附录/i)[1] ?? '';
  // Count rows that look like "| skill-name |" style entries
  // More robustly: count unique downstream skill names mentioned in the appendix table rows
  const skillNames = APPENDIX_DEPENDENCIES.map((d) => d.downstream_skill);
  let appendixMatchCount = 0;
  for (const skillName of skillNames) {
    if (appendixSection.includes(skillName)) {
      appendixMatchCount++;
    }
  }
  const expectedAppendix = APPENDIX_DEPENDENCIES.length;
  if (appendixMatchCount !== expectedAppendix) {
    diffs.push(
      `APPENDIX_DEPENDENCIES: registry=${expectedAppendix}, brd-template.md matched=${appendixMatchCount}`
    );
  }

  return {
    aligned: diffs.length === 0,
    diffs,
  };
}

// ─────────────────────────────────────────────
// Main dispatch
// ─────────────────────────────────────────────

function main() {
  const { subcommand, flags } = parseArgs();

  if (!subcommand) {
    process.stderr.write(
      'Usage: ledger-query.mjs <subcommand> [flags]\n' +
      'Subcommands: status, gaps, progress, summary, lint, alignment-check\n'
    );
    process.exit(1);
  }

  let result;

  if (subcommand === 'alignment-check') {
    const refsDir = requireFlag(flags, '--refs-dir');
    result = cmdAlignmentCheck(refsDir);
  } else {
    // All other subcommands need --ledger
    const ledgerPath = requireFlag(flags, '--ledger');
    let ledger;
    try {
      ledger = readLedger(ledgerPath);
    } catch (err) {
      process.stderr.write(`Error reading ledger: ${err.message}\n`);
      process.exit(1);
    }

    switch (subcommand) {
      case 'status':
        result = cmdStatus(ledger);
        break;
      case 'gaps':
        result = cmdGaps(ledger);
        break;
      case 'progress':
        result = cmdProgress(ledger);
        break;
      case 'summary':
        result = cmdSummary(ledger);
        break;
      case 'lint':
        result = cmdLint(ledger);
        break;
      default:
        process.stderr.write(`Unknown subcommand: ${subcommand}\n`);
        process.exit(1);
    }
  }

  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
}

main();
