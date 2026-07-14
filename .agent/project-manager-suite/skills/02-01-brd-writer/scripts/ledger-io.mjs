#!/usr/bin/env node
/**
 * ledger-io.mjs — shared module for BRD ledger scripts.
 * Not a CLI entry point. Imported by ledger-mutate/query/render.
 */

import fs from 'fs';
import path from 'path';

// ─────────────────────────────────────────────
// Schema version
// ─────────────────────────────────────────────

export const SCHEMA_VERSION = '2.0.0';
// v2.0.0 (2026-05-22): breaking — BRD universal/type-specific fields and CHAPTER_MATRIX
// were simplified; old ledger files (1.0.0) need migration before rendering.
// Migration action: drop unsupported fields/values and re-render markdown.

// ─────────────────────────────────────────────
// Universal P0 fields
// All definitions trace to: references/p0-fields.md §通用P0
// ─────────────────────────────────────────────

export const UNIVERSAL_P0 = [
  // ref: p0-fields.md #1
  {
    id: 'project_type',
    display_name: '项目类型',
    field_type: 'decision',
    value_type: 'text',
    section: 'universal',
    condition: null,
  },
  // ref: p0-fields.md #2
  {
    id: 'project_background',
    display_name: '项目背景',
    field_type: 'fact',
    value_type: 'text',
    section: 'universal',
    condition: null,
  },
  // ref: p0-fields.md #3
  {
    id: 'stakeholder_roles',
    display_name: '利益相关角色',
    field_type: 'fact',
    value_type: 'text',
    section: 'universal',
    condition: null,
  },
  // ref: p0-fields.md #4
  {
    id: 'core_pain_points',
    display_name: '核心痛点',
    field_type: 'fact',
    value_type: 'text',
    section: 'universal',
    condition: null,
  },
  // ref: p0-fields.md #5
  {
    id: 'core_value_model',
    display_name: '核心价值模型',
    field_type: 'decision',
    value_type: 'text',
    section: 'universal',
    condition: null,
  },
  // ref: p0-fields.md #6
  {
    id: 'scope_definition',
    display_name: '范围定义',
    field_type: 'decision',
    value_type: 'text',
    section: 'universal',
    condition: null,
  },
  // ref: p0-fields.md #7
  {
    id: 'key_risks',
    display_name: '关键风险与兜底策略',
    field_type: 'fact',
    value_type: 'text',
    section: 'universal',
    condition: null,
  },
  // ref: p0-fields.md #8
  {
    id: 'project_timeline',
    display_name: '项目周期',
    field_type: 'fact',
    value_type: 'text',
    section: 'universal',
    condition: null,
  },
];

// ─────────────────────────────────────────────
// Type-specific P0 fields
// All definitions trace to: references/p0-fields.md §各类型追加P0
// ─────────────────────────────────────────────

export const TYPE_SPECIFIC_P0 = {
  // ref: p0-fields.md §创新型追加P0
  innovation: [
    // ref: p0-fields.md 创新#11
    {
      id: 'innovation_target_user_scenario',
      display_name: '目标使用者与核心场景',
      field_type: 'fact',
      value_type: 'text',
      section: 'innovation',
      condition: null,
    },
    // ref: p0-fields.md 创新#12
    {
      id: 'innovation_current_alternatives',
      display_name: '用户当前替代方案',
      field_type: 'fact',
      value_type: 'text',
      section: 'innovation',
      condition: null,
    },
    // ref: p0-fields.md 创新#13
    {
      id: 'innovation_validation_evidence',
      display_name: '需求验证证据',
      field_type: 'fact',
      value_type: 'text',
      section: 'innovation',
      condition: null,
    },
    // ref: p0-fields.md 创新#14
    {
      id: 'innovation_value_proposition',
      display_name: '核心价值主张',
      field_type: 'decision',
      value_type: 'text',
      section: 'innovation',
      condition: null,
    },
    // ref: p0-fields.md 创新#15 — structured: single-record metric
    {
      id: 'innovation_north_star',
      display_name: '核心衡量指标',
      field_type: 'decision',
      value_type: 'structured',
      schema: ['metric_name', 'formula', 'target', 'period'],
      section: 'innovation',
      condition: null,
    },
    // ref: p0-fields.md 创新#16
    {
      id: 'innovation_auxiliary_metrics',
      display_name: '辅助业务指标体系',
      field_type: 'decision',
      value_type: 'text',
      section: 'innovation',
      condition: null,
    },
  ],

  // ref: p0-fields.md §改造型追加P0
  transformation: [
    // ref: p0-fields.md 改造#11 — structured: single-record metric
    {
      id: 'transformation_target_metric',
      display_name: '改造目标指标',
      field_type: 'decision',
      value_type: 'structured',
      schema: ['dimension', 'baseline', 'target'],
      section: 'transformation',
      condition: null,
    },
    // ref: p0-fields.md 改造#12
    {
      id: 'transformation_alt_comparison',
      display_name: '备选技术方案对比',
      field_type: 'decision',
      value_type: 'text',
      section: 'transformation',
      condition: null,
    },
  ],

  // ref: p0-fields.md §扩展型追加P0
  extension: [
    // ref: p0-fields.md 扩展#11
    {
      id: 'extension_target_user_scenario',
      display_name: '目标使用者与核心场景',
      field_type: 'fact',
      value_type: 'text',
      section: 'extension',
      condition: null,
    },
    // ref: p0-fields.md 扩展#12
    {
      id: 'extension_validation_evidence',
      display_name: '需求验证证据',
      field_type: 'fact',
      value_type: 'text',
      section: 'extension',
      condition: null,
    },
    // ref: p0-fields.md 扩展#13
    {
      id: 'extension_value_proposition',
      display_name: '核心价值主张',
      field_type: 'decision',
      value_type: 'text',
      section: 'extension',
      condition: null,
    },
    // ref: p0-fields.md 扩展#14 — structured: single-record metric
    {
      id: 'extension_core_metrics',
      display_name: '核心指标',
      field_type: 'decision',
      value_type: 'structured',
      schema: ['metric_name', 'formula', 'target', 'period'],
      section: 'extension',
      condition: null,
    },
  ],

  // ref: p0-fields.md §集成型追加P0 — 纯B2B，无页面字段
  integration: [
    // ref: p0-fields.md 集成#11
    {
      id: 'integration_upstream_downstream',
      display_name: '上下游系统画像',
      field_type: 'fact',
      value_type: 'text',
      section: 'integration',
      condition: null,
    },
    // ref: p0-fields.md 集成#12
    {
      id: 'integration_current_method',
      display_name: '当前对接方式',
      field_type: 'fact',
      value_type: 'text',
      section: 'integration',
      condition: null,
    },
    // ref: p0-fields.md 集成#13
    {
      id: 'integration_goal',
      display_name: '集成目标',
      field_type: 'decision',
      value_type: 'text',
      section: 'integration',
      condition: null,
    },
    // ref: p0-fields.md 集成#14
    {
      id: 'integration_alt_comparison',
      display_name: '备选集成方案对比',
      field_type: 'decision',
      value_type: 'text',
      section: 'integration',
      condition: null,
    },
  ],

  // ref: p0-fields.md §运营型追加P0 — 必有后台页面，页面字段通过PAGE_FIELDS注入
  operational: [
    // ref: p0-fields.md 运营#11
    {
      id: 'operational_current_workflow',
      display_name: '当前工作流',
      field_type: 'fact',
      value_type: 'text',
      section: 'operational',
      condition: null,
    },
    // ref: p0-fields.md 运营#12 — structured: single-record metric
    {
      id: 'operational_efficiency_goal',
      display_name: '效率目标',
      field_type: 'decision',
      value_type: 'structured',
      schema: ['dimension', 'baseline', 'target'],
      section: 'operational',
      condition: null,
    },
  ],

  // ref: p0-fields.md §合规型追加P0
  compliance: [
    // ref: p0-fields.md 合规#11
    {
      id: 'compliance_gap',
      display_name: '当前合规差距',
      field_type: 'fact',
      value_type: 'text',
      section: 'compliance',
      condition: null,
    },
    // ref: p0-fields.md 合规#12
    {
      id: 'compliance_standard',
      display_name: '合规达标标准',
      field_type: 'decision',
      value_type: 'text',
      section: 'compliance',
      condition: null,
    },
    // ref: p0-fields.md 合规#13
    {
      id: 'compliance_scope_priority',
      display_name: '整改范围与优先级',
      field_type: 'decision',
      value_type: 'text',
      section: 'compliance',
      condition: null,
    },
  ],
};

// ─────────────────────────────────────────────
// Project type normalization
// ref: SKILL.md Phase A 中英对照表（中文类型名 ↔ 脚本英文 token）
// ─────────────────────────────────────────────

export const VALID_PROJECT_TYPES = Object.keys(TYPE_SPECIFIC_P0);

export const PROJECT_TYPE_ALIASES = {
  创新型: 'innovation',
  改造型: 'transformation',
  扩展型: 'extension',
  集成型: 'integration',
  运营型: 'operational',
  合规型: 'compliance',
};

/**
 * Normalize a --project-type value to its English key.
 * Accepts the six English tokens, or the Chinese names used in SKILL.md (mapped to English keys).
 * Throws with the full list of valid values on unknown input.
 *
 * @param {string} input - raw --project-type value
 * @returns {string} normalized English key
 */
export function normalizeProjectType(input) {
  const raw = String(input ?? '').trim();
  if (VALID_PROJECT_TYPES.includes(raw)) return raw;
  if (PROJECT_TYPE_ALIASES[raw]) return PROJECT_TYPE_ALIASES[raw];
  const validList = Object.entries(PROJECT_TYPE_ALIASES)
    .map(([zh, en]) => `${en}（${zh}）`)
    .join(', ');
  throw new Error(`Unknown project type: "${raw}". Valid values: ${validList}`);
}

// ─────────────────────────────────────────────
// Page fields
// ref: p0-fields.md §页面定位全套字段
// ─────────────────────────────────────────────

export const PAGE_FIELDS = [
  // ref: p0-fields.md 页面#1
  {
    id: 'page_coverage',
    display_name: '项目覆盖对象',
    field_type: 'fact',
    value_type: 'text',
    section: 'page',
    condition: null,
  },
  // ref: p0-fields.md 页面#2
  {
    id: 'page_target_users',
    display_name: '各端目标用户',
    field_type: 'fact',
    value_type: 'text',
    section: 'page',
    condition: null,
  },
  // ref: p0-fields.md 页面#3
  {
    id: 'page_primary_use',
    display_name: '各端主要用途',
    field_type: 'fact',
    value_type: 'text',
    section: 'page',
    condition: null,
  },
  // ref: p0-fields.md 页面#4
  {
    id: 'page_positioning',
    display_name: '页面定位判断',
    field_type: 'fact',
    value_type: 'text',
    section: 'page',
    condition: null,
  },
  // ref: p0-fields.md 页面#5
  {
    id: 'page_downstream_boundary',
    display_name: '下游待确认边界',
    field_type: 'fact',
    value_type: 'text',
    section: 'page',
    condition: null,
  },
];

// ─────────────────────────────────────────────
// Helper: derive hasPages from project type
// ref: p0-fields.md §集成型（默认无独立页面）/ §运营型（必有后台页面）/ 其他类型默认含页面
// ─────────────────────────────────────────────

/**
 * Derive whether the project has pages.
 * Internal-tool defaults: integration → no pages; operational → always pages; others → pages by default.
 * @param {string} projectType - one of: innovation|transformation|extension|integration|operational|compliance
 * @returns {boolean}
 */
export function deriveHasPages(projectType) {
  if (projectType === 'integration') return false;   // pure backend integration, no independent pages
  if (projectType === 'operational') return true;    // always has backend pages
  return true;                                       // innovation/transformation/extension/compliance default to having pages
}

// ─────────────────────────────────────────────
// Helper: build the full field set for a given project context
// ─────────────────────────────────────────────

/**
 * Build the complete ordered field set for a BRD project.
 * Returns field definitions only — no value/status (those are added by init).
 *
 * @param {string} projectType - one of: innovation|transformation|extension|integration|operational|compliance
 * @returns {Array<Object>} ordered array of field definition objects
 */
export function buildFieldSet(projectType) {
  const hasPages = deriveHasPages(projectType);

  const typeFields = (TYPE_SPECIFIC_P0[projectType] ?? []).filter((field) => {
    if (field.condition === 'has_pages' && !hasPages) return false;
    return true;
  });

  const pageFields = hasPages ? PAGE_FIELDS : [];

  return [...UNIVERSAL_P0, ...typeFields, ...pageFields];
}

// ─────────────────────────────────────────────
// Phase migration graph
// ref: SKILL.md §6
// ─────────────────────────────────────────────

/**
 * Allowed phase transitions.
 * Keys are "from" phases; values are arrays of allowed "to" phases.
 * Conditions noted in comments but not enforced here — callers apply guard logic.
 */
export const PHASE_GRAPH = {
  B:    ['C'],
  C:    ['D.5', 'E'],      // D.5 when should_trigger_d5; E when D.5 already passed
  'D.5': ['E', 'C'],       // E when premises passed; C when premises failed
  E:    ['E.5', 'C'],      // E.5 when all gates pass; C when gates fail
  'E.5': ['F', 'C'],       // F when user confirmed; C when user wants modifications
  F:    ['DONE'],          // save-brd success
  DONE: ['C'],             // reopen for iteration
};

/**
 * Check whether a phase transition is valid.
 * @param {string} from - current phase
 * @param {string} to   - target phase
 * @returns {boolean}
 */
export function isValidTransition(from, to) {
  const allowed = PHASE_GRAPH[from];
  return Array.isArray(allowed) && allowed.includes(to);
}

// ─────────────────────────────────────────────
// Chapter cropping matrix
// ref: references/brd-template.md §各项目类型的章节裁剪规则
// ─────────────────────────────────────────────

/**
 * CHAPTER_MATRIX — keyed by template chapter number.
 * Chapter 5 (市场与竞品差异化) and Chapter 7 (商业化路径) are intentionally absent.
 * Template numbers are skeleton IDs used only for cropping/lookup — `chapters finalize`
 * renumbers the included chapters consecutively (1..N) in the final BRD, and the
 * appendix references the renumbered chapters (see references/brd-template.md).
 * Each entry:
 *   title           : default Chinese chapter title
 *   page_dependent  : true → skip unless hasPages
 *   types           : per-type config { status: 'required'|'skip'|'conditional', title_override? }
 */
export const CHAPTER_MATRIX = {
  1: {
    title: '项目背景与机会判断',
    page_dependent: false,
    types: {
      innovation:     { status: 'required' },
      transformation: { status: 'required', title_override: '项目背景与改造动因' },
      extension:      { status: 'required' },
      integration:    { status: 'required', title_override: '项目背景与集成目的' },
      operational:    { status: 'required' },
      compliance:     { status: 'required', title_override: '项目背景与法规要求' },
    },
  },
  2: {
    title: '目标与成功标准',
    page_dependent: false,
    types: {
      innovation:     { status: 'required' },
      transformation: { status: 'required', title_override: '改造目标指标' },
      extension:      { status: 'required' },
      integration:    { status: 'required', title_override: '集成目标' },
      operational:    { status: 'required', title_override: '效率目标' },
      compliance:     { status: 'required', title_override: '合规达标标准' },
    },
  },
  3: {
    title: '利益相关角色与核心场景',
    page_dependent: false,
    types: {
      innovation:     { status: 'required' },
      transformation: { status: 'required', title_override: '利益相关角色与当前系统痛点' },
      extension:      { status: 'required' },
      integration:    { status: 'required', title_override: '利益相关角色与上下游系统画像' },
      operational:    { status: 'required', title_override: '内部用户角色与当前工作流' },
      compliance:     { status: 'required', title_override: '利益相关角色与合规影响范围' },
    },
  },
  4: {
    title: '核心价值主张',
    page_dependent: false,
    types: {
      innovation:     { status: 'required' },
      transformation: { status: 'skip' },
      extension:      { status: 'required' },
      integration:    { status: 'skip' },
      operational:    { status: 'skip' },
      compliance:     { status: 'skip' },
    },
  },
  // Chapter 5 (市场与竞品差异化) removed in v2.0.0.
  6: {
    title: '核心价值模型',
    page_dependent: false,
    types: {
      innovation:     { status: 'required' },
      transformation: { status: 'required', title_override: '改造价值模型' },
      extension:      { status: 'required' },
      integration:    { status: 'required', title_override: '集成价值模型' },
      operational:    { status: 'required' },
      compliance:     { status: 'required', title_override: '合规达标模型' },
    },
  },
  // Chapter 7 (商业化路径与收入模型) removed in v2.0.0.
  8: {
    title: 'MVP 范围',
    page_dependent: false,
    types: {
      innovation:     { status: 'required' },
      transformation: { status: 'required', title_override: '改造范围（分期）' },
      extension:      { status: 'required' },
      integration:    { status: 'required', title_override: '集成范围' },
      operational:    { status: 'required' },
      compliance:     { status: 'required', title_override: '整改范围' },
    },
  },
  9: {
    title: '备选方案对比',
    page_dependent: false,
    types: {
      innovation:     { status: 'required' },
      transformation: { status: 'required', title_override: '备选技术方案对比' },
      extension:      { status: 'required' },
      integration:    { status: 'required' },
      operational:    { status: 'conditional' },
      compliance:     { status: 'conditional' },
    },
  },
  10: {
    title: '关键前提假设',
    page_dependent: false,
    types: {
      innovation:     { status: 'required' },
      transformation: { status: 'required', title_override: '关键前提假设（兼容性）' },
      extension:      { status: 'required' },
      integration:    { status: 'required', title_override: '关键前提假设（第三方稳定性）' },
      operational:    { status: 'conditional' },
      compliance:     { status: 'conditional' },
    },
  },
  11: {
    title: '关键风险与兜底策略',
    page_dependent: false,
    types: {
      innovation:     { status: 'required' },
      transformation: { status: 'required', title_override: '关键风险与兜底策略（迁移风险）' },
      extension:      { status: 'required' },
      integration:    { status: 'required', title_override: '关键风险与兜底策略（第三方风险）' },
      operational:    { status: 'conditional' },
      compliance:     { status: 'required' },
    },
  },
  12: {
    title: '项目周期',
    page_dependent: false,
    types: {
      innovation:     { status: 'required' },
      transformation: { status: 'required' },
      extension:      { status: 'required' },
      integration:    { status: 'required' },
      operational:    { status: 'required' },
      compliance:     { status: 'required', title_override: '项目周期（含合规 deadline）' },
    },
  },
  13: {
    title: '页面定位',
    page_dependent: true,
    types: {
      innovation:     { status: 'conditional' },
      transformation: { status: 'conditional' },
      extension:      { status: 'conditional' },
      integration:    { status: 'skip' },          // integration projects have no independent pages
      operational:    { status: 'required' },      // always has backend pages
      compliance:     { status: 'conditional' },
    },
  },
};

/**
 * Compute the chapter plan for a given project context.
 *
 * @param {string}  projectType  - one of: innovation|transformation|extension|integration|operational|compliance
 * @param {boolean} hasPages     - derived via deriveHasPages()
 * @returns {Array<{ template_number: number, title: string, status: string, reason?: string }>}
 */
export function getChapterPlan(projectType, hasPages) {
  const plan = [];

  for (const [numStr, chapter] of Object.entries(CHAPTER_MATRIX)) {
    const num = Number(numStr);
    const typeConfig = chapter.types[projectType];

    // Unknown project type — mark skip
    if (!typeConfig) {
      plan.push({ template_number: num, title: chapter.title, status: 'skip', reason: 'unknown project type' });
      continue;
    }

    // page_dependent filter
    if (chapter.page_dependent && !hasPages) {
      plan.push({ template_number: num, title: chapter.title, status: 'skip', reason: 'project has no pages' });
      continue;
    }

    // Type-level skip
    if (typeConfig.status === 'skip') {
      plan.push({ template_number: num, title: chapter.title, status: 'skip' });
      continue;
    }

    const resolvedTitle = typeConfig.title_override ?? chapter.title;
    plan.push({ template_number: num, title: resolvedTitle, status: typeConfig.status });
  }

  return plan;
}

// ─────────────────────────────────────────────
// Appendix downstream dependency mapping
// ref: references/brd-template.md §附录：下游交接清单
// ─────────────────────────────────────────────

export const APPENDIX_DEPENDENCIES = [
  {
    downstream_skill: 'page-designer',
    fields: [
      { semantic_name: '利益相关角色',     template_chapters: [3],  optional: false },
      { semantic_name: '各角色痛点与场景', template_chapters: [3],  optional: false },
      { semantic_name: '核心价值模型',     template_chapters: [6],  optional: false },
      { semantic_name: '页面定位',         template_chapters: [13], optional: false },
    ],
  },
  {
    downstream_skill: 'page-explainer',
    fields: [
      { semantic_name: '核心价值主张',     template_chapters: [4],  optional: true  },
      { semantic_name: '利益相关角色诉求', template_chapters: [3],  optional: false },
      { semantic_name: '各端定位',         template_chapters: [13], optional: false },
    ],
  },
  {
    downstream_skill: 'foundation-builder',
    fields: [
      { semantic_name: '指标体系',           template_chapters: [2],  optional: true  },
      { semantic_name: '核心价值模型',       template_chapters: [6],  optional: false },
      { semantic_name: '关键风险与兜底策略', template_chapters: [11], optional: false },
    ],
  },
  {
    downstream_skill: 'prd-writer',
    fields: [
      { semantic_name: '目标与成功标准', template_chapters: [2], optional: false },
      { semantic_name: 'MVP范围',        template_chapters: [8], optional: false },
    ],
  },
];

// ─────────────────────────────────────────────
// Rule conflict definitions
// ─────────────────────────────────────────────

export const RULE_CONFLICTS = [
  {
    id: 'no_pages_page_field',
    check: (header, fieldId) => !header.has_pages && fieldId.startsWith('page_'),
    description: '无页面项目不能锁定页面定位字段',
  },
];

// ─────────────────────────────────────────────
// Timestamp helper
// ─────────────────────────────────────────────

/**
 * Return current local time as "YYYY-MM-DD HH:MM" (no seconds, no timezone).
 * @returns {string}
 */
function nowTimestamp() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm   = String(d.getMonth() + 1).padStart(2, '0');
  const dd   = String(d.getDate()).padStart(2, '0');
  const hh   = String(d.getHours()).padStart(2, '0');
  const mi   = String(d.getMinutes()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
}

// ─────────────────────────────────────────────
// readLedger
// ─────────────────────────────────────────────

/**
 * Read and parse a ledger JSON file.
 * Throws if the schema_version does not match SCHEMA_VERSION.
 *
 * @param {string} jsonPath - absolute path to ledger JSON file
 * @returns {Object} parsed ledger data
 */
export function readLedger(jsonPath) {
  const raw = fs.readFileSync(jsonPath, 'utf8');
  const data = JSON.parse(raw);
  const version = data.schema_version;
  if (version !== SCHEMA_VERSION) {
    throw new Error(
      `Schema version mismatch: file has ${version}, scripts expect ${SCHEMA_VERSION}. Migration needed.`
    );
  }
  return data;
}

// ─────────────────────────────────────────────
// writeLedger
// ─────────────────────────────────────────────

/**
 * Write ledger data to JSON (atomic) and render Markdown sidecar.
 * Markdown write is best-effort; failure is logged but not thrown.
 *
 * @param {string} jsonPath - absolute path to ledger JSON file
 * @param {Object} data     - ledger data object (mutated: last_updated is set)
 * @param {string} slug     - project slug (used for Markdown filename)
 */
export function writeLedger(jsonPath, data, slug) {
  data.header.last_updated = nowTimestamp();

  // Output dir may not exist yet (greenfield host: bootstrap does not pre-create docs/brd)
  const dir = path.dirname(jsonPath);
  fs.mkdirSync(dir, { recursive: true });

  const tmp = `${jsonPath}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2), 'utf8');
  fs.renameSync(tmp, jsonPath);

  const mdPath = path.join(dir, `brd-ledger-${slug}.md`);
  try {
    const mdContent = renderMarkdown(data);
    fs.writeFileSync(mdPath, mdContent, 'utf8');
  } catch (err) {
    console.warn(`[ledger-io] Warning: Markdown render failed (JSON is authoritative): ${err.message}`);
  }
}

// ─────────────────────────────────────────────
// createEmptyLedger
// ─────────────────────────────────────────────

/**
 * Create and return an initial (empty) ledger JSON object.
 *
 * @param {string} projectName  - human-readable project name
 * @param {string} slug         - URL-safe project identifier
 * @param {string} projectType  - one of: innovation|transformation|extension|integration|operational|compliance
 * @returns {Object} ledger data object
 */
export function createEmptyLedger(projectName, slug, projectType) {
  const hasPages = deriveHasPages(projectType);
  const fieldDefs = buildFieldSet(projectType);

  const META_IDS = new Set(['project_type']);
  const metaValues = {
    project_type: projectType,
  };

  const fields = fieldDefs.map((def) => {
    const instance = {
      id:           def.id,
      display_name: def.display_name,
      field_type:   def.field_type,
      value_type:   def.value_type,
    };
    if (def.value_type === 'structured' && def.schema) {
      instance.value_schema = def.schema;
    }
    if (META_IDS.has(def.id)) {
      instance.value       = metaValues[def.id];
      instance.status      = 'locked';
      instance.lock_round  = 0;
      instance.methodology = 'Phase A 定性';
    } else {
      instance.value       = null;
      instance.status      = 'open';
      instance.lock_round  = null;
      instance.methodology = null;
    }
    return instance;
  });

  const gates = [
    { id: 'field_completeness', applicable: true,       status: null, remarks: null },
    { id: 'consistency',        applicable: true,       status: null, remarks: null },
    { id: 'scope',              applicable: true,       status: null, remarks: null },
    { id: 'methodology',        applicable: true,       status: null, remarks: null },
    { id: 'role',               applicable: true,       status: null, remarks: null },
    { id: 'measurement',        applicable: true,       status: null, remarks: null },
    { id: 'page',               applicable: hasPages,   status: null, remarks: null },
  ];

  return {
    schema_version: SCHEMA_VERSION,
    header: {
      project_name:          projectName,
      slug,
      project_type:          projectType,
      has_pages:             hasPages,
      current_phase:         'B',
      current_round:         0,
      created_at:            nowTimestamp(),
      last_updated:          null,
      reopen_count:          0,
      pending_brd_filename:  null,
      brd_filename:          null,
      d5_state: {
        last_result:                    null,
        last_triggered_at_round:        null,
        fields_changed_since_last_d5:   false,
      },
    },
    fields,
    conflicts:    [],
    changelog:    [],
    gates,
    chapter_plan: null,
  };
}

// ─────────────────────────────────────────────
// renderMarkdown
// ─────────────────────────────────────────────

/**
 * Render ledger data to a Markdown string.
 *
 * @param {Object} data - ledger data object
 * @returns {string} Markdown content
 */
export function renderMarkdown(data) {
  const { header, fields, conflicts, changelog, gates } = data;
  const slug = header.slug;
  const lines = [];

  // Anti-edit marker
  lines.push(
    `<!-- 此文件由 ledger-state-${slug}.json 自动生成，请勿手动编辑。修改请通过 brd-writer 脚本操作 JSON 源文件。 -->`
  );
  lines.push('');

  // Header section
  lines.push(`# BRD Ledger — ${header.project_name}`);
  lines.push('');
  lines.push(`- **Slug**: ${slug}`);
  lines.push(`- **Skill**: brd-writer`);
  lines.push(`- **Phase**: ${header.current_phase}`);
  lines.push(`- **Round**: ${header.current_round}`);
  lines.push(`- **Created**: ${header.created_at}`);
  lines.push(`- **Last Updated**: ${header.last_updated ?? '—'}`);
  lines.push('');

  // §1 P0 Fields table
  lines.push('## §1 P0 字段总览');
  lines.push('');
  lines.push('| # | 字段名 | 值 | 状态 | 锁定轮次 | 方法论 |');
  lines.push('|---|--------|----|------|----------|--------|');
  fields.forEach((f, idx) => {
    let rawVal = f.value;
    let displayVal;
    if (rawVal === null || rawVal === undefined) {
      displayVal = '—';
    } else if (typeof rawVal === 'object') {
      displayVal = JSON.stringify(rawVal);
    } else {
      displayVal = String(rawVal);
    }
    if (displayVal.length > 60) {
      displayVal = displayVal.slice(0, 60) + '...';
    }
    const status     = f.status      ?? '—';
    const lockRound  = f.lock_round  != null ? String(f.lock_round) : '—';
    const methodology = f.methodology ?? '—';
    lines.push(`| ${idx + 1} | ${f.display_name} | ${displayVal} | ${status} | ${lockRound} | ${methodology} |`);
  });
  lines.push('');

  // §2 Conflicts table
  lines.push('## §2 冲突记录');
  lines.push('');
  if (!conflicts || conflicts.length === 0) {
    lines.push('（无冲突）');
  } else {
    lines.push('| 冲突 ID | 描述 |');
    lines.push('|---------|------|');
    conflicts.forEach((c) => {
      lines.push(`| ${c.id ?? '—'} | ${c.description ?? '—'} |`);
    });
  }
  lines.push('');

  // §3 Changelog
  lines.push('## §3 变更日志');
  lines.push('');
  if (!changelog || changelog.length === 0) {
    lines.push('（无变更记录）');
  } else {
    changelog.forEach((entry) => {
      const actionLabels = {
        rollback:    '（回滚）',
        batch_lock:  '（Phase B 批量锁定）',
        reopen:      '（重新打开）',
      };
      const label = actionLabels[entry.action] ?? '';
      lines.push(`### Round ${entry.round} — ${entry.action}${label}`);
      lines.push(`- **时间**: ${entry.timestamp ?? '—'}`);
      if (entry.methodology) {
        lines.push(`- **方法论**: ${entry.methodology}`);
      }
      if (entry.requester_quote) {
        lines.push(`- **需求原话**: ${entry.requester_quote}`);
      }
      if (entry.changes && entry.changes.length > 0) {
        lines.push('- **变更内容**:');
        entry.changes.forEach((ch) => {
          lines.push(`  - \`${ch.field_id}\`: ${JSON.stringify(ch.old_value)} → ${JSON.stringify(ch.new_value)}`);
        });
      }
      lines.push('');
    });
  }

  // §4 Gates table
  lines.push('## §4 质量门');
  lines.push('');
  lines.push('| 质量门 | 适用 | 状态 | 备注 |');
  lines.push('|--------|------|------|------|');
  (gates ?? []).forEach((g) => {
    const applicable = g.applicable ? '是' : '否';
    const status     = g.status  ?? '—';
    const remarks    = g.remarks ?? '—';
    lines.push(`| ${g.id} | ${applicable} | ${status} | ${remarks} |`);
  });
  lines.push('');

  return lines.join('\n');
}

// ─────────────────────────────────────────────
// invalidateDerivedState
// ─────────────────────────────────────────────

/**
 * Invalidate derived state after any field value change (lock or rollback).
 * Resets chapter_plan and all gates, then recomputes fields_changed_since_last_d5.
 *
 * @param {Object} data - ledger data object (mutated in place)
 */
export function invalidateDerivedState(data) {
  // Reset chapter plan
  data.chapter_plan = null;

  // Reset all gates
  if (Array.isArray(data.gates)) {
    data.gates.forEach((g) => {
      g.status  = null;
      g.remarks = null;
    });
  }

  // Recompute fields_changed_since_last_d5
  const d5State = data.header.d5_state;
  const lastTriggeredRound = d5State.last_triggered_at_round;

  // If D.5 has never been triggered, don't touch the flag (lock sets it directly)
  if (lastTriggeredRound === null || lastTriggeredRound === undefined) {
    return;
  }

  // Scan changelog entries after lastTriggeredRound
  // Build a map of effective changes (accounting for rollbacks)
  const changelog = data.changelog ?? [];
  const effectiveChanges = new Map(); // field_id → latest effective new_value

  for (const entry of changelog) {
    if (entry.round <= lastTriggeredRound) continue;

    if (entry.action === 'rollback') {
      // Rollback removes previously recorded changes for those fields
      if (Array.isArray(entry.changes)) {
        entry.changes.forEach((ch) => {
          effectiveChanges.delete(ch.field_id);
        });
      }
    } else {
      // lock, batch_lock, reopen, etc. — record the change
      if (Array.isArray(entry.changes)) {
        entry.changes.forEach((ch) => {
          effectiveChanges.set(ch.field_id, ch.new_value);
        });
      }
    }
  }

  d5State.fields_changed_since_last_d5 = effectiveChanges.size > 0;
}
