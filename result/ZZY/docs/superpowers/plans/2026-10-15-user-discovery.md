# User Discovery Page Implementation Plan

> For agentic workers: execute inline with executing-plans, task by task. The user has authorized implementation; do not request execution choice again. No commit/push. Use the independent delivery directory approved in the spec, not a new Git checkout of incomplete tracked sources.

**Goal:** Turn the approved A direction into a real game discovery page with grounded explanations.

**Architecture:** Keep the Python query/score services and the full evidence renderer. Add a small pure JavaScript presentation module for card reasons and official links; change HTML/CSS and the renderer's ranking projection. Keep the existing request cancellation/generation logic and single-port mounting.

**Tech Stack:** Existing Python HTTP service, vanilla JavaScript/CSS, Node built-in test runner, existing pytest and browser tooling.

## Task 1 — Isolate delivery and establish baseline

- [x] Create `交付版-用户发现/result/ZZY/` by copying only files listed in the existing delivery manifest; preserve the old ZIP and caches.
- [x] Record the original SHA256 of all calculation modules. Run existing search tests from the private module directory with a project-local pytest temp directory.
- [x] Find a working Python interpreter and browser runtime; use existing frozen inputs for evaluation, never extract or modify the database for this UI check.

## Task 2 — Grounded presentation (test first)

Files: `modeling/recommendation/query_view_assets/discovery.js`, `tests/test_discovery.cjs`.

- [x] Write Node tests requiring `discovery.js`: positive path selection, per-seed attribution, exclusion of zero/non-scored paths, fallback, numeric appid links, and input immutability.
- [x] Run `node --test tests/test_discovery.cjs` and confirm the missing module causes failure before implementation.
- [x] Implement `DiscoveryPresentation.describe(display, games)` returning `{reason,tags,paths}`, selecting only `p.used_for_score && p.contribution > 0`, ordered by field (tags/genres/developers) and descending contribution, with deterministic ties.
- [x] Implement validated official `storeURL(appid)` and `coverURL(appid)` using positive safe integer ids; reject other input.
- [x] Re-run the same test suite until all pass. Register `/discovery.js` in `query_view.py`.

## Task 3 — Player-facing UI

Files: `query_view_assets/index.html`, `style.css`, `renderer.js`, `app.js`, `process/site_service.py`.

- [x] Replace the page structure with a dark A layout, retaining every DOM id used by the existing app/evidence renderer. Keep filters, methods and technical evidence collapsed; use three-column cards on desktop and single-column on mobile.
- [x] Adapt `QueryRenderer.show` to render actual results as cards. Build nodes with `textContent`, not arbitrary HTML; card metadata has year and real path-derived tags, no probability.
- [x] Bind card explanation buttons to the selected real result and open the common explanation panel; preserve full paths, formulas, source proofs and graph keyboard controls. Make selected card state accessible.
- [x] Add image loading fallback (hide failed image; leave named placeholder), lazy loading and official details links with `noopener noreferrer`.
- [x] Replace technical status wording in `app.js`; keep cancellation/generation tokens, all eligibility and pagination logic.
- [x] Limit image CSP to the selected Steam CDN while keeping other directives. Check all scripts with `node --check`.

## Task 4 — Verify real behavior and visual layout

- [x] Refresh delivery source hashes for changed/new resources; baseline protected calculation-module hashes must remain byte-identical.
- [x] Run existing pytest contracts plus Node presentation tests.
- [x] Start a separate loopback server with frozen input/cache. Compare old and new real query ranking payloads for one seed, multiple seeds and years; compare every returned reason to its contributing source paths.
- [x] Use a real browser at 1440×1000 and 390×844. Check search aliases, add/remove/replace/max-three, filtering/clear, cancellation, retries, stale response protection, empty results, keyboard flow, hostile text, image failure and no horizontal overflow. Save screenshots and results.
- [x] Inspect screenshots and fix visible issues; distinguish real data checks from injected failure fixtures.

## Task 5 — Deliver

- [x] Update approved spec status, delivery README/report, verification report, source manifest, submit list and task log.
- [x] Create `最新版交付包/ZZY-site-v6.zip` and manifest. Verify ZIP CRC and SHA256 of every packaged file, exclude secrets/cache/runtime and preserve v5.
- [x] Provide actual running page and screenshot links; report what was checked and any remaining limits. No Git commit/push or claims of improved recommendation quality.
