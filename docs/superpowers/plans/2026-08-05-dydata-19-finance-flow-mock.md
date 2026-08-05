# DYDATA-19 Finance Flow Mock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a browser-operable React Mock that demonstrates the confirmed DYDATA-19 store-side and finance-side monthly billing, dispute, invoicing, SAP, import, settlement, and next-period adjustment flows.

**Architecture:** Create a standalone Vite + React prototype under `docs/prototypes/dydata-19-finance-flow-dashboard/` so production APIs and pages remain untouched. Keep business calculations in pure functions, put realistic fixtures in a separate data module, compose stable route-like views inside one demo shell, and verify domain behavior with Vitest plus end-to-end interaction with Playwright CLI.

**Tech Stack:** React 19, Vite, JavaScript/JSX, Vitest, Testing Library, Iconify Solar icons, CSS custom properties, Playwright CLI.

## Global Constraints

- The source of truth is `docs/superpowers/specs/2026-08-05-dydata-19-finance-flow-mock-design.md`.
- “财务” means `财务（系统权限：管理员角色）`; do not introduce an independent finance role.
- Use “账单确认” in store-facing copy; “锁账” is internal compatibility wording only.
- Auto-confirm is 6th 24:00 and invoice cutoff is 10th 24:00; holidays do not shift either deadline.
- One disputed fee direction is entirely unconfirmed; the other direction remains independent.
- Audit approval means full payment and the final state is “审核通过，已结算”; no partial settlement state.
- A failed external audit always means red-flush and reissue; do not collect red invoice number or completion time.
- Main lists show only `有效 SAP`; source values remain in detail/history.
- Imports are atomic; one invalid row fails the whole batch.
- Paid results never roll back; recompute differences enter the next period.
- Use the existing dy-data V0.2.1 palette, light/dark semantic tokens, visible focus, 44px touch targets, and reduced-motion support.
- Do not call real APIs, write a database, verify invoices externally, or modify production runtime pages.

---

### Task 1: Prototype scaffold and finance domain rules

**Files:**
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/package.json`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/vite.config.mjs`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/index.html`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/main.jsx`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/domain/financeRules.test.js`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/domain/financeRules.js`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/data/financeData.js`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/AGENTS.md`

**Interfaces:**
- Consumes: confirmed rules from the design spec.
- Produces: `getConfirmationState`, `getSettlementMonth`, `validateInvoice`, `validateImportBatch`, `getRecomputeOutcome`, `money`, `scenarioFixtures`.

- [ ] **Step 1: Create package configuration and install the test/runtime dependencies**

```json
{
  "name": "dydata-19-finance-flow-dashboard",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "build": "vite build",
    "test": "vitest run"
  }
}
```

Run: `npm install react react-dom @iconify/react @iconify-icons/solar && npm install -D vite @vitejs/plugin-react vitest jsdom @testing-library/react @testing-library/user-event`

Expected: `package-lock.json` is generated and npm exits 0.

- [ ] **Step 2: Write failing domain tests**

```js
import { describe, expect, it } from "vitest";
import {
  getConfirmationState,
  getRecomputeOutcome,
  getSettlementMonth,
  validateImportBatch,
  validateInvoice,
} from "./financeRules.js";

describe("DYDATA-19 finance rules", () => {
  it("auto-confirms on the sixth at 24:00 when no blocker exists", () => {
    expect(getConfirmationState({ day: 7, confirmed: false, disputed: false, systemBlocked: false })).toBe("已确认");
  });

  it("keeps an entire disputed direction unconfirmed", () => {
    expect(getConfirmationState({ day: 7, confirmed: false, disputed: true, systemBlocked: false })).toBe("异议处理中");
  });

  it("uses submission success time for settlement month", () => {
    expect(getSettlementMonth("2026-08-10T23:59:59+08:00")).toBe("2026-08");
    expect(getSettlementMonth("2026-08-11T00:00:00+08:00")).toBe("2026-09");
  });

  it("rejects the wrong buyer, tax rate, number or amount", () => {
    const errors = validateInvoice({ buyer: "其他公司", taxRate: 3, invoiceNumber: "123", total: 99, expectedTotal: 100 });
    expect(errors).toHaveLength(4);
  });

  it("fails an import batch atomically", () => {
    expect(validateImportBatch([{ invoiceNumber: "12345678901234567890", valid: true }, { invoiceNumber: "bad", valid: false }])).toEqual({ ok: false, accepted: 0, rejected: 2 });
  });

  it("moves paid recompute differences to the next period", () => {
    expect(getRecomputeOutcome({ paid: true, before: 1000, after: 900 })).toMatchObject({ rollback: false, adjustment: -100 });
  });
});
```

- [ ] **Step 3: Run the tests and confirm RED**

Run: `npm test -- src/domain/financeRules.test.js`

Expected: FAIL because `financeRules.js` does not exist or its exports are missing.

- [ ] **Step 4: Implement the smallest pure-rule module and fixture module**

```js
export function getConfirmationState({ day, confirmed, disputed, systemBlocked }) {
  if (systemBlocked) return "系统异常，待修复";
  if (disputed) return "异议处理中";
  if (confirmed || day > 6) return "已确认";
  return "待确认";
}

export function getSettlementMonth(submittedAt) {
  const date = new Date(submittedAt);
  const shanghaiDay = Number(new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", day: "2-digit" }).format(date));
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit" }).formatToParts(date);
  const year = Number(parts.find((part) => part.type === "year").value);
  const month = Number(parts.find((part) => part.type === "month").value);
  const target = new Date(Date.UTC(year, month - 1 + (shanghaiDay > 10 ? 1 : 0), 1));
  return `${target.getUTCFullYear()}-${String(target.getUTCMonth() + 1).padStart(2, "0")}`;
}

export function validateInvoice(invoice) {
  return [
    invoice.buyer === "比亚迪汽车销售有限公司" ? null : "发票对象开具错误，请检查开具至【比亚迪汽车销售有限公司】发票",
    invoice.taxRate === 6 ? null : "发票税率错误，请开具6%税率的推广服务费发票至比亚迪汽车销售有限公司",
    /^\d{20}$/.test(invoice.invoiceNumber) ? null : "数电专票号码需要是20位纯数字",
    invoice.total === invoice.expectedTotal ? null : "价税合计需要与所选账期的已确认金额一致",
  ].filter(Boolean);
}

export function validateImportBatch(rows) {
  const ok = rows.length > 0 && rows.every((row) => row.valid);
  return { ok, accepted: ok ? rows.length : 0, rejected: ok ? 0 : rows.length };
}

export function getRecomputeOutcome({ paid, before, after }) {
  return { rollback: false, notifyStore: !paid && before !== after, adjustment: after - before };
}

export const money = (value) => new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(value);
```

`financeData.js` exports `scenarioFixtures` keyed by `F01` through `F10`; every fixture contains `title`, `summary`, `role`, `page`, `notice`, and the affected business record so the scenario switcher can update the whole page consistently.

- [ ] **Step 5: Run domain tests and confirm GREEN**

Run: `npm test -- src/domain/financeRules.test.js`

Expected: all six tests pass.

- [ ] **Step 6: Commit Task 1**

```powershell
git add docs/prototypes/dydata-19-finance-flow-dashboard
git commit -m "feat: add DYDATA-19 finance mock domain"
```

### Task 2: Store-side monthly bill and invoicing journey

**Files:**
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/App.test.jsx`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/App.jsx`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/components/AppShell.jsx`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/components/FinanceTimeline.jsx`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/components/StatusTag.jsx`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/components/ScenarioSwitcher.jsx`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/pages/StoreBillsPage.jsx`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/pages/StoreInvoicesPage.jsx`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/pages/StoreHistoryPage.jsx`

**Interfaces:**
- Consumes: `scenarioFixtures`, `validateInvoice`, `money`.
- Produces: role-aware app shell, three stable store pages, invoice form validation, hidden dispute entry, F01-F07 scenario actions.

- [ ] **Step 1: Write failing store journey tests**

```jsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "./App.jsx";

describe("store finance journey", () => {
  it("shows separate promotion and management confirmation states", () => {
    render(<App />);
    expect(screen.getByText("推广服务费")).toBeInTheDocument();
    expect(screen.getByText("管理服务费")).toBeInTheDocument();
  });

  it("reveals dispute entry only inside bill details", async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(screen.queryByRole("button", { name: "发起账单异议" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "查看账单详情" }));
    expect(screen.getByRole("button", { name: "发起账单异议" })).toBeInTheDocument();
  });

  it("shows the exact buyer validation guidance", async () => {
    const user = userEvent.setup();
    render(<App initialPage="store-invoices" />);
    await user.click(screen.getByRole("button", { name: "校验并提交发票" }));
    expect(screen.getByText(/发票对象开具错误/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the store tests and confirm RED**

Run: `npm test -- src/App.test.jsx`

Expected: FAIL because `App.jsx` and the store pages do not exist.

- [ ] **Step 3: Implement the store shell and pages**

```jsx
const storePages = {
  "store-bills": { label: "月度账单", Component: StoreBillsPage },
  "store-invoices": { label: "推广服务费开票", Component: StoreInvoicesPage },
  "store-history": { label: "发票与调整记录", Component: StoreHistoryPage },
};

export function App({ initialRole = "store", initialPage = "store-bills" }) {
  const [role, setRole] = useState(initialRole);
  const [page, setPage] = useState(initialPage);
  const [scenarioId, setScenarioId] = useState("F01");
  const pages = role === "store" ? storePages : financePages;
  const ActivePage = pages[page]?.Component ?? Object.values(pages)[0].Component;

  return (
    <AppShell role={role} page={page} pages={pages} onRoleChange={setRole} onPageChange={setPage}>
      <FinanceTimeline scenario={scenarioFixtures[scenarioId]} />
      <ScenarioSwitcher value={scenarioId} onChange={setScenarioId} />
      <ActivePage scenario={scenarioFixtures[scenarioId]} />
    </AppShell>
  );
}
```

`StoreBillsPage` keeps `showDetail` local state so “发起账单异议” is absent until “查看账单详情” is used. `StoreInvoicesPage` keeps visible labels for all five fields, calls `validateInvoice` on “校验并提交发票”, and renders every returned error in an `aria-live="polite"` region. `StoreHistoryPage` renders promotion invoice history, management invoice number/amount/time, dispute history, and next-period adjustments without attachment/download controls.

- [ ] **Step 4: Run the store tests and confirm GREEN**

Run: `npm test -- src/App.test.jsx`

Expected: store journey tests pass.

- [ ] **Step 5: Commit Task 2**

```powershell
git add docs/prototypes/dydata-19-finance-flow-dashboard/src
git commit -m "feat: build store finance mock journey"
```

### Task 3: Finance pages, disputes, SAP differences and imports

**Files:**
- Modify: `docs/prototypes/dydata-19-finance-flow-dashboard/src/App.test.jsx`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/components/DataWorkbench.jsx`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/components/ImportDialog.jsx`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/pages/FinanceHomePage.jsx`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/pages/FinancePromotionPage.jsx`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/pages/FinanceManagementPage.jsx`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/pages/FinanceDisputesPage.jsx`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/pages/FinanceImportsPage.jsx`

**Interfaces:**
- Consumes: finance fixtures and domain validators.
- Produces: four finance secondary pages, two dispute tertiary pages, atomic import preview, SAP resolution, audit-result update, F08-F10 scenario actions.

- [ ] **Step 1: Add failing finance tests**

```jsx
it("keeps operational totals on secondary pages instead of finance home", async () => {
  const user = userEvent.setup();
  render(<App initialRole="finance" />);
  expect(screen.queryByText("审核未通过金额")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "推广服务费" }));
  expect(screen.getByText("审核未通过金额")).toBeInTheDocument();
});

it("fails an import preview as one batch", async () => {
  const user = userEvent.setup();
  render(<App initialRole="finance" initialPage="finance-imports" />);
  await user.click(screen.getByRole("button", { name: "演示含错误批次" }));
  expect(screen.getByText("整批校验失败，未写入任何记录")).toBeInTheDocument();
});

it("shows only effective SAP in the main list", () => {
  render(<App initialRole="finance" initialPage="finance-disputes" />);
  expect(screen.getByRole("columnheader", { name: "有效 SAP" })).toBeInTheDocument();
  expect(screen.queryByRole("columnheader", { name: "门店 SAP" })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the finance tests and confirm RED**

Run: `npm test -- src/App.test.jsx`

Expected: the new finance assertions fail because the pages and actions are missing.

- [ ] **Step 3: Implement finance home and four secondary pages**

```jsx
const financePages = {
  "finance-home": { label: "财务", Component: FinanceHomePage },
  "finance-promotion": { label: "推广服务费", Component: FinancePromotionPage },
  "finance-management": { label: "管理服务费", Component: FinanceManagementPage },
  "finance-disputes": { label: "账单异议", Component: FinanceDisputesPage },
  "finance-imports": { label: "导入记录", Component: FinanceImportsPage },
};

function ImportDialog({ rows, onClose }) {
  const result = validateImportBatch(rows);
  return (
    <dialog open aria-labelledby="import-title">
      <h2 id="import-title">导入校验结果</h2>
      <p role="status">{result.ok ? `整批校验通过，可写入 ${result.accepted} 条记录` : "整批校验失败，未写入任何记录"}</p>
      <button type="button" onClick={onClose}>返回导入记录</button>
    </dialog>
  );
}
```

`FinanceHomePage` renders only the four page entrances and explanatory copy. Promotion and management pages render their confirmed metric sets and full field tables. `FinanceDisputesPage` uses stable “SAP 编码异议 / 账单金额异议” tertiary navigation; the main SAP table exposes only “有效 SAP”, while its detail drawer contains source values and history. `FinanceImportsPage` exposes four import types and uses `ImportDialog` for same-content, overwrite-preview, atomic-failure and success outcomes.

- [ ] **Step 4: Run all prototype tests and confirm GREEN**

Run: `npm test`

Expected: domain and UI tests pass with zero failures.

- [ ] **Step 5: Commit Task 3**

```powershell
git add docs/prototypes/dydata-19-finance-flow-dashboard/src
git commit -m "feat: build finance operations mock pages"
```

### Task 4: Visual system, responsive QA, browser evidence and delivery handoff

**Files:**
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/src/styles.css`
- Create: `docs/prototypes/dydata-19-finance-flow-dashboard/design-qa.md`
- Create: `src/frontend/page-preview/page-delivery-dydata-19-finance-flow.md`
- Create: `src/frontend/page-preview/screenshots/dydata-19-finance-desktop.png`
- Create: `src/frontend/page-preview/screenshots/dydata-19-finance-tablet.png`
- Create: `src/frontend/page-preview/screenshots/dydata-19-finance-mobile.png`
- Modify: `docs/plans/execution-plan.md`
- Modify: `docs/devlog/20260804_refactor_log_Keith_Chen.md`

**Interfaces:**
- Consumes: all prototype pages and V0.2.1 tokens.
- Produces: responsive light/dark presentation, verified local route, screenshots, page delivery record, governance writeback.

- [ ] **Step 1: Run the design knowledge search and persist prototype-local guidance**

Run:

```powershell
python .agent/project-manager-suite/skills/03-02-page-designer/scripts/search.py "financial operations admin dashboard dense table workflow" --design-system --persist -p "dy-data" --output-dir "docs/prototypes/dydata-19-finance-flow-dashboard"
python .agent/project-manager-suite/skills/03-02-page-designer/scripts/search.py "responsive data table form accessibility" --stack react
```

Expected: no `warning: no match`; a prototype-local `design-system/dy-data/MASTER.md` is generated.

- [ ] **Step 2: Add the V0.2.1 visual and responsive layer**

```css
:root {
  color-scheme: light;
  --page: #f6f6f3;
  --surface: #ffffff;
  --surface-subtle: #f2f2ee;
  --text: #181818;
  --muted: #686a66;
  --line: #e3e3df;
  --brand: #d63b00;
  --brand-accent: #fe5205;
  --brand-soft: #fff4ef;
  --success: #2f7d5c;
  --warning: #9a5d00;
  --danger: #b43d37;
}

:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #10110f;
  --surface: #181a17;
  --surface-subtle: #22241f;
  --text: #f3f4ef;
  --muted: #b7b9b1;
  --line: #32352f;
  --brand-soft: #3b2118;
}

button, input, select, textarea { min-height: 44px; }
button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible {
  outline: 2px solid var(--brand-accent);
  outline-offset: 2px;
}
.amount, td[data-kind="amount"] { font-variant-numeric: tabular-nums; }

@media (max-width: 720px) {
  .data-workbench table, .data-workbench thead { display: none; }
  .mobile-records { display: grid; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}
```

- [ ] **Step 3: Run automated verification**

Run:

```powershell
git diff --check
npm test
npm run build
```

Expected: all commands exit 0; build creates `dist/index.html`.

- [ ] **Step 4: Run real-browser interaction checks**

Prerequisite: `Get-Command npx` returns a command.

Start: `npm run dev -- --port 4179 --strictPort`

Use Playwright CLI to open `http://127.0.0.1:4179/`, snapshot, switch roles, navigate all seven business pages, open bill details, trigger invoice validation, run failed import preview, resolve SAP, switch F01-F10 scenarios, and capture 1440×900, 768×1024 and 390×844 screenshots.

Expected: one H1, no console/page errors, no main-root horizontal overflow, and all named actions produce the expected feedback.

- [ ] **Step 5: Write delivery and QA records**

Record the verified start command, URL, mock-only boundary, routes/views, screenshot paths, scenario coverage, test/build outputs, and remaining risks. Keep repository paths relative and do not add machine-specific paths.

- [ ] **Step 6: Retry Linear writeback**

Update DYDATA-19 to In Progress with the existing assignee; comment with branch, commit(s), verification results and remaining risks. If Linear transport still fails, record the exact failure without claiming success.

- [ ] **Step 7: Commit Task 4**

```powershell
git add docs/prototypes/dydata-19-finance-flow-dashboard src/frontend/page-preview docs/plans/execution-plan.md docs/devlog/20260804_refactor_log_Keith_Chen.md
git commit -m "docs: deliver DYDATA-19 finance flow mock"
```

## Self-Review Result

- Spec coverage: Tasks 1-4 cover roles, timeline, confirmation, disputes, promotion invoices, external audit results, management invoices, SAP, imports, recompute adjustments, F01-F10, responsive behavior and delivery evidence.
- Placeholder scan: no `TBD`, `TODO`, “implement later”, or unspecified test step remains.
- Type consistency: all downstream pages consume the same `scenarioFixtures` and exported finance rule functions defined in Task 1.
- Execution mode: inline execution in this session, because the user confirmed implementation and the active collaboration policy does not authorize subagent delegation.
