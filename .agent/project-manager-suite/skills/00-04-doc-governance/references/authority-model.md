# Authority Model

Use this model to decide which file should own a rule.

## Core principle

Each rule family should have one unique authority source.

Other files may keep only:

- a boundary note
- a navigation note
- a short summary that does not recreate the full rule

## File role taxonomy

### 1. Entry file

Typical contents:

- what this package or skill is
- when to use it
- when not to use it
- high-level red lines
- where to read detailed rules

Good examples:

- `SKILL.md`
- human-facing entry documents

Do not put here:

- full execution order
- field contracts
- scaffold implementation details

### 2. Runtime file

Typical contents:

- execution order
- decision flow
- stage gating
- handoff conditions
- runtime red flags

Good examples:

- `runtime.md`
- runbook-like execution protocols

Do not put here:

- detailed field schema ownership
- template creation policy details
- installation or scaffold directory specifics unless runtime truly owns them

### 3. Protocol file

Typical contents:

- field contracts
- read/write responsibility
- lifecycle of artifacts
- default writeback carrier
- template creation prerequisites

Good examples:

- `global-files-protocol.md`
- API or data contract docs

Do not put here:

- full runtime order
- routing target matrix

### 4. Routing or scaffold file

Typical contents:

- capability mapping
- target skill mapping
- directory scaffold
- host integration path
- install and bootstrap strategy

Good examples:

- `routing.md`
- scaffold or bootstrap rule docs

Do not put here:

- full stage execution rules
- repeated S2 or other stage-specific runtime workflows

### 5. Human overview file

Typical contents:

- product explanation
- reading index
- quick start
- reading path by audience

Good examples:

- `README.md`

Do not put here:

- deep protocol or runtime rules

## Anti-patterns

Treat these as governance smells:

- the same stage rule appears in 2 or more authority files
- the same file answers more than 2 role categories
- one change would require keeping 2 files in sync
- a routing file explains runtime order
- a runtime file explains scaffold installation strategy
- an entry file restates full protocol details
- a single long file has no reading index even though readers usually jump by task
- high-frequency and low-frequency sections are mixed with no ordering or fold strategy

## Single-file overload test

Do not default to splitting a file just because it is long.

For a long single file, check in this order:

1. Does the file still have one clear primary role?
2. Would a reading index solve most navigation cost?
3. Can section reordering move high-frequency content earlier?
4. Can low-frequency detail be folded or pushed to appendix-like sections?
5. Only if the answers above are insufficient, propose a split.

Preferred low-cost actions:

- `Add index`: for jump-reading by task or audience
- `Reorder`: put conclusion, quick path, or high-frequency rules first
- `Fold`: collapse low-frequency detail without changing authority ownership
- `Compress`: turn repeated prose into a table, checklist, or short summary

Use split only when:

- one file clearly carries multiple authority roles
- readers must edit different sections with different change cadences
- navigation fixes still leave the file hard to maintain

## Bidirectional index test

For a layered doc system, do not stop at one-way navigation by default.

Check:

1. Can readers move from the entry file to the authority file quickly?
2. Can maintainers who open the authority file directly see what it serves, what implements it, and what else changes with it?
3. If the answer to 1 is yes but 2 is no, the system still needs a backward index.

Use:

- `Forward index`
  - entry -> authority
  - overview -> detail
  - task question -> target section or file
- `Backward index`
  - authority -> entry
  - authority -> structured implementation
  - authority -> tools
  - authority -> change-impact neighbors

Bidirectional indexing is especially useful when:

- there are 3 or more documentation layers
- AI or humans often open deep files directly
- change-impact is distributed across docs, structured rules, templates, and tools

## Decision test

For any rule, ask:

1. If this rule changes, which file should be edited first?
2. Would a maintainer be surprised if that file owned the rule?
3. Does another file only need to point at it rather than restate it?

If question 1 has more than one answer, the boundary is still unclear.

## Governance automation escalation

Do not automate governance checks too early.

Escalate in this order:

1. Manual review
2. Scan
3. Structured impact map
4. Alignment checker
5. Blocking lint / CI

Recommend escalation when:

- the same governance mistake repeats
- the signal is stable and machine-checkable
- missing it creates real maintenance drift

Examples:

- repeated headings or repeated keyword families -> scan
- “changed authority but forgot downstream files” -> structured impact map
- protocol doc and structured implementation drift -> alignment checker
- chronic repeated violations in team workflow -> lint or CI

## Refactor actions

Use these labels in proposals:

- `Keep`: content already belongs here
- `Move`: content belongs in another authority file
- `Delete`: duplicated copy with no value
- `Navigate`: replace with short pointer to authority file
- `Add forward index`: add entry-to-authority navigation
- `Add backward index`: add authority-to-entry / implementation / change-impact navigation
- `Add index`: add a task-based or audience-based reading index
- `Reorder`: move high-frequency sections earlier
- `Fold`: collapse low-frequency detail
- `Compress`: reduce repeated or verbose explanation without changing ownership

## Recommended review order

1. Decide the file roles
2. Identify duplicated rule families
3. Choose one authority source per family
4. Edit authority file first
5. Replace secondary copies with navigation
6. Re-scan for residual overlap
