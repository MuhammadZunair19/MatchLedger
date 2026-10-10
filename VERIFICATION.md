# Milestone 1 verification

Executed on October 9, 2026, on Windows with Python 3.12 and Node.js 24.

| Check | Result |
| --- | --- |
| `python -m pytest -q` | 16 passed; isolated SQLite databases with foreign keys enabled |
| `npm.cmd run build` | Passed; Next.js 16 webpack build, including TypeScript and static page generation |
| `npm.cmd run typecheck` | Passed |
| `npm.cmd run test:e2e` | 1 complete browser workflow passed against the real local frontend and API |
| Desktop and mobile screenshots | Reviewed; sidebar overflow fixed and browser workflow rerun successfully |
| `docker compose config --quiet` | Passed using a temporary validation-only environment value |
| Alembic upgrade/downgrade | Passed on a temporary SQLite database |
| Alembic PostgreSQL offline SQL generation | Passed |
| Live PostgreSQL integration and full Docker stack | Not run: Docker Desktop engine failed to start |

The browser test registers a real isolated QA organization, creates a supplier and PO, records a 90-roll receipt and a 100-roll invoice at SAR 55, edits/deletes the invoice, reloads persisted data, logs out/in and uses mobile navigation. No API interception or mock endpoints are used. Browser verification used `qa.db`, an ignored local SQLite database, because PostgreSQL was unavailable.

Docker Desktop's log reported failure to initialize its Secrets Engine because its local `engine.sock` could not be accessed/renamed. No Docker state or sockets were deleted. The repository includes PostgreSQL test instructions in README; live database and container verification still need to run after Docker is healthy.

An installed Starlette dependency emits a test-client deprecation warning about its future HTTP client migration; tests pass. Turbopack crashed while spawning its CSS processing subprocess; using Next's supported webpack mode resolved the build.

Those checks established the Milestone 1 baseline. They do not establish correctness of the new document workflows.

## Milestone 2 verification record — October 10, 2026

- The existing 16 backend regression tests passed after adding the document schema and migration. The final document changes and newly added document tests were not rerun.
- The second migration was applied successfully to the local PostgreSQL database. Earlier schema migration round-trip checks ran on SQLite; final rollback remains to be checked on PostgreSQL.
- Native extraction was exercised on English, Arabic, bilingual and multipage synthetic PDFs. Font mapping and Arabic column handling issues were repaired. The final Arabic numeric fixture adjustment has not been rerun through extraction.
- Real PaddleOCR 3.7 / PaddlePaddle 3.3.1 CPU models downloaded and loaded. A scanned English image produced actual OCR tokens, confidence and structured header evidence. OCR merged description and quantity in one box; a conservative, explicitly uncertain splitting repair was added afterward and remains unverified. Arabic image OCR and low-quality fixtures still need the dedicated OCR suite.
- Backend Ruff checks passed before the final small edits. Final frontend typecheck, lint/build, document browser workflows, full container build and document test counts have not been verified.
- A document test command was rejected by automatic approval review because of an account usage limit, before execution. The user subsequently requested source completion and chose to run the application/tests themselves. No further runtime tests were run.
- Docker Compose shutdown was attempted at handoff. Docker Desktop's Linux engine pipe was unavailable; no running stack could be inspected through Docker at that point. No development services were restarted.

Run the commands in `docs/MILESTONE2.md` to validate this handoff. Milestone 2 is implemented in source but needs final regression and end-to-end verification; readiness for Milestone 3 is conditional on those results. No production-readiness claim is made.

### Arabic and split-label follow-up

After manual review exposed blank fields on PDFs that render labels and values as separate spans, extraction was updated to pair same-row LTR/RTL evidence and to expose bilingual OCR alternatives to field recognition. The two retained demo PDFs now extract their number, date, supplier, currency, totals and line price without validation warnings. Native English/Arabic regression selection passed: 8 tests in 0.24 seconds.

The strengthened real Arabic raster test passed in 94.36 seconds on CPU. It now requires an Arabic supplier name, invoice/date evidence, SAR, due date, Arabic line description, unit price and line total. OCR can still omit or confuse individual characters and quantities; these stay uncertain/missing for human review rather than being inferred. Ruff passed on backend and document/OCR tests. API tests requiring a new Starlette TestClient later stalled while Windows created its internal socket pair; they were interrupted and no application service was left running.

## Milestone 3 verification record — October 10, 2026

| Check | Result |
| --- | --- |
| Matching engine tests | 14 passed, including the SAR 5,500 / 4,500 / 1,000 reference case |
| Matching persistence and tenant isolation | 2 passed against isolated SQLite with foreign keys enabled |
| Targeted invoice extraction regressions | 9 passed for split labels, Arabic invoice fields and native English/Arabic/bilingual PDFs |
| Frontend TypeScript | Passed |
| Alembic upgrade/current/downgrade | Passed on a fresh temporary SQLite database; head was `c84e31f2a6d0` |
| Existing FastAPI TestClient suite | Interrupted: this Windows host blocked inside CPython `socket.socketpair()` while starting Starlette's portal, before an application request |

The engine tests cover exact and fuzzy association behavior, multiple invoice lines to one PO line, reference normalization, tolerance boundaries, zero expected price, missing receipts, duplicate/supplier/currency/date findings, two-way behavior and the full three-way sample variance. The persistence tests verify historical reruns, structured findings, audit creation and cross-tenant invisibility.

No application or worker service was left running. PostgreSQL, Docker Compose, frontend production build and Playwright should still be run by the tester before accepting deployment. This is a development milestone and is not production-ready.
