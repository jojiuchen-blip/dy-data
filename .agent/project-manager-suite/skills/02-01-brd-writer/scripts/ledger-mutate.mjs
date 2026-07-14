#!/usr/bin/env node
/**
 * ledger-mutate.mjs — CLI for all BRD ledger write operations.
 * Subcommands: init, lock, rollback, set-phase, add-conflict, resolve-conflict, update-gates
 *
 * All output goes to stdout as JSON. Errors go to stderr as JSON + exit(1).
 */

import process from 'process';
import fs from 'fs';
import path from 'path';
import {
  readLedger,
  writeLedger,
  createEmptyLedger,
  normalizeProjectType,
  isValidTransition,
  RULE_CONFLICTS,
  invalidateDerivedState,
} from './ledger-io.mjs';

// ─────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────

function parseArgs(args) {
  const opts = {};
  for (let i = 0; i < args.length; i++) {
    if (args[i].startsWith('--')) {
      const key = args[i].slice(2);
      const next = args[i + 1];
      if (next === undefined || next.startsWith('--')) {
        opts[key] = true; // bare flag, e.g. --force
      } else {
        opts[key] = next === 'true' ? true : next === 'false' ? false : next;
        i++;
      }
    }
  }
  return opts;
}

function nowTimestamp() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm   = String(d.getMonth() + 1).padStart(2, '0');
  const dd   = String(d.getDate()).padStart(2, '0');
  const hh   = String(d.getHours()).padStart(2, '0');
  const mi   = String(d.getMinutes()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
}

function ok(obj) {
  process.stdout.write(JSON.stringify(obj, null, 2) + '\n');
}

function fail(obj) {
  process.stderr.write(JSON.stringify(obj, null, 2) + '\n');
  process.exit(1);
}

// ─────────────────────────────────────────────
// Subcommand: init
// ─────────────────────────────────────────────

function cmdInit(opts) {
  const projectTypeRaw = opts['project-type'];
  const slug           = opts['slug'];
  const projectName    = opts['project-name'];
  const outputDir      = opts['output-dir'];
  const force          = opts['force'] === true;

  if (!projectTypeRaw || !slug || !projectName || !outputDir) {
    fail({ success: false, error: 'missing_args', message: '--project-type, --slug, --project-name, --output-dir are required' });
  }

  // Whitelist check: six English tokens, or SKILL.md's Chinese names normalized to English keys.
  // Unknown values must error out — a silent fallback would drop all type-specific P0 fields.
  let projectType;
  try {
    projectType = normalizeProjectType(projectTypeRaw);
  } catch (err) {
    fail({ success: false, error: 'invalid_project_type', message: err.message });
  }

  const jsonPath = path.join(outputDir, `ledger-state-${slug}.json`);
  const mdPath   = path.join(outputDir, `brd-ledger-${slug}.md`);

  // Re-entry guard: an existing ledger holds locked decisions and the round log —
  // overwriting it silently would destroy the traceability record.
  if (!force && fs.existsSync(jsonPath)) {
    fail({
      success: false,
      error:   'already_exists',
      message: `台账已存在: ${jsonPath}。重跑 init 会清空全部已锁定字段与变更日志；确认要推倒重建时加 --force。`,
    });
  }

  let data;
  try {
    data = createEmptyLedger(projectName, slug, projectType);
  } catch (err) {
    fail({ success: false, error: 'create_failed', message: err.message });
  }

  try {
    writeLedger(jsonPath, data, slug);
  } catch (err) {
    fail({ success: false, error: 'write_failed', message: err.message });
  }

  const totalFields  = data.fields.length;
  const lockedFields = data.fields.filter((f) => f.status === 'locked').length;

  ok({
    success:       true,
    action:        'init',
    json_path:     jsonPath,
    md_path:       mdPath,
    total_fields:  totalFields,
    locked_fields: lockedFields,
  });
}

// ─────────────────────────────────────────────
// Subcommand: lock
// ─────────────────────────────────────────────

function cmdLock(opts) {
  const ledgerPath     = opts['ledger'];
  const fieldsRaw      = opts['fields'];
  const round          = opts['round'];
  const requesterQuote = opts['requester-quote'] ?? null;

  if (!ledgerPath || !fieldsRaw || round === undefined) {
    fail({ success: false, error: 'missing_args', message: '--ledger, --fields, --round are required' });
  }

  let data;
  try {
    data = readLedger(ledgerPath);
  } catch (err) {
    fail({ success: false, error: 'read_failed', message: err.message });
  }

  // DONE guard: a finalized ledger is the traceability record of the saved BRD.
  if (data.header.current_phase === 'DONE') {
    fail({
      success: false,
      error:   'phase_done',
      message: '终稿已落盘（DONE），台账禁止再锁定字段。需求方明确要求继续迭代时，先执行 set-phase --phase C --round <n> 显式重开（reopen），再重新收敛。',
    });
  }

  let fieldsToLock;
  try {
    fieldsToLock = JSON.parse(fieldsRaw);
  } catch (err) {
    fail({ success: false, error: 'invalid_fields_json', message: `--fields must be valid JSON array: ${err.message}` });
  }

  if (!Array.isArray(fieldsToLock) || fieldsToLock.length === 0) {
    fail({ success: false, error: 'invalid_fields', message: '--fields must be a non-empty JSON array' });
  }

  const roundNum = Number(round);

  // Build a registry map from ledger fields for fast lookup
  const fieldRegistry = new Map(data.fields.map((f) => [f.id, f]));

  // Validate: all field IDs exist
  for (const item of fieldsToLock) {
    if (!fieldRegistry.has(item.id)) {
      fail({ success: false, error: 'unknown_field', message: `Field ID not found in ledger: ${item.id}` });
    }
  }

  // Validate: value types match
  for (const item of fieldsToLock) {
    const def = fieldRegistry.get(item.id);
    if (def.value_type === 'text' && typeof item.value !== 'string') {
      fail({ success: false, error: 'type_mismatch', message: `Field ${item.id} expects text (string), got ${typeof item.value}` });
    }
    if (def.value_type === 'structured' && (typeof item.value !== 'object' || item.value === null || Array.isArray(item.value))) {
      fail({ success: false, error: 'type_mismatch', message: `Field ${item.id} expects structured (object), got ${typeof item.value}` });
    }
  }

  // Single-focus enforcement: Phase C/D only allow 1 field per lock call.
  // Phase B batch lock is the only exception (AI calls lock before set-phase to C).
  const phase = data.header.current_phase;
  if (phase !== 'B' && fieldsToLock.length > 1) {
    fail({
      success: false,
      error: 'single_focus_violation',
      message: `当前阶段 ${phase}：单焦点原则要求每轮只锁定 1 个字段，收到 ${fieldsToLock.length} 个。Phase B 批量锁定除外。`,
    });
  }

  // Rule conflict detection
  const header = data.header;
  const detectedConflicts = [];

  for (const item of fieldsToLock) {
    for (const rule of RULE_CONFLICTS) {
      if (rule.check(header, item.id)) {
        detectedConflicts.push({
          rule_id:     rule.id,
          field_id:    item.id,
          description: rule.description,
        });
      }
    }
  }

  if (detectedConflicts.length > 0) {
    // Write conflicts to the conflicts array but DO NOT write field values
    const nextConflictId = (data.conflicts.length > 0
      ? Math.max(...data.conflicts.map((c) => c.id)) + 1
      : 1);

    detectedConflicts.forEach((c, idx) => {
      data.conflicts.push({
        id:          nextConflictId + idx,
        status:      'open',
        fields:      [c.field_id],
        description: `[${c.rule_id}] ${c.description}`,
        resolution:  null,
        resolved_round: null,
      });
    });

    try {
      writeLedger(ledgerPath, data, header.slug);
    } catch (err) {
      fail({ success: false, error: 'write_failed', message: err.message });
    }

    fail({
      success:    false,
      error:      'rule_conflict',
      conflicts:  detectedConflicts,
      retry_hint: '请修改字段值或检查项目类型后重试',
    });
  }

  // No conflicts — apply the lock
  const changes = [];
  for (const item of fieldsToLock) {
    const field = fieldRegistry.get(item.id);
    changes.push({
      field_id:   item.id,
      old_value:  field.value,
      old_status: field.status,
      new_value:  item.value,
      new_status: 'locked',
    });
    field.value       = item.value;
    field.status      = 'locked';
    field.lock_round  = roundNum;
    field.methodology = item.methodology ?? null;
  }

  // Build changelog entry
  const actionType = fieldsToLock.length > 1 ? 'batch_lock' : 'lock';
  const entry = {
    round,
    timestamp:       nowTimestamp(),
    action_type:     actionType,
    action:          actionType,
    changes,
    methodology:     fieldsToLock[0]?.methodology ?? null,
    requester_quote: requesterQuote,
  };
  data.changelog.push(entry);

  // Advance header round marker (never decreases) — cross-session recovery reads it
  if (Number.isFinite(roundNum)) {
    header.current_round = Math.max(header.current_round ?? 0, roundNum);
  }

  // Invalidate derived state after field value changes
  invalidateDerivedState(data);

  try {
    writeLedger(ledgerPath, data, header.slug);
  } catch (err) {
    fail({ success: false, error: 'write_failed', message: err.message });
  }

  ok({
    success:        true,
    action:         'lock',
    locked_fields:  changes.map((c) => c.field_id),
    round:          roundNum,
  });
}

// ─────────────────────────────────────────────
// Subcommand: rollback
// ─────────────────────────────────────────────

function cmdRollback(opts) {
  const ledgerPath = opts['ledger'];

  if (!ledgerPath) {
    fail({ success: false, error: 'missing_args', message: '--ledger is required' });
  }

  let data;
  try {
    data = readLedger(ledgerPath);
  } catch (err) {
    fail({ success: false, error: 'read_failed', message: err.message });
  }

  // DONE guard: rolling back after finalization would desync the ledger from the saved BRD.
  if (data.header.current_phase === 'DONE') {
    fail({
      success: false,
      error:   'phase_done',
      message: '终稿已落盘（DONE），禁止回滚——回滚会让台账与已落盘的 BRD 终稿不一致。需求方明确要求继续迭代时，先执行 set-phase --phase C --round <n> 显式重开（reopen）。',
    });
  }

  // Find the latest lock entry that has NOT been rolled back yet.
  // Stack-style matching: each rollback entry consumes the nearest earlier change-bearing
  // entry, so consecutive rollbacks walk further back instead of re-hitting the same round.
  const changelog = data.changelog ?? [];
  let targetEntry = null;
  let pendingRollbacks = 0;
  for (let i = changelog.length - 1; i >= 0; i--) {
    const entry = changelog[i];
    if (entry.action_type === 'rollback' || entry.action === 'rollback') {
      pendingRollbacks++;
      continue;
    }
    // Entries without field changes (e.g. reopen) have nothing to reverse — skip
    if (!Array.isArray(entry.changes) || entry.changes.length === 0) continue;
    if (pendingRollbacks > 0) {
      pendingRollbacks--; // already rolled back — keep walking back
      continue;
    }
    targetEntry = entry;
    break;
  }

  if (!targetEntry) {
    fail({
      success: false,
      error:   'nothing_to_rollback',
      message: '没有可回滚的锁定记录：历史锁定已全部回滚，或台账中还没有锁定记录。',
    });
  }

  const fieldRegistry = new Map(data.fields.map((f) => [f.id, f]));
  const reversedFields = [];

  for (const ch of (targetEntry.changes ?? [])) {
    const field = fieldRegistry.get(ch.field_id);
    if (!field) continue;
    field.value       = ch.old_value;
    field.status      = ch.old_status;
    field.lock_round  = ch.old_status === 'locked' ? field.lock_round : null;
    reversedFields.push(ch.field_id);
  }

  // Append rollback changelog entry
  const rollbackEntry = {
    round:            targetEntry.round,
    timestamp:        nowTimestamp(),
    action_type:      'rollback',
    action:           'rollback',
    rolled_back_round: targetEntry.round,
    changes:          (targetEntry.changes ?? []).map((ch) => ({
      field_id:   ch.field_id,
      old_value:  ch.new_value,
      old_status: ch.new_status,
      new_value:  ch.old_value,
      new_status: ch.old_status,
    })),
    methodology:      null,
    requester_quote:  null,
  };
  data.changelog.push(rollbackEntry);

  // Advance header round marker (never decreases — rollback does not rewind round numbering)
  const targetRound = Number(targetEntry.round);
  if (Number.isFinite(targetRound)) {
    data.header.current_round = Math.max(data.header.current_round ?? 0, targetRound);
  }

  // Invalidate derived state after field value changes
  invalidateDerivedState(data);

  try {
    writeLedger(ledgerPath, data, data.header.slug);
  } catch (err) {
    fail({ success: false, error: 'write_failed', message: err.message });
  }

  ok({
    success:           true,
    action:            'rollback',
    rolled_back_round: targetEntry.round,
    reversed_fields:   reversedFields,
  });
}

// ─────────────────────────────────────────────
// Subcommand: set-phase
// ─────────────────────────────────────────────

function cmdSetPhase(opts) {
  const ledgerPath = opts['ledger'];
  const toPhase    = opts['phase'];
  const round      = opts['round'];

  if (!ledgerPath || !toPhase || round === undefined) {
    fail({ success: false, error: 'missing_args', message: '--ledger, --phase, --round are required' });
  }

  let data;
  try {
    data = readLedger(ledgerPath);
  } catch (err) {
    fail({ success: false, error: 'read_failed', message: err.message });
  }

  const fromPhase = data.header.current_phase;
  const roundNum  = Number(round);

  if (!isValidTransition(fromPhase, toPhase)) {
    fail({
      success: false,
      error:   'invalid_transition',
      message: `Transition ${fromPhase} → ${toPhase} is not allowed`,
    });
  }

  // Apply phase transition
  data.header.current_phase = toPhase;

  // Advance header round marker (never decreases) — cross-session recovery reads it
  if (Number.isFinite(roundNum)) {
    data.header.current_round = Math.max(data.header.current_round ?? 0, roundNum);
  }

  // DONE → C special handling
  if (fromPhase === 'DONE' && toPhase === 'C') {
    data.header.reopen_count = (data.header.reopen_count ?? 0) + 1;

    // Reset all gates to null
    if (Array.isArray(data.gates)) {
      data.gates.forEach((g) => {
        g.status  = null;
        g.remarks = null;
      });
    }

    // Set chapter_plan = null
    data.chapter_plan = null;

    // Set d5_state
    data.header.d5_state = {
      last_result:                  'passed',
      last_triggered_at_round:      data.header.d5_state?.last_triggered_at_round ?? null,
      fields_changed_since_last_d5: false,
    };

    // Append reopen changelog entry
    data.changelog.push({
      round:            roundNum,
      timestamp:        nowTimestamp(),
      action_type:      'reopen',
      action:           'reopen',
      changes:          [],
      methodology:      null,
      requester_quote:  null,
    });
  }

  // D.5 state maintenance
  const d5State = data.header.d5_state;

  // Entering D.5
  if (toPhase === 'D.5') {
    d5State.last_triggered_at_round      = roundNum;
    d5State.fields_changed_since_last_d5 = false;
  }

  // D.5 → E: set last_result = 'passed'
  if (fromPhase === 'D.5' && toPhase === 'E') {
    d5State.last_result = 'passed';
  }

  // D.5 → C: set last_result = 'failed'
  if (fromPhase === 'D.5' && toPhase === 'C') {
    d5State.last_result = 'failed';
  }

  try {
    writeLedger(ledgerPath, data, data.header.slug);
  } catch (err) {
    fail({ success: false, error: 'write_failed', message: err.message });
  }

  ok({
    success: true,
    action:  'set-phase',
    from:    fromPhase,
    to:      toPhase,
    round:   roundNum,
  });
}

// ─────────────────────────────────────────────
// Subcommand: add-conflict
// ─────────────────────────────────────────────

function cmdAddConflict(opts) {
  const ledgerPath  = opts['ledger'];
  const fieldsRaw   = opts['fields'];
  const description = opts['description'];

  if (!ledgerPath || !fieldsRaw || !description) {
    fail({ success: false, error: 'missing_args', message: '--ledger, --fields, --description are required' });
  }

  let data;
  try {
    data = readLedger(ledgerPath);
  } catch (err) {
    fail({ success: false, error: 'read_failed', message: err.message });
  }

  const fieldIds = fieldsRaw.split(',').map((s) => s.trim()).filter(Boolean);
  const nextId   = data.conflicts.length > 0
    ? Math.max(...data.conflicts.map((c) => c.id)) + 1
    : 1;

  const newConflict = {
    id:             nextId,
    status:         'open',
    fields:         fieldIds,
    description,
    resolution:     null,
    resolved_round: null,
  };

  data.conflicts.push(newConflict);

  try {
    writeLedger(ledgerPath, data, data.header.slug);
  } catch (err) {
    fail({ success: false, error: 'write_failed', message: err.message });
  }

  ok({
    success:   true,
    action:    'add-conflict',
    conflict:  newConflict,
  });
}

// ─────────────────────────────────────────────
// Subcommand: resolve-conflict
// ─────────────────────────────────────────────

function cmdResolveConflict(opts) {
  const ledgerPath  = opts['ledger'];
  const conflictId  = opts['conflict-id'];
  const resolution  = opts['resolution'];
  const round       = opts['round'];

  if (!ledgerPath || conflictId === undefined || !resolution || round === undefined) {
    fail({ success: false, error: 'missing_args', message: '--ledger, --conflict-id, --resolution, --round are required' });
  }

  let data;
  try {
    data = readLedger(ledgerPath);
  } catch (err) {
    fail({ success: false, error: 'read_failed', message: err.message });
  }

  const idNum   = Number(conflictId);
  const roundNum = Number(round);
  const conflict = data.conflicts.find((c) => c.id === idNum);

  if (!conflict) {
    fail({ success: false, error: 'conflict_not_found', message: `No conflict with id=${idNum}` });
  }

  conflict.status         = 'resolved';
  conflict.resolution     = resolution;
  conflict.resolved_round = roundNum;

  try {
    writeLedger(ledgerPath, data, data.header.slug);
  } catch (err) {
    fail({ success: false, error: 'write_failed', message: err.message });
  }

  ok({
    success:  true,
    action:   'resolve-conflict',
    conflict,
  });
}

// ─────────────────────────────────────────────
// Subcommand: update-gates
// ─────────────────────────────────────────────

function cmdUpdateGates(opts) {
  const ledgerPath = opts['ledger'];
  const gatesRaw   = opts['gates'];

  if (!ledgerPath || !gatesRaw) {
    fail({ success: false, error: 'missing_args', message: '--ledger and --gates are required' });
  }

  let data;
  try {
    data = readLedger(ledgerPath);
  } catch (err) {
    fail({ success: false, error: 'read_failed', message: err.message });
  }

  let gateUpdates;
  try {
    gateUpdates = JSON.parse(gatesRaw);
  } catch (err) {
    fail({ success: false, error: 'invalid_gates_json', message: `--gates must be valid JSON array: ${err.message}` });
  }

  if (!Array.isArray(gateUpdates)) {
    fail({ success: false, error: 'invalid_gates', message: '--gates must be a JSON array' });
  }

  const updated = [];
  for (const update of gateUpdates) {
    const gate = (data.gates ?? []).find((g) => g.id === update.gate);
    if (!gate) {
      fail({ success: false, error: 'gate_not_found', message: `Gate not found: ${update.gate}` });
    }
    gate.status  = update.status  ?? gate.status;
    gate.remarks = update.remarks ?? gate.remarks;
    updated.push(update.gate);
  }

  try {
    writeLedger(ledgerPath, data, data.header.slug);
  } catch (err) {
    fail({ success: false, error: 'write_failed', message: err.message });
  }

  ok({
    success:       true,
    action:        'update-gates',
    updated_gates: updated,
  });
}

// ─────────────────────────────────────────────
// Main dispatch
// ─────────────────────────────────────────────

const [,, subcommand, ...rest] = process.argv;
const opts = parseArgs(rest);

switch (subcommand) {
  case 'init':             cmdInit(opts);            break;
  case 'lock':             cmdLock(opts);            break;
  case 'rollback':         cmdRollback(opts);        break;
  case 'set-phase':        cmdSetPhase(opts);        break;
  case 'add-conflict':     cmdAddConflict(opts);     break;
  case 'resolve-conflict': cmdResolveConflict(opts); break;
  case 'update-gates':     cmdUpdateGates(opts);     break;
  default:
    fail({
      success: false,
      error:   'unknown_subcommand',
      message: `Unknown subcommand: ${subcommand}. Valid: init, lock, rollback, set-phase, add-conflict, resolve-conflict, update-gates`,
    });
}
