# MatchLedger — Milestone 1

A multi-tenant procurement workspace for suppliers, purchase orders, goods receipts and supplier invoices. Next.js App Router, TypeScript, Tailwind CSS and shadcn-style UI primitives; FastAPI, SQLAlchemy, Pydantic and PostgreSQL. This is a development milestone, not a production-ready product.

## Included

- Registration creates an organization and owner membership. Login, logout, expiring server-side sessions, organization switching, and owner-controlled membership of existing registered users.
- Functional supplier, PO, receipt and invoice create/read/update/delete APIs and screens, line-item editors, search, pagination, validation, dashboard and audit activity.
- SAR defaults with validated ISO 4217 currency codes. PostgreSQL `NUMERIC(18,2)` prices, `NUMERIC(18,3)` quantities and Python `Decimal` arithmetic. Each line is rounded half-up to two places before summation; values are serialized as strings. The frontend formats strings without money arithmetic. All milestone amounts exclude VAT.
- Organization filters on resource reads/writes; composite organization foreign keys prevent cross-tenant parent/child references. Supplier, PO, and PO-line consistency is also validated. Foreign IDs return 404. Authentication users are global identities connected through memberships; procurement records are tenant scoped.
- Organization, User, Membership, Session, Supplier, PurchaseOrder/Line, GoodsReceipt/Line, SupplierInvoice/Line, Document, MatchRun, MatchFinding and AuditEvent tables.
- PostgreSQL Alembic migration, deterministic sample seed, pytest tests and a real-browser Playwright workflow.

## Start with Docker (Windows PowerShell)

Install Docker Desktop with its Linux/WSL2 engine and start it. From this folder:

```powershell
Copy-Item .env.example .env
# Generate a random local database password without placing it in source code.
$dbPassword = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
(Get-Content .env) -replace '^POSTGRES_PASSWORD=$', "POSTGRES_PASSWORD=$dbPassword" | Set-Content -Encoding utf8 .env
docker compose up --build -d
docker compose ps
```

Open http://localhost:3000 and choose **Create workspace**. There are no default accounts. The API docs are at http://localhost:8000/docs. Migrations run before the backend starts. PostgreSQL data persists in a named volume. Ports bind only to the local machine.

```powershell
docker compose logs -f backend
docker compose down
```

`down` preserves data; do not add `-v` unless you intend to delete the development database. Keep `.env` private. Changing the database password in `.env` does not change credentials inside an existing PostgreSQL volume.

## Seed your organization

Register first. In the browser's developer console, retrieve your active organization ID:

```javascript
(await (await fetch('/api/auth/me')).json()).organization_id
```

Then in PowerShell:

```powershell
docker compose exec backend python -m app.seed --organization-id YOUR_ORGANIZATION_ID
```

Refresh the overview. The seed creates Riyadh Electrical Supplies, `PO-2026-001` for 100 cable rolls × SAR 50 = SAR 5,000, `GR-2026-001` for 90 rolls and `INV-2026-001` for 100 × SAR 55 = SAR 5,500, excluding VAT. The seed is transactional and skips an organization where the sample PO reference already exists. It creates no users or credentials. See `sample_data/procurement.json`.

## Local development without application containers

Requires Python 3.12+, Node.js 22+ and a running PostgreSQL database. Start only the Compose database after preparing `.env` above:

```powershell
docker compose up -d db
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend/requirements.lock
# Read the generated URL-safe password from your local .env.
$dbPassword = ((Get-Content .env | Where-Object { $_ -match '^POSTGRES_PASSWORD=' }) -split '=', 2)[1]
$env:DATABASE_URL = "postgresql+psycopg://matchledger:${dbPassword}@localhost:5432/matchledger"
$env:APP_ORIGIN = 'http://localhost:3000'
Set-Location backend
..\.venv\Scripts\python -m alembic upgrade head
..\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

In another PowerShell window:

```powershell
Set-Location D:\ocr\frontend
npm.cmd ci
npm.cmd run dev
```

The browser calls `/api` on Next.js; Next proxies to FastAPI at `http://127.0.0.1:8000`. Set `API_INTERNAL_URL` before starting/building Next if the API is elsewhere. Docker builds set it to `http://backend:8000`. Webpack is selected because Turbopack crashed in the implementation environment.

## Tests

From the repository root, after installing Python dependencies:

```powershell
.\.venv\Scripts\python -m pytest -q
# Run the same CRUD/isolation tests on PostgreSQL (uses disposable schemas).
$env:TEST_DATABASE_URL = $env:DATABASE_URL
.\.venv\Scripts\python -m pytest -q
Remove-Item Env:TEST_DATABASE_URL
```

Without `TEST_DATABASE_URL`, tests use isolated in-memory SQLite with foreign keys enabled. PostgreSQL is the supported application database; SQLite results do not establish PostgreSQL compatibility. The PostgreSQL test user needs CREATE SCHEMA permission; tests create and remove only random `test_*` schemas. The migration round-trip test uses its own temporary SQLite file.

With the full Compose stack running, PostgreSQL tests can also run inside the backend container:

```powershell
docker compose exec backend sh -c 'cd /workspace && TEST_DATABASE_URL="$DATABASE_URL" python -m pytest -q'
```

For browser tests, keep the app running and use a disposable development database. Tests register a unique account and leave its organization/records for inspection:

```powershell
Set-Location frontend
npm.cmd ci
npx.cmd playwright install chromium
npm.cmd run typecheck
npm.cmd run build
npm.cmd run test:e2e
```

Use `PLAYWRIGHT_BASE_URL` to override http://localhost:3000. No endpoints are mocked. The browser test covers registration, supplier/PO/receipt/invoice creation, invoice editing and deletion, persistence across reload, logout and login. pytest covers negative validation, CSRF, session expiry, CRUD, cross-tenant API access and database foreign-key protection, membership revocation, exact sample data, rounding and migration rollback.

## API conventions and behavior

`POST /api/auth/register`, `/login`, `/logout`; `GET /api/auth/me`; `POST /api/auth/organization`. Owners use `GET/POST /api/members` and `DELETE /api/members/{id}`. Adding a member requires their existing registered email; there is no email invitation flow.

`/api/suppliers`, `/api/purchase-orders`, `/api/receipts`, `/api/invoices` support GET list, POST create and GET/PUT/DELETE `/{id}`. PUT replaces the full editable record and its lines. Lists accept `page`, `page_size` (max 100), and `q` (name/reference search). Responses include `{items,total,page,page_size}`. Errors use `{error:{code,message,details?}}`. OpenAPI documents validated request schemas.

Authenticated mutations require the `X-CSRF-Token` returned by `/api/auth/me` or sign-in, together with the HttpOnly session cookie. Sessions contain a cryptographically random bearer token; only its SHA-256 digest is stored in the database. Passwords are Argon2-hashed. Sessions expire after 12 hours by default; logout deletes the current session and removing membership revokes that user's sessions for the organization. Cross-origin mutation requests are rejected. Local HTTP sets `COOKIE_SECURE=false`; HTTPS deployment requires `COOKIE_SECURE=true` and an exact `APP_ORIGIN`.

Each organization has an owner; members can manage procurement records. Only owners manage membership, and the owner cannot be removed. Existing membership lists refresh at login/reload. To switch organizations, use the sidebar selector.

Receipts and invoices require a purchase order and unique references to its lines. Invoice currency must match its PO. Quantities and prices may differ intentionally; no matching verdict is calculated. A PO with linked receipts/invoices cannot be edited or deleted until those records are removed. Referenced suppliers cannot be deleted. These safeguards avoid dangling procurement references. Successful writes and their audit events commit together.

## Boundaries and follow-up work

OCR, AI extraction, document uploads, matching execution, VAT calculations, currency conversion, payment tracking and approval workflows are deliberately absent. Document/MatchRun/MatchFinding tables and Python protocols prepare the next milestones. Before exposing uploads, implement allowlisted MIME types, magic-byte validation, byte-size limits and tenant-scoped storage authorization.

Production hardening still requires deployment review, HTTPS, managed secrets, login rate limiting, password recovery/email verification, operational monitoring, backups, dependency review and load testing. Session cleanup should periodically delete expired rows. Database row-level security is not enabled; tenant isolation is enforced by application queries and composite foreign keys, so direct SQL access must remain restricted. Concurrent edits currently use last-write-wins semantics. The UI is a single App Router workspace with client-side screen navigation.

See `VERIFICATION.md` for checks actually executed in the implementation environment.
