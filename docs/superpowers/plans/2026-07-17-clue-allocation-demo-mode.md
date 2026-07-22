# Clue Allocation Demo Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a development-only, no-backend demo mode that renders one coherent synthetic clue-allocation dataset across the clue center, follow-up history, allocation admin, trial cycles, decisions, rules, scores, and headquarters pool.

**Architecture:** A deterministic generator creates one in-memory business graph from non-sensitive aggregate weights. A focused repository exposes the same response shapes as the existing API client and handles browser-session-only mutations; `api/client.ts` selects that repository only behind a development-and-flag guard. Existing pages remain the rendering surface, with a persistent demo-data notice added to `Shell`.

**Tech Stack:** React 19, TypeScript 5.8, Vite 7, existing dashboard types/components, pytest controller tests, Playwright browser verification.

## Global Constraints

- Demo mode is enabled only when `import.meta.env.DEV` is true and `VITE_DEMO_MODE === "true"`.
- Production authentication and production API behavior must remain unchanged.
- The frontend must never import, read, bundle, or hash row-level data from `local_exports/`.
- Every synthetic business identifier starts with `DEMO-`; store, customer, phone, operator, order, and note values come only from controlled demo dictionaries.
- Default dataset: 480 unique leads, 48 synthetic stores, 12 cities, 530 successful assignment rounds, and 650-750 follow-up records.
- Of 360 allocated leads, 230 have one round, 90 have two rounds, and 40 have three rounds; 60 leads enter headquarters directly and 60 terminal leads never receive a round.
- Historical rounds are read-only; only the current active round accepts follow-up actions.
- Demo writes update only the in-memory graph and reset on page refresh.
- Demo mode must not emit real business API requests; unimplemented demo endpoints fail locally before `fetch`.
- No new runtime dependency is required.

---

## File Map

**Create**

- `apps/web/.env.demo` - non-secret Vite demo-mode flags.
- `apps/web/src/demo/clueDemoMode.ts` - secure mode guard and fixed demo administrator.
- `apps/web/src/demo/clueDemoProfile.ts` - counts, aggregate weights, regions, products, and synthetic dictionaries.
- `apps/web/src/demo/clueDemoTypes.ts` - internal generated-graph and repository types.
- `apps/web/src/demo/clueDemoGenerator.ts` - seeded graph generation and invariant validation.
- `apps/web/src/demo/clueDemoRepository.ts` - clue-center and allocation-admin reads, mutations, and CSV generation.
- `tests/test_frontend_clue_demo_mode.py` - controller-level contract tests for the guard, modules, client wiring, UI notice, and documentation.

**Modify**

- `apps/web/package.json` - add `dev:demo` command without adding dependencies.
- `apps/web/src/vite-env.d.ts` - type `VITE_DEMO_MODE`.
- `apps/web/src/api/client.ts` - route supported calls to the demo repository and block accidental network access.
- `apps/web/src/App.tsx` - pass demo state into `Shell` and suppress real logout behavior in demo mode.
- `apps/web/src/components/Shell.tsx` - render the persistent synthetic-data notice.
- `apps/web/src/styles.css` - responsive demo notice and data-workspace height adjustment.
- `apps/web/README.md` - document `npm run dev:demo` and reset behavior.

---

### Task 1: Add the development-only mode and authentication contract

**Files:**

- Create: `apps/web/.env.demo`
- Create: `apps/web/src/demo/clueDemoMode.ts`
- Modify: `apps/web/package.json`
- Modify: `apps/web/src/vite-env.d.ts`
- Create: `tests/test_frontend_clue_demo_mode.py`

**Interfaces:**

- Produces: `isClueDemoMode(env): boolean`
- Produces: `CLUE_DEMO_MODE: boolean`
- Produces: `CLUE_DEMO_ADMIN_USER: AdminUser`
- Later tasks consume `CLUE_DEMO_MODE` in `client.ts`, `App.tsx`, and `Shell.tsx`.

- [ ] **Step 1: Write the failing guard test**

Create `tests/test_frontend_clue_demo_mode.py`:

```python
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
SRC = WEB / "src"


def _read(relative_path: str) -> str:
    return (SRC / relative_path).read_text(encoding="utf-8")


def test_demo_mode_requires_dev_and_explicit_flag() -> None:
    source = _read("demo/clueDemoMode.ts")
    package = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
    demo_env = (WEB / ".env.demo").read_text(encoding="utf-8")

    assert "import.meta.env.DEV" in source
    assert 'VITE_DEMO_MODE === "true"' in source
    assert "CLUE_DEMO_MODE" in source
    assert 'user_id: "DEMO-USER-ADMIN"' in source
    assert 'display_name: "演示最高管理员"' in source
    assert package["scripts"]["dev:demo"] == "vite --host 127.0.0.1 --mode demo"
    assert "VITE_DEMO_MODE=true" in demo_env
    assert "VITE_USE_MOCKS=true" in demo_env
```

- [ ] **Step 2: Run the test and verify the missing files fail**

Run:

```powershell
pytest tests/test_frontend_clue_demo_mode.py::test_demo_mode_requires_dev_and_explicit_flag -q
```

Expected: FAIL with `FileNotFoundError` for `demo/clueDemoMode.ts`.

- [ ] **Step 3: Add the mode module and typed environment**

Create `apps/web/src/demo/clueDemoMode.ts`:

```ts
import type { AdminUser } from "../types/dashboard";

export function isClueDemoMode(
  env: Pick<ImportMetaEnv, "DEV" | "VITE_DEMO_MODE">,
): boolean {
  return env.DEV && env.VITE_DEMO_MODE === "true";
}

export const CLUE_DEMO_MODE = isClueDemoMode(import.meta.env);

export const CLUE_DEMO_ADMIN_USER: AdminUser = {
  username: "demo_admin",
  user_id: "DEMO-USER-ADMIN",
  display_name: "演示最高管理员",
  role: "admin",
  status: "active",
  is_initialized: true,
  store_ids: [],
  is_highest_admin: true,
};
```

Append to `apps/web/src/vite-env.d.ts`:

```ts
interface ImportMetaEnv {
  readonly VITE_DEMO_MODE?: string;
}
```

Create `apps/web/.env.demo`:

```dotenv
VITE_DEMO_MODE=true
VITE_USE_MOCKS=true
```

Add to `apps/web/package.json` scripts:

```json
"dev:demo": "vite --host 127.0.0.1 --mode demo"
```

- [ ] **Step 4: Run the guard test and TypeScript build**

Run:

```powershell
pytest tests/test_frontend_clue_demo_mode.py::test_demo_mode_requires_dev_and_explicit_flag -q
npm run build
```

Working directory for `npm`: `apps/web`.

Expected: pytest PASS; `tsc --noEmit && vite build` exits 0.

- [ ] **Step 5: Commit the security boundary**

```powershell
git add apps/web/.env.demo apps/web/package.json apps/web/src/vite-env.d.ts apps/web/src/demo/clueDemoMode.ts tests/test_frontend_clue_demo_mode.py
git commit -m "feat: add guarded clue demo mode"
```

---

### Task 2: Generate the deterministic synthetic business graph

**Files:**

- Create: `apps/web/src/demo/clueDemoProfile.ts`
- Create: `apps/web/src/demo/clueDemoTypes.ts`
- Create: `apps/web/src/demo/clueDemoGenerator.ts`
- Modify: `tests/test_frontend_clue_demo_mode.py`

**Interfaces:**

- Produces: `CLUE_DEMO_PROFILE`
- Produces: `ClueDemoState`
- Produces: `createClueDemoState(options?: { seed?: number; now?: Date }): ClueDemoState`
- Produces: `assertClueDemoState(state: ClueDemoState): void`
- The repository in Task 3 consumes `ClueDemoState` and `createClueDemoState`.

- [ ] **Step 1: Add the failing generator-contract test**

Append:

```python
def test_demo_generator_has_required_scale_and_privacy_guards() -> None:
    profile = _read("demo/clueDemoProfile.ts")
    generator = _read("demo/clueDemoGenerator.ts")
    types = _read("demo/clueDemoTypes.ts")
    combined = "\n".join([profile, generator, types])

    for required in [
        "leadCount: 480",
        "storeCount: 48",
        "cityCount: 12",
        "oneRoundLeadCount: 230",
        "twoRoundLeadCount: 90",
        "threeRoundLeadCount: 40",
        "directHeadquartersLeadCount: 60",
        "terminalWithoutRoundLeadCount: 60",
        "minimumFollowUpCount: 650",
        "maximumFollowUpCount: 750",
        "createClueDemoState",
        "assertClueDemoState",
        'startsWith("DEMO-")',
    ]:
        assert required in combined

    assert "local_exports" not in combined
    assert "telephone" not in profile.lower()
    assert "follow_life_account_name" not in profile
```

- [ ] **Step 2: Run the test and verify it fails**

```powershell
pytest tests/test_frontend_clue_demo_mode.py::test_demo_generator_has_required_scale_and_privacy_guards -q
```

Expected: FAIL because the profile, types, and generator files do not exist.

- [ ] **Step 3: Define the profile and graph types**

`clueDemoProfile.ts` must export this shape and exact counts:

```ts
export const CLUE_DEMO_PROFILE = {
  seed: 20260717,
  leadCount: 480,
  storeCount: 48,
  cityCount: 12,
  oneRoundLeadCount: 230,
  twoRoundLeadCount: 90,
  threeRoundLeadCount: 40,
  directHeadquartersLeadCount: 60,
  terminalWithoutRoundLeadCount: 60,
  minimumFollowUpCount: 650,
  maximumFollowUpCount: 750,
} as const;

export const DEMO_REGIONS = [
  { province: "广东", city: "深圳", cityCode: "440300", weight: 16 },
  { province: "广东", city: "广州", cityCode: "440100", weight: 12 },
  { province: "河南", city: "郑州", cityCode: "410100", weight: 11 },
  { province: "陕西", city: "西安", cityCode: "610100", weight: 10 },
  { province: "安徽", city: "合肥", cityCode: "340100", weight: 9 },
  { province: "湖北", city: "武汉", cityCode: "420100", weight: 9 },
  { province: "江苏", city: "苏州", cityCode: "320500", weight: 8 },
  { province: "浙江", city: "杭州", cityCode: "330100", weight: 8 },
  { province: "山东", city: "济南", cityCode: "370100", weight: 6 },
  { province: "河北", city: "石家庄", cityCode: "130100", weight: 5 },
  { province: "四川", city: "成都", cityCode: "510100", weight: 4 },
  { province: "福建", city: "福州", cityCode: "350100", weight: 2 },
] as const;

export const DEMO_PRODUCTS = [
  { productId: "DEMO-PRODUCT-MAINT-01", name: "基础保养演示套餐", type: "保养服务" },
  { productId: "DEMO-PRODUCT-MAINT-02", name: "四轮定位演示服务", type: "保养服务" },
  { productId: "DEMO-PRODUCT-WASH-01", name: "精洗护理演示套餐", type: "洗美服务" },
  { productId: "DEMO-PRODUCT-TIRE-01", name: "轮胎安装演示服务", type: "轮胎服务" },
] as const;

export const DEMO_FOLLOW_UP_NOTES = [
  "客户希望周末到店，已确认可联系时间。",
  "已介绍服务内容，客户需要再确认行程。",
  "首次拨打未接通，稍后继续联系。",
  "客户暂不需要本次服务。",
  "客户希望调整到更方便的门店。",
] as const;
```

`clueDemoTypes.ts` must define one state object rather than per-page fixtures:

```ts
import type {
  ClueAllocationAuditLog,
  ClueAllocationCycle,
  ClueAllocationDecision,
  ClueAllocationEligibleLead,
  ClueAllocationRule,
  ClueAllocationRuleVersion,
  ClueAssignmentRound,
  ClueFollowUpRecord,
  ClueHeadquartersPoolEntry,
  ClueOrderDetail,
  StoreScoreSnapshot,
} from "../types/dashboard";

export interface ClueDemoStore {
  store_id: string;
  store_name: string;
  province: string;
  city: string;
  city_code: string;
  latitude: number;
  longitude: number;
}

export interface ClueDemoRuleBundle {
  rule: ClueAllocationRule;
  versions: ClueAllocationRuleVersion[];
}

export interface ClueDemoPreviewToken {
  token: string;
  operation: "trial" | "rebuild";
  leadKeys: string[];
  sourceCycleId: string | null;
  expiresAt: string;
}

export interface ClueDemoState {
  generatedAt: string;
  stores: ClueDemoStore[];
  rounds: ClueAssignmentRound[];
  orderDetails: Record<string, ClueOrderDetail>;
  followUpRecords: ClueFollowUpRecord[];
  eligibleLeads: ClueAllocationEligibleLead[];
  headquartersPool: ClueHeadquartersPoolEntry[];
  cycles: ClueAllocationCycle[];
  auditLogs: ClueAllocationAuditLog[];
  rules: ClueDemoRuleBundle[];
  decisions: ClueAllocationDecision[];
  storeScores: StoreScoreSnapshot[];
  previewTokens: Map<string, ClueDemoPreviewToken>;
  sequence: number;
}
```

- [ ] **Step 4: Build the seeded generator and invariant checks**

Use a local Mulberry32 generator; never use `Math.random()`:

```ts
function createSeededRandom(seed: number): () => number {
  let value = seed >>> 0;
  return () => {
    value += 0x6d2b79f5;
    let next = value;
    next = Math.imul(next ^ (next >>> 15), next | 1);
    next ^= next + Math.imul(next ^ (next >>> 7), next | 61);
    return ((next ^ (next >>> 14)) >>> 0) / 4294967296;
  };
}
```

`createClueDemoState` must generate leads in four deterministic bands:

```ts
function roundCountForAllocatedLead(index: number): 1 | 2 | 3 {
  if (index < 230) return 1;
  if (index < 320) return 2;
  return 3;
}

// 0..359: allocated; 360..419: direct headquarters; 420..479: terminal.
```

For allocated leads:

- Create consecutive `round_no` values and distinct historical stores.
- Make earlier rounds inactive with one of `follow_lost`, `request_store_change`, `timeout`, or `protection_expired` as the transition reason.
- Use the final round/outcome matrix `index % 8` to cover active-unfollowed, active-followed, converted, refunded, expired, failed, exhausted-to-headquarters, and protected states.
- Attach 0-4 records per round. Use this deterministic count and cap to the profile range:

```ts
function followUpCountForRound(roundIndex: number): number {
  if (roundIndex % 11 === 0) return 0;
  return Math.min(
    4,
    1 + (roundIndex % 3 === 0 ? 1 : 0) + (roundIndex % 7 === 0 ? 1 : 0),
  );
}
```

If the first pass is below 650 records, append one additional non-terminal follow-up to active rounds in stable order until 650. If it exceeds 750, remove trailing non-terminal records until 750. Never remove the final `lost` or `request_store_change` record from a historical transition round.

Every order detail reuses the same round and follow-up identifiers used by the top-level arrays. Generate rule bundles, decisions, cycles, scores, and audit rows with `DEMO-` IDs during the same pass.

Call `assertClueDemoState(state)` before returning. It must throw descriptive errors for count, prefix, reference, sequence, and privacy violations:

```ts
function invariant(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`Clue demo invariant failed: ${message}`);
}

export function assertClueDemoState(state: ClueDemoState): void {
  const orderDetails = Object.values(state.orderDetails);
  const roundIds = new Set(state.rounds.map((round) => round.assignment_round_id));
  const storeIds = new Set(state.stores.map((store) => store.store_id));

  invariant(orderDetails.length === CLUE_DEMO_PROFILE.leadCount, "lead count");
  invariant(state.stores.length === CLUE_DEMO_PROFILE.storeCount, "store count");
  invariant(state.rounds.length === 530, "assignment round count");
  invariant(
    state.followUpRecords.length >= CLUE_DEMO_PROFILE.minimumFollowUpCount &&
      state.followUpRecords.length <= CLUE_DEMO_PROFILE.maximumFollowUpCount,
    "follow-up count",
  );
  invariant(
    state.stores.every((store) =>
      store.store_id.startsWith("DEMO-") && store.store_name.includes("演示门店"),
    ),
    "synthetic stores",
  );
  invariant(
    state.followUpRecords.every(
      (record) => roundIds.has(record.assignment_round_id) &&
        (!record.assigned_store_id || storeIds.has(record.assigned_store_id)),
    ),
    "follow-up references",
  );
  invariant(
    state.rounds.every((round) =>
      round.assignment_round_id.startsWith("DEMO-") &&
      round.order_id.startsWith("DEMO-"),
    ),
    "identifier prefixes",
  );
}
```

- [ ] **Step 5: Run the generator contract and build**

```powershell
pytest tests/test_frontend_clue_demo_mode.py::test_demo_generator_has_required_scale_and_privacy_guards -q
npm run build
```

Expected: PASS and build exit 0.

- [ ] **Step 6: Commit the generator**

```powershell
git add apps/web/src/demo/clueDemoProfile.ts apps/web/src/demo/clueDemoTypes.ts apps/web/src/demo/clueDemoGenerator.ts tests/test_frontend_clue_demo_mode.py
git commit -m "feat: generate synthetic clue demo graph"
```

---

### Task 3: Add coherent clue-center reads

**Files:**

- Create: `apps/web/src/demo/clueDemoRepository.ts`
- Modify: `tests/test_frontend_clue_demo_mode.py`

**Interfaces:**

- Produces singleton: `clueDemoRepository`
- Produces reads: `getFilters`, `getOverview`, `getAssignmentRounds`, `getOrderDetail`, `getOrderPhone`
- Produces helper: `reset(): void`
- Later tasks add mutations and admin methods to the same class.

- [ ] **Step 1: Add the failing repository-read test**

Append:

```python
def test_demo_repository_exposes_coherent_clue_center_reads() -> None:
    source = _read("demo/clueDemoRepository.ts")
    for name in [
        "class ClueDemoRepository",
        "getFilters(",
        "getOverview(",
        "getAssignmentRounds(",
        "getOrderDetail(",
        "getOrderPhone(",
        "filterRounds(",
        "paginate(",
        "reset(",
        'source: "demo"',
    ]:
        assert name in source
```

- [ ] **Step 2: Run it and verify failure**

```powershell
pytest tests/test_frontend_clue_demo_mode.py::test_demo_repository_exposes_coherent_clue_center_reads -q
```

Expected: FAIL because `clueDemoRepository.ts` does not exist.

- [ ] **Step 3: Create the repository shell and response helpers**

Use exact public method signatures:

```ts
export interface ClueDemoRoundQuery {
  filters: ClueOverviewFilters;
  page: number;
  pageSize: number;
}

export class ClueDemoRepositoryError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ClueDemoRepositoryError";
  }
}

export class ClueDemoRepository {
  private state = createClueDemoState();

  reset(): void {
    this.state = createClueDemoState();
  }

  getFilters(): ApiResponse<ClueFilterMetadata>;
  getOverview(filters: ClueOverviewFilters): ApiResponse<ClueOverviewMetrics>;
  getAssignmentRounds(query: ClueDemoRoundQuery): ApiResponse<ClueAssignmentRoundData>;
  getOrderDetail(orderId: string): ApiResponse<ClueOrderDetail>;
  getOrderPhone(orderId: string): ApiResponse<CluePhoneReveal>;
}

export const clueDemoRepository = new ClueDemoRepository();
```

Define reusable helpers:

```ts
function demoResponse<T>(data: T, generatedAt: string): ApiResponse<T> {
  return { data: structuredClone(data), meta: { generated_at: generatedAt, source: "demo" } };
}

function paginate<T>(rows: T[], page: number, pageSize: number) {
  const safeSize = Math.max(1, Math.min(Math.floor(pageSize) || 20, 100));
  const totalPages = Math.max(1, Math.ceil(rows.length / safeSize));
  const safePage = Math.max(1, Math.min(Math.floor(page) || 1, totalPages));
  const start = (safePage - 1) * safeSize;
  return {
    rows: rows.slice(start, start + safeSize),
    pagination: { page: safePage, page_size: safeSize, total: rows.length, total_pages: totalPages },
  };
}
```

`filterRounds` must apply every existing `ClueOverviewFilters` field. Resolve province/city through the assigned store map; date filters compare the `YYYY-MM-DD` part of `assigned_at`. Overview metrics must derive from the filtered rows, matching the existing backend's round-level counting semantics.

`getOrderDetail` throws `ClueDemoRepositoryError(404, "演示线索不存在")` for an unknown order. `getOrderPhone` returns the non-callable synthetic value derived from the order sequence.

- [ ] **Step 4: Run repository test and build**

```powershell
pytest tests/test_frontend_clue_demo_mode.py::test_demo_repository_exposes_coherent_clue_center_reads -q
npm run build
```

Expected: PASS and build exit 0.

- [ ] **Step 5: Commit clue-center reads**

```powershell
git add apps/web/src/demo/clueDemoRepository.ts tests/test_frontend_clue_demo_mode.py
git commit -m "feat: add clue demo read repository"
```

---

### Task 4: Add follow-up mutations, round transitions, and demo CSV export

**Files:**

- Modify: `apps/web/src/demo/clueDemoRepository.ts`
- Modify: `tests/test_frontend_clue_demo_mode.py`

**Interfaces:**

- Produces: `saveFollowUp(orderId, payload): ApiResponse<ClueFollowUpRecord>`
- Produces: `deleteFollowUpRecord(id): ApiResponse<ClueFollowUpRecord>`
- Produces: `exportAssignmentRounds(filters): ClueDemoExportFile`
- Produces transition helper: `advanceAfterRoundFailure(orderId, round, reason): void`

- [ ] **Step 1: Add failing mutation-contract tests**

Append:

```python
def test_demo_repository_models_follow_up_and_round_transitions() -> None:
    source = _read("demo/clueDemoRepository.ts")
    for value in [
        "saveFollowUp(",
        "deleteFollowUpRecord(",
        "advanceAfterRoundFailure(",
        "exportAssignmentRounds(",
        'payload.follow_result === "lost"',
        'payload.follow_result === "request_store_change"',
        'round_effective_status = "inactive"',
        'can_operate_current_round = false',
        "DEMO-PHONE-",
        "demo-clue-assignment-rounds-",
    ]:
        assert value in source
```

- [ ] **Step 2: Verify the new test fails**

```powershell
pytest tests/test_frontend_clue_demo_mode.py::test_demo_repository_models_follow_up_and_round_transitions -q
```

Expected: FAIL on missing mutation methods.

- [ ] **Step 3: Add current-round validation and follow-up append**

`saveFollowUp` must:

1. Find the order detail and referenced round.
2. Reject unknown orders/rounds with status 404.
3. Reject non-current or inoperable rounds with status 409.
4. Append a `DEMO-FOLLOW-UP-*` record to both `state.followUpRecords` and the order detail.
5. For `appointment`, `further_follow_up`, and `unreachable`, set the current round to `active_followed`, set `followed_at`, and set `timing_state` to `protected`.
6. For `lost` and `request_store_change`, make the round inactive, save the reason, and call `advanceAfterRoundFailure`.

Use this branch literally so the controller test protects the two immediate-transition actions:

```ts
if (
  payload.follow_result === "lost" ||
  payload.follow_result === "request_store_change"
) {
  round.round_effective_status = "inactive";
  round.can_operate_current_round = false;
  round.round_status = "failed_pending_reassign";
  round.reassign_reason =
    payload.follow_result === "lost" ? "follow_lost" : "request_store_change";
  this.advanceAfterRoundFailure(orderId, round, round.reassign_reason);
} else {
  round.round_status = "active_followed";
  round.follow_result = payload.follow_result;
  round.followed_at = createdAt;
  round.timing_state = "protected";
}
```

`advanceAfterRoundFailure` chooses the next unused store in the same city and creates a new round with `round_no + 1`. If no unused store exists, it clears current-round pointers and creates a headquarters entry with reason `all_strategies_exhausted`.

`deleteFollowUpRecord` marks the record deleted and records the demo administrator and deletion timestamp; it does not physically remove history.

- [ ] **Step 4: Add filtered demo export**

Return a UTF-8 CSV file object rather than touching the DOM in the repository:

```ts
export interface ClueDemoExportFile {
  filename: string;
  content: string;
  mimeType: "text/csv;charset=utf-8";
}
```

The header must include order ID, round number, status, assigned time, demo store, masked demo phone, product, follow-up result, transition reason, and verification time. Escape quotes and commas; prepend a UTF-8 BOM. Filename:

```text
demo-clue-assignment-rounds-YYYY-MM-DD.csv
```

- [ ] **Step 5: Run focused tests and build**

```powershell
pytest tests/test_frontend_clue_demo_mode.py::test_demo_repository_models_follow_up_and_round_transitions -q
npm run build
```

Expected: PASS and build exit 0.

- [ ] **Step 6: Commit follow-up behavior**

```powershell
git add apps/web/src/demo/clueDemoRepository.ts tests/test_frontend_clue_demo_mode.py
git commit -m "feat: simulate clue follow-up transitions"
```

---

### Task 5: Add allocation-admin reads and browser-session mutations

**Files:**

- Modify: `apps/web/src/demo/clueDemoRepository.ts`
- Modify: `tests/test_frontend_clue_demo_mode.py`

**Interfaces:**

- Produces all read methods used by `AdminClueAllocationPage`.
- Produces preview/trial/rebuild and rule-version mutations with existing dashboard request/response types.
- These methods are consumed by the client branches in Task 6.

Mutation signatures:

```ts
previewCycle(payload: ClueAllocationCyclePreviewRequest): ApiResponse<ClueAllocationCyclePreview>
runTrial(payload: ClueAllocationCycleRequest): ApiResponse<ClueAllocationCycleExecution>
rebuildTrial(payload: ClueAllocationCycleRebuildRequest): ApiResponse<ClueAllocationCycleExecution>
createRule(payload: ClueAllocationRuleCreate): ApiResponse<ClueAllocationRule>
createRuleVersion(
  ruleId: string,
  payload: ClueAllocationRuleVersionWrite,
): ApiResponse<ClueAllocationRuleVersion>
publishRuleVersion(ruleVersionId: string): ApiResponse<ClueAllocationRuleVersion>
retireRuleVersion(ruleVersionId: string): ApiResponse<ClueAllocationRuleVersion>
```

- [ ] **Step 1: Add the failing admin repository test**

Append:

```python
def test_demo_repository_covers_all_allocation_admin_calls() -> None:
    source = _read("demo/clueDemoRepository.ts")
    for method in [
        "getEligibleLeads(",
        "getHeadquartersPool(",
        "getCycles(",
        "getAuditLogs(",
        "previewCycle(",
        "runTrial(",
        "rebuildTrial(",
        "getRules(",
        "getRuleDetail(",
        "getDecisions(",
        "getStoreScores(",
        "createRule(",
        "createRuleVersion(",
        "publishRuleVersion(",
        "retireRuleVersion(",
    ]:
        assert method in source

    for marker in ["DEMO-PREVIEW-", "DEMO-CYCLE-", "DEMO-AUDIT-", "previewTokens"]:
        assert marker in source
```

- [ ] **Step 2: Verify failure**

```powershell
pytest tests/test_frontend_clue_demo_mode.py::test_demo_repository_covers_all_allocation_admin_calls -q
```

Expected: FAIL because the admin methods do not exist.

- [ ] **Step 3: Add read methods with existing response shapes**

Define the repository-owned filter type so it does not import the private `QueryParams` alias from `client.ts`:

```ts
export interface ClueDemoHeadquartersFilters {
  pool_status?: string;
  reason?: string;
  entered_date_start?: string;
  entered_date_end?: string;
  order_status?: string;
  order_id?: string;
  page?: number;
  page_size?: number;
}
```

Implement exact methods:

```ts
getEligibleLeads(): ApiResponse<ClueAllocationEligibleLeadData>
getHeadquartersPool(filters: ClueDemoHeadquartersFilters): ApiResponse<ClueHeadquartersPoolData>
getCycles(): ApiResponse<ClueAllocationCycleData>
getAuditLogs(): ApiResponse<ClueAllocationAuditLogData>
getRules(): ApiResponse<ClueAllocationRuleListData>
getRuleDetail(ruleId: string): ApiResponse<ClueAllocationRuleDetailData>
getDecisions(): ApiResponse<ClueAllocationDecisionData>
getStoreScores(): ApiResponse<StoreScoreSnapshotData>
```

Headquarters filtering must support status, reason, entered-date range, order status, order ID, page, and page size. Populate `summary.current_inventory`, `summary.filtered_total`, and all filter option arrays.

- [ ] **Step 4: Add preview, trial, and rebuild mutations**

`previewCycle` stores a five-minute token in `state.previewTokens` and returns the selected active lead count. `runTrial` requires a matching unexpired token and `confirm: true`, then:

- Creates a `DEMO-CYCLE-*` row.
- Creates allocation decisions and successful rounds for selected eligible leads.
- Updates each affected order detail and the clue-center round list with the same new round object and current-round pointers.
- Removes those leads from the eligible list.
- Adds `DEMO-AUDIT-*` evidence.
- Returns counts in the existing `ClueAllocationCycleExecution` shape.

`rebuildTrial` additionally requires `source_cycle_id`, a rebuild preview token, `confirm: true`, and `privileged_confirmation: true`. It creates a child cycle, leaves the source cycle in history, and appends superseding decisions without deleting prior evidence.

Invalid, expired, or mismatched preview tokens throw status 409; missing confirmation throws 422.

- [ ] **Step 5: Add in-memory rule lifecycle mutations**

Use the existing write payload types. Rules and versions receive monotonic `DEMO-RULE-*` and `DEMO-RULE-VERSION-*` IDs.

- `createRule` creates a rule with no versions.
- `createRuleVersion` appends a draft with `version_no = max + 1`.
- `publishRuleVersion` retires any currently published version for the same rule and publishes the selected draft.
- `retireRuleVersion` marks the selected published version retired.
- All four operations append audit rows and update timestamps.
- Unknown IDs return 404; invalid lifecycle transitions return 409.

- [ ] **Step 6: Run focused tests and build**

```powershell
pytest tests/test_frontend_clue_demo_mode.py::test_demo_repository_covers_all_allocation_admin_calls -q
npm run build
```

Expected: PASS and build exit 0.

- [ ] **Step 7: Commit allocation-admin behavior**

```powershell
git add apps/web/src/demo/clueDemoRepository.ts tests/test_frontend_clue_demo_mode.py
git commit -m "feat: simulate clue allocation admin flows"
```

---

### Task 6: Wire the API client and automatic demo session

**Files:**

- Modify: `apps/web/src/api/client.ts`
- Modify: `apps/web/src/App.tsx`
- Modify: `tests/test_frontend_clue_demo_mode.py`

**Interfaces:**

- Consumes: `CLUE_DEMO_MODE`, `CLUE_DEMO_ADMIN_USER`, and `clueDemoRepository`.
- Preserves every existing exported client function signature.
- Produces `usingMock: true` and `fallbackReason: "当前展示合成演示数据。"` for demo responses.

- [ ] **Step 1: Add the failing integration test**

Append:

```python
def test_client_routes_clue_and_admin_calls_without_demo_network() -> None:
    client = _read("api/client.ts")
    app = _read("App.tsx")

    for value in [
        "CLUE_DEMO_MODE",
        "CLUE_DEMO_ADMIN_USER",
        "clueDemoRepository",
        "demoLoad",
        "blockDemoNetwork",
        'fallbackReason: "当前展示合成演示数据。"',
        "clueDemoRepository.getAssignmentRounds",
        "clueDemoRepository.saveFollowUp",
        "clueDemoRepository.getHeadquartersPool",
        "clueDemoRepository.previewCycle",
        "clueDemoRepository.runTrial",
        "clueDemoRepository.getRules",
    ]:
        assert value in client

    assert "isDemoMode={CLUE_DEMO_MODE}" in app
    assert "CLUE_DEMO_MODE ? undefined : onLogout" in app
```

- [ ] **Step 2: Verify failure**

```powershell
pytest tests/test_frontend_clue_demo_mode.py::test_client_routes_clue_and_admin_calls_without_demo_network -q
```

Expected: FAIL because client and App are not wired.

- [ ] **Step 3: Add reusable demo wrappers and local network block**

At the top of `client.ts`, import the mode, admin user, repository, and repository error. Change the existing mock flag:

```ts
const USE_MOCKS =
  CLUE_DEMO_MODE || import.meta.env.VITE_USE_MOCKS === "true";
```

Add:

```ts
function demoLoad<T>(factory: () => ApiResponse<T>): Promise<ApiLoadResult<T>> {
  try {
    return Promise.resolve({
      ...factory(),
      usingMock: true,
      fallbackReason: "当前展示合成演示数据。",
    });
  } catch (error) {
    if (error instanceof ClueDemoRepositoryError) {
      return Promise.reject(new ApiRequestError(error.status, error.message));
    }
    return Promise.reject(error);
  }
}

function blockDemoNetwork(): void {
  if (CLUE_DEMO_MODE) {
    throw new ApiRequestError(503, "演示模式未提供该接口，已阻止真实网络请求。");
  }
}
```

Call `blockDemoNetwork()` at the beginning of `requestJson`, `sendJson`, and `requestDownload`. Supported demo branches return before those helpers are called.

- [ ] **Step 4: Branch every clue-center and allocation-admin client function**

Use this pattern without changing function signatures:

```ts
export function fetchClueAssignmentRounds(
  query: ClueRoundQuery,
): Promise<ApiLoadResult<ClueAssignmentRoundData>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => clueDemoRepository.getAssignmentRounds(query));
  }
  return withMockFallback(/* existing real and legacy mock branches */);
}
```

Add these explicit client-to-repository mappings:

```text
fetchClueFilters                    -> getFilters
fetchClueOverview                   -> getOverview
fetchClueAssignmentRounds           -> getAssignmentRounds
fetchClueOrderDetail                -> getOrderDetail
fetchClueOrderPhone                 -> getOrderPhone
saveClueFollowUp                    -> saveFollowUp
deleteClueFollowUpRecord            -> deleteFollowUpRecord
exportClueAssignmentRounds          -> exportAssignmentRounds
fetchClueAllocationEligibleLeads    -> getEligibleLeads
fetchClueHeadquartersPool           -> getHeadquartersPool
fetchClueAllocationCycles           -> getCycles
fetchClueAllocationAuditLogs        -> getAuditLogs
previewClueAllocationCycle          -> previewCycle
runClueAllocationTrial              -> runTrial
rebuildClueAllocationTrial          -> rebuildTrial
fetchClueAllocationRules            -> getRules
fetchClueAllocationRuleDetail       -> getRuleDetail
fetchClueAllocationDecisions        -> getDecisions
fetchClueAllocationStoreScores      -> getStoreScores
createClueAllocationRule            -> createRule
createClueAllocationRuleVersion     -> createRuleVersion
publishClueAllocationRuleVersion    -> publishRuleVersion
retireClueAllocationRuleVersion     -> retireRuleVersion
```

For `exportClueAssignmentRounds`, obtain the repository file, create a `Blob`, generate an object URL, click a temporary download anchor, and revoke the URL.

For auth:

```ts
export async function fetchAdminSession(): Promise<ApiLoadResult<AdminUser>> {
  if (CLUE_DEMO_MODE) {
    return demoLoad(() => ({
      data: CLUE_DEMO_ADMIN_USER,
      meta: { generated_at: new Date().toISOString(), source: "demo" },
    }));
  }
  return { ...(await requestJson<AdminUser>("/auth/me")), usingMock: false };
}
```

Apply the same demo identity to `loginAdmin` and `logoutAdmin` so no auth request can escape if those functions are called during a demo session.

- [ ] **Step 5: Pass demo mode into both Shell render paths**

Import `CLUE_DEMO_MODE` in `App.tsx`. For both admin and non-admin `Shell` instances:

```tsx
<Shell
  currentPath={location.pathname}
  currentUser={user}
  isDemoMode={CLUE_DEMO_MODE}
  onLogout={CLUE_DEMO_MODE ? undefined : onLogout}
>
```

- [ ] **Step 6: Run integration test and builds in normal and demo modes**

```powershell
pytest tests/test_frontend_clue_demo_mode.py::test_client_routes_clue_and_admin_calls_without_demo_network -q
npm run build
npm run build -- --mode demo
```

Expected: test PASS; both builds exit 0. The demo-mode production build still compiles with `import.meta.env.DEV === false` and therefore cannot auto-authenticate.

- [ ] **Step 7: Commit client integration**

```powershell
git add apps/web/src/api/client.ts apps/web/src/App.tsx tests/test_frontend_clue_demo_mode.py
git commit -m "feat: route clue pages through demo repository"
```

---

### Task 7: Add persistent demo disclosure and local-run documentation

**Files:**

- Modify: `apps/web/src/components/Shell.tsx`
- Modify: `apps/web/src/styles.css`
- Modify: `apps/web/README.md`
- Modify: `tests/test_frontend_clue_demo_mode.py`

**Interfaces:**

- `ShellProps` gains optional `isDemoMode?: boolean`.
- `App.tsx` already supplies the flag from Task 6.

- [ ] **Step 1: Add the failing UI disclosure test**

Append:

```python
def test_shell_discloses_demo_data_on_desktop_and_mobile() -> None:
    shell = _read("components/Shell.tsx")
    styles = _read("styles.css")
    readme = (WEB / "README.md").read_text(encoding="utf-8")

    assert "isDemoMode?: boolean" in shell
    assert "演示数据 · 全部为合成数据 · 不写入数据库" in shell
    assert "demo-mode-notice" in shell
    assert ".demo-mode-notice" in styles
    assert ".app-shell--demo" in styles
    assert "npm run dev:demo" in readme
    assert "刷新页面后恢复" in readme
```

- [ ] **Step 2: Verify failure**

```powershell
pytest tests/test_frontend_clue_demo_mode.py::test_shell_discloses_demo_data_on_desktop_and_mobile -q
```

Expected: FAIL because Shell and README lack the notice.

- [ ] **Step 3: Add the Shell notice**

Extend `ShellProps` and root class:

```tsx
interface ShellProps {
  currentPath: string;
  currentUser?: AdminUser | null;
  isDemoMode?: boolean;
  onLogout?: () => void;
  children: ReactNode;
}

const shellClassName = isDemoMode
  ? "app-shell app-shell--rail app-shell--demo"
  : "app-shell app-shell--rail";
```

Render directly after the top bar/mobile subnav and before `<main>`:

```tsx
{isDemoMode ? (
  <div className="demo-mode-notice" role="note">
    <SolarIcon name="info" size={16} />
    <span>演示数据 · 全部为合成数据 · 不写入数据库</span>
    <small>操作仅在当前浏览器会话生效，刷新后重置</small>
  </div>
) : null}
```

- [ ] **Step 4: Add restrained responsive styling**

Add styles near workspace top-bar rules:

```css
.demo-mode-notice {
  display: flex;
  min-height: 34px;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid #f2c879;
  padding: 6px 28px;
  background: #fff7e6;
  color: #6f4300;
  font-size: 12px;
  font-weight: 700;
}

.demo-mode-notice small {
  color: #8a641d;
  font-weight: 500;
}

.app-shell--demo .workspace-shell .page-frame--data-workspace {
  height: calc(100vh - var(--workspace-topbar-height) - 34px);
}
```

Add these exact rules inside the existing `@media (max-width: 640px)` block:

```css
.demo-mode-notice {
  min-height: 0;
  align-items: flex-start;
  padding: 8px 16px;
  line-height: 1.4;
}

.demo-mode-notice small {
  display: none;
}

.app-shell--demo .workspace-shell .page-frame--data-workspace {
  height: auto;
}
```

- [ ] **Step 5: Document startup and reset semantics**

Add to `apps/web/README.md`:

````markdown
### 线索分配演示模式

```powershell
npm run dev:demo
```

演示模式仅在 Vite 开发环境生效，自动使用“演示最高管理员”和合成线索数据，不连接真实业务 API。跟进、试运行、重建和规则操作只修改浏览器内存，刷新页面后恢复初始数据。
````

- [ ] **Step 6: Run UI contract, full demo test file, and build**

```powershell
pytest tests/test_frontend_clue_demo_mode.py -q
npm run build
```

Expected: all demo controller tests PASS and build exits 0.

- [ ] **Step 7: Commit disclosure and documentation**

```powershell
git add apps/web/src/components/Shell.tsx apps/web/src/styles.css apps/web/README.md tests/test_frontend_clue_demo_mode.py
git commit -m "feat: label synthetic clue demo data"
```

---

### Task 8: Run complete automated and browser verification

**Files:**

- Verify: all files from Tasks 1-7
- Generate ignored artifacts: `local_exports/clue-demo-preview/`

**Interfaces:** None. This is the release gate.

- [ ] **Step 1: Confirm repository scope before testing**

```powershell
git status --short
git diff --check 873bcbf..HEAD
```

Expected: no unrelated modifications; no whitespace errors.

- [ ] **Step 2: Run focused and full automated checks**

```powershell
pytest tests/test_frontend_clue_demo_mode.py -q
pytest tests/test_frontend_clue_center.py tests/test_frontend_clue_allocation_m3.py -q
pytest -q
npm run build
npm run build -- --mode demo
```

Working directory for `npm`: `apps/web`.

Expected: all pytest suites PASS; both builds exit 0.

- [ ] **Step 3: Start the demo server on an available port**

From `apps/web`:

```powershell
npm run dev:demo -- --port 4173
```

If port 4173 is occupied, select the next free port and record it. Keep the server running through browser verification.

- [ ] **Step 4: Verify no real API request escapes**

Using Playwright request listeners, open `/clues` and each allocation-admin route. Assert no request URL contains `/api/v1/`. Console errors and unhandled page errors must be empty.

- [ ] **Step 5: Verify the clue center and multi-round details**

At 1440x900:

- Open `/clues` and confirm the persistent demo notice.
- Confirm hundreds of rows through pagination and a non-zero overview.
- Filter by store, city, product, and status; confirm totals change coherently.
- Open a three-round lead and verify ordered round history plus multiple follow-up records.
- Add a non-terminal follow-up and confirm the detail and list status update.
- Add a lost/change-store follow-up on another current lead and confirm a new round appears.
- Export CSV and confirm filename begins `demo-clue-assignment-rounds-`.

- [ ] **Step 6: Verify allocation admin flows**

Open and exercise:

- `/admin/clue-allocation/rules`
- `/admin/clue-allocation/trial`
- `/admin/clue-allocation/records`
- `/admin/clue-allocation/headquarters`

Confirm trial preview and execution update cycles/decisions, headquarters filters work, rules can create/publish/retire in memory, and a browser refresh restores the initial counts.

- [ ] **Step 7: Verify mobile layout**

At 390x844, check `/clues`, one multi-round detail, `/admin/clue-allocation/records`, and `/admin/clue-allocation/headquarters`. Confirm no text overlap, clipped controls, horizontal page overflow, or hidden demo disclosure.

- [ ] **Step 8: Save evidence and stop the server**

Save screenshots to:

```text
local_exports/clue-demo-preview/clue-center-desktop.png
local_exports/clue-demo-preview/multi-round-detail-desktop.png
local_exports/clue-demo-preview/allocation-records-desktop.png
local_exports/clue-demo-preview/headquarters-desktop.png
local_exports/clue-demo-preview/clue-center-mobile.png
```

Stop the development server after screenshots and request checks complete. These files remain ignored and are not committed.

- [ ] **Step 9: Record final repository state**

```powershell
git status --short
git log -7 --oneline
```

Expected: clean tracked worktree; implementation commits visible; only ignored screenshot artifacts remain.

---

## Completion Gate

The work is complete only when:

1. `npm run dev:demo` opens the existing app without a backend or real credentials.
2. The clue center and allocation admin use one coherent 480-lead synthetic graph.
3. About 530 rounds and 650-750 follow-up records render with valid historical transitions.
4. Follow-up, trial, rebuild, rule, and export actions work in memory and reset on refresh.
5. No production API request occurs in demo mode.
6. Normal and demo-mode production builds preserve the real authentication boundary.
7. Automated tests, desktop checks, mobile checks, console checks, and screenshots all pass.
