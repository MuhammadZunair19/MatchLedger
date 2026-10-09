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

OCR, AI extraction, document upload and matching execution are intentionally outside this milestone. No production-readiness claim is made.
