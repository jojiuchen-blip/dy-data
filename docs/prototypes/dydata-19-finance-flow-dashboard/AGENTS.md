# Prototype Instructions

Run the local server and open the preview in the browser available to this environment. Do not ask the user to start the server when it can be run locally.

This prototype is the confirmed DYDATA-19 finance-flow discussion artifact. Keep these durable decisions:

- The demo covers both store and finance views; finance uses the existing administrator permission model.
- Store-facing terminology is “账单确认”; the dispute entrance exists inside bill details but is deliberately not prominent.
- Finance has four secondary pages: promotion service fee, management service fee, bill disputes, and import records.
- Operational totals belong at the top of secondary pages, not on the finance landing page.
- Bill disputes contain SAP code disputes and amount/rate disputes; amount disputes use one list with type-specific actions.
- Main lists expose only `有效 SAP`; source values appear in details and audit history.
- External audit approval equals full payment; external audit rejection requires red-flush and reissue.
- Paid results do not roll back; recompute differences move to the next billing period.

Build application UI in `src/`. Use realistic Chinese mock data, V0.2.1 semantic tokens, Solar icons, visible focus, responsive record cards, and reduced-motion support. Before delivery run `npm test`, `npm run build`, and real-browser interaction checks.
