# Administration surface brief

## Mode and decision

- Mode: Operate
- Direction: Braided Light
- Seed: `8feeff99`
- Composition: task-first rail and data workspace using the same identity at higher density

The admin surface uses the public brand's type, indigo, mineral rules, mark, and theme behavior without importing landing-page spectacle. The desktop experience prioritizes comparison and scanning. Mobile changes the view control to a select and converts data tables into compact semantic result summaries with essential actions.

## Component grammar

- Navigation: nine-view vertical tablist with roving keyboard focus; labeled mobile selector below the breakpoint.
- Data: semantic captioned tables inside focusable overflow regions, tabular numerals, bounded long values, and `dir="auto"` for user content.
- Metrics: rectangular divided grid with no decorative card shadows; red and green only for real operational state.
- Mutations: native modal dialogs with explicit reason fields where required, pending lockout, live success/failure messages, focus trap, and restoration.
- Loading and errors: view-level `aria-busy`, live announcements, retry action, and consistent 401/403 handling.
- Concurrency: active view and conversation requests use cancellation plus generation checks to prevent stale rendering.

## Compatibility commitments

All nine existing views and `/api/admin/*` payloads remain in place. Admin continues to require its server-enforced role, stays `noindex, nofollow`, remains excluded from robots and sitemap, and is routed before the deployment catchall.

## Responsive commitments

Desktop tables remain contained instead of widening the page. At 390px the rail is removed from layout, the view selector becomes primary navigation, records become stacked summaries, Hebrew and long identifiers wrap safely, and every actionable control keeps at least a 44px target.
