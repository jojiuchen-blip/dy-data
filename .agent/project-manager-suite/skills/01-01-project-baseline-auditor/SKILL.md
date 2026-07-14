---
name: project-baseline-auditor
description: Use when an existing or half-built host codebase is being adopted into the suite, especially when maintainability is poor because project-profile, BRD, page explainer, foundation, or PRD files are missing or stale.
---

# Project Baseline Auditor

This skill diagnoses an existing codebase before normal suite work continues. It builds or updates the shared `project-profile.md`, then writes a focused maintenance-document gap list for the main router.

## Scope

Use this skill for:
- Existing code moved under a host project.
- A half-built or finished project that lacks maintainable structured files.
- A user asking what BRD / page explainer / foundation / PRD files are missing.

Do not use it for:
- Test cases, test execution, or acceptance plans.
- New development planning or pending implementation tasks.
- Replacing `brd-writer`, `page-explainer`, `foundation-builder`, or `prd-writer`.

## Evidence Boundary

Baseline evidence must come from host-authored source, docs, configuration, schemas, migrations, and other project-owned materials.
Dependency trees, generated build outputs, caches, compiled artifacts, and AI tool runtime directories are noise and must be ignored at any directory depth before counting page, API, model, config, or README signals.

- Prefer a repository-root README; a cache or dependency README is never project identity evidence.
- Count page files only from explicit page/view/screen locations or page-like filenames. Components, application shells, routers, and backend route modules are not pages.
- Report API source files separately from detected endpoint declarations.
- Include conventional model modules and migration directories; report model definitions and migration files separately.
- Persist only repository-relative evidence paths. Never write a developer-machine absolute path into baseline artifacts.
- File and declaration counts are discovery evidence, not confirmed business scope. They may guide the next documentation task but must not invent page purpose, role, or positioning.

## Required Command

Run the scanner first:

```bash
node <suite-path>/skills/01-01-project-baseline-auditor/scripts/collect-baseline-gaps.mjs <hostRoot> --json [--slug <slug>]
```

> `<suite-path>` 指套件根目录：源码仓库联调时为 `project-manager-suite/`，安装到宿主后为 `.agent/project-manager-suite/`；命令默认在宿主项目根目录执行。

The script writes:
- `<host>/project-profile.md`
- `<host>/docs/baseline/baseline-audit-<slug>.json`
- `<host>/docs/baseline/baseline-audit-<slug>.md`

## Slug Rules

The authoritative slug source is the `项目 slug` field in `project-profile.md`. All suite artifacts of one host project must share one slug.

- If the host already has a slug — in the profile `项目 slug` field, or in an existing `docs/baseline/baseline-audit-<slug>.json` — it must be reused. Do not derive a new one.
- When the caller (usually `ai-project-manager`) already knows the slug, pass it explicitly with `--slug <slug>` on every refresh run.
- Without `--slug`, the script resolves the slug in this order: profile `项目 slug` field → most recently modified existing `baseline-audit-<slug>.json` → derived from `package.json` name / profile project name / directory name.
- The resolved slug is written back into the profile `项目 slug` field, so later stages (such as `brd-writer`) can read and reuse it.

## Profile Rules

- Use the same `project-profile.md` filename as `ai-project-manager`.
- When `project-profile.md` already exists, the script merges line by line instead of rewriting the file: every line carrying `【用户确认】` or `【主入口回写】` is kept verbatim; other recognized profile fields (typically `【系统推断】` lines) are refreshed from code evidence; lines that are not profile fields stay untouched; missing template fields are appended.
- Fill code-derived values as `【系统推断】`.
- Fill stage judgment fields as `【主入口回写】`.
- Do not guess fields that code cannot prove; put them in `待确认`.

## Single-Focus Interview

If startup minimum fields are still missing, ask exactly one question: the highest-blocking question from `profile.next_questions[0]`.

You may summarize all findings first, but only one user-answerable question is allowed in the turn. This follows the same single-focus principle used by `brd-writer`.

## Gap List Rules

The audit scope is maintenance docs only:
- `PROJECT_PROFILE`
- `BRD`
- `PAGE_EXPLAINER`
- `FOUNDATION`
- `PRD`

The `summary.recommended_next_skill` field in the audit JSON takes exactly one of these values:

| Value | When |
|---|---|
| `ai-project-manager` | The profile still has a pending question (`profile.next_questions` is not empty); the main router must ask the user first |
| `brd-writer` | BRD gap is the first missing maintenance document |
| `page-explainer` | Page explainer gap is the first missing maintenance document |
| `foundation-builder` | Foundation gap is the first missing maintenance document |
| `prd-writer` | PRD gap is the first missing maintenance document |
| `null` (shown as `无` in the markdown report) | No pending question and no maintenance-document gap |

Per-artifact `recommended_skill` values are limited to the four document skills above, plus `project-baseline-auditor` on the `PROJECT_PROFILE` row and `null` when the artifact is present.

Never recommend:
- `delivery-planner`
- `test-case-chief`
- `test-case-writer`
- `test-case-reviewer`
- `test-case-runner`

## Handoff

After the audit, tell `ai-project-manager` to read `docs/baseline/baseline-audit-<slug>.json` and route only by its maintenance-document gap list. The audit is evidence, not a final BRD/PRD/foundation/page specification.
