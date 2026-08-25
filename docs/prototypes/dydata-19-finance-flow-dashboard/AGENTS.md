# Prototype Instructions

Run the local server and open the preview in the browser available to this environment. Do not ask the user to start the server when it can be run locally.

This directory is a historical DYDATA-19 requirement-discussion prototype. It is not a production capability, an approved business contract, or an authority for finance policy.

For current scope and acceptance, use [Linear DYDATA-19](https://linear.app/keith-lim/issue/DYDATA-19), [Linear DYDATA-74](https://linear.app/keith-lim/issue/DYDATA-74), `../../prd/mainprd-dy-data.md`, and `../../prd/subprd/04-subprd-invoice-guide.md`. If this prototype conflicts with those sources, the current Linear issue and PRD/Foundation documents take precedence.

The following items describe historical demonstration assumptions only. They must not be promoted into production behavior without a separately reviewed Linear requirement:

- The demo covers both store and finance views; finance uses the existing administrator permission model.
- Store-facing terminology is “账单确认”; the dispute entrance exists inside bill details but is deliberately not prominent.
- Finance has four secondary pages: promotion service fee, management service fee, bill disputes, and import records.
- Operational totals belong at the top of secondary pages, not on the finance landing page.
- Bill disputes contain SAP code disputes and amount/rate disputes; amount disputes use one list with type-specific actions.
- Main lists expose only `有效 SAP`; source values appear in details and audit history.
- External audit approval equals full payment; external audit rejection requires red-flush and reissue.
- Paid results do not roll back; recompute differences move to the next billing period.

Keep all work inside this standalone mock. Do not connect real APIs, databases, authentication, payment actions, production data, or deployment workflows. Use synthetic Chinese mock data only. Before delivery run `npm test`, `npm run build`, and real-browser interaction checks.
