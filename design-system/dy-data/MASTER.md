# dy-data Page Delivery Design-System Index

**Project:** dy-data
**Delivery scope:** Existing project pages
**Generated search profile:** Data-dense operational dashboard
**Authority status:** Index only; not a competing design system

## Authoritative Sources

The formal and runtime-active design system is dy-data V0.2. Apply sources in this order:

1. `docs/design-system/tokens.json` - the only machine-readable specification source.
2. `apps/web/src/design-tokens.css` - the runtime token implementation.
3. `docs/design-system/index.html` - the visual reference and component examples.
4. `docs/design-system/README.md` - scope, maintenance process, and exceptions.

If this file or a generated page note conflicts with any source above, the V0.2 source wins.

## Delivery Constraints

- Reuse the current React 19 and Vite 7 application; do not introduce a second preview application.
- Preserve the V0.2 light-only theme and the existing Solar icon family.
- Reuse current runtime pages, layout, controls, and demo data. This delivery documents and verifies them; it does not redesign unrelated business pages.
- Keep dense operational pages optimized for filtering, comparison, review, and repeated action.
- Use V0.2 component radii and control dimensions. Do not apply the search generator's blue palette, Fira fonts, 12-16 px card radii, landing-page structure, or decorative hover transforms.
- Treat mobile patterns marked `future-DYDATA-5-not-runtime-active` in `tokens.json` as future requirements, not current implementation claims.

## Stack

- React 19 + TypeScript
- Vite 7
- `@iconify/react` with `@iconify-icons/solar`
- Hand-rolled route selection in `apps/web/src/App.tsx`
- Shared runtime tokens in `apps/web/src/design-tokens.css`

## Verification Viewports

- Desktop data workspace: 1440 x 900
- Compact desktop/tablet: 1024 x 768
- Mobile smoke check: 390 x 844

The page delivery checklist records current behavior at these sizes. It does not promote future-only mobile design-system examples to runtime scope.
