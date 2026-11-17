# Stock Trends Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, as requested by the user. Steps use checkbox syntax.

**Goal:** Fix the reviewed update/data defects and add traceable stock-level cumulative ETF adjustments.
**Architecture:** Keep immutable raw history, derive dated intervals and fixed-cohort aggregates, embed the compact trend payload in the existing standalone HTML. Retain the current Python/unittest and vanilla JS stack.
**Tech Stack:** Python 3.9+, requests, unittest; vanilla JS, CSS, SVG; no new runtime dependencies.
**Spec:** docs/reviews/2026-10-03-review-and-stock-trends.md plus the six-step plan approved in chat.

## Global Constraints
- Work in the user-requested existing project. Preserve review documents and raw historical snapshots.
- No push, deployment, or history overwrite. Generate local active.json/index.html and derived trend data only.
- Unknown values are null, never zero. First observations are baselines, not purchases.
- Event and quote dates remain traceable; aggregate only comparable intervals.
- Default 20 sessions, optional 5/60/all. Insufficient history must be explicit.
- Preserve offline standalone HTML and current visual language.

## Review Focus
- Newly appearing ETF must not crash or create a full-portfolio buy spike (Task 1).
- Older successful data, missing quotes and template-only changes must not regress/freeze output (Tasks 1/2).
- Same-day revisions and legacy date changes must not double count (Task 3).
- Gaps, first observations, and possible corporate actions must not look like zero flow (Task 3).
- Cleared stocks, unavailable windows, CSV export and mobile chart interaction must remain usable (Task 4).

## Task 1: Update pipeline and events
Files: scripts/update_dashboard.py, scripts/outputs.py, scripts/diffengine.py, scripts/adapters/base.py; tests/test_pipeline_v3.py.
Interfaces: load_latest_snapshot(history_dir) -> merged latest ETF state; compute_all_events adds from_date/to_date/method; quotes remain compatible until Task 2.
- [x] Write regressions: missing baseline yields events=[]; stale fetch preserves latest; metadata-only update is detected; REMOVE at scale 1.2 yields adjusted=-1200.
- [x] Run `python3 -m unittest discover -s tests -p 'test_pipeline_v3.py' -v`; expect failures on old code.
- [x] Implement latest-state merge before resolving publish date; avoid wholesale skip before quote/render; attach event periods, preserve snapshot revisions in derived data only; full suite green.

## Task 2: Quote identity and safe complete output
Files: scripts/quotes.py, scripts/outputs.py, scripts/render_html.py, scripts/update_dashboard.py, .github/workflows/update.yml; tests/test_pipeline_v3.py.
Interfaces: QuoteMap(dict) with dates and failed; build_fundamentals uses per-code date; build_id includes renderer/assets; write_bundle_atomic stages all files before replace with rollback.
- [x] Test different market dates, unknown date premium=null, wrong-day event price=null, UI hash changes, script-safe JSON, staged failure leaves old bundle intact.
- [x] Run focused tests and observe old behavior failures.
- [x] Implement per-security provenance, staged publication and rollback, safe JSON, full artifact hashes. Run full suite.

## Task 3: Historical intervals and aggregates
Files: scripts/trends.py, scripts/trading_calendar.py, data/trading_calendar.json, tests/test_trends.py.
Interfaces: build_trends(history_dir, registry, calendar, overrides=None) -> {stocks, windows, intervals, quality}; windows fixed cohort across selected sessions; all raw history unchanged.
- [x] Test pure scale flows, below-threshold accumulation, consistent removal, missing session, duplicate revision, new ETF, entirely cleared stock, action-risk interval, insufficient 60 sessions.
- [x] Run focused tests; expect missing module/functions.
- [x] Implement canonical snapshots with source references and legacy taishin quarantine, complete full-holdings deltas, fixed cohort, summaries and audit output. Run full suite.

## Task 4: Stock trends and ranking UI
Files: scripts/trends_ui.js, scripts/trends_ui.css, scripts/render_html.py, tests/test_trends_ui.js, tests/test_render.py.
Interfaces: embedded TREND_DATA, window/stock selectors, SVG daily/cumulative/holdings charts, selected-day breakdown and CSV; ranking opens stock view.
- [x] Add executable JS tests for selection, ranking, CSV escaping and unavailable windows; render smoke checks for new accessible controls.
- [x] Run tests before implementation; expect missing module/controls.
- [x] Implement offline SVG charts and accessible tables in existing style; export all period intervals with provenance.
- [ ] Actual desktop/mobile visual QA: unavailable due browser policy; offline DOM checks passed.

## Task 5: Local build, migration report and docs
Files: scripts/build_local.py, data/stock_trends.json, docs/reviews/2026-10-03-migration.json, active.json, index.html, README.md.
- [x] Test offline rebuild leaves history/perf_stats/registry unchanged and deterministic on rerun.
- [x] Implement local rebuild with new versioned derived data and current-day recomputation only in active output. Never invent historical prices.
- [x] Run full Python/JS suite, build local artifacts, check output identity and raw history hashes.

## Task 6: Final verification
- [x] Review all changes with a fresh reviewer under executing-plans; fix important findings with regressions.
- [x] Validate UI with permitted browser APIs if possible; report any tool policy limits honestly.
- [x] Document calendar provenance, quality exclusions, estimator assumptions, new commands and schema.
- [x] Leave all changes uncommitted for user review; no automatic publish.

## Execution ledger
- Baseline: 168 Python tests pass. Existing untracked review files preserved.
- Ruling: User explicitly requested taking over and starting in order; proceed inline in original workspace without additional approval or worktree setup. No commits/pushes.
- Ruling: Calendar must carry verified provenance and coverage; outside its range UI labels observed sessions rather than pretending verified trading days.

- Tasks 1–5: implementation complete; 198 Python tests plus JS logic/smoke checks pass. Original history/perf/registry unchanged.
- Ruling: browser file URL was refused in prior review; do not bypass via another browser surface. Use offline unit DOM smoke; actual desktop/mobile visual acceptance remains unverified.
- Task 6: fresh reviewer found same-day A→B→A revision deduplication bug. Regression reproduced, fixed by comparing only the latest revision; 17 pipeline regressions pass. Reviewer then stopped due usage limit, so independent review was partial.
- Final verification: 199 Python tests, JS logic/breadth sorting and generated-page unit DOM controls/export smoke pass; git diff --check clean. Raw history/perf/registry verified byte-for-byte against HEAD. No commits or deployment.

- Follow-up authorization (2026-10-03): user requests remaining review/verification and authorizes GitHub push afterward, superseding earlier no-push scope.
- Complete independent review finished. Additional findings fixed: legacy event quarantine, shared scale quality gate, latest-valid-date batch watermark, reverse-lookup end date and noninteractive baseline points. See docs/reviews/2026-10-03-final-verification.md.
- Current verification: 203 Python tests plus JS logic and generated-page unit DOM checks pass; original 43 source files unchanged. User-side visual verification pending because browser policy still blocks local-page access.
