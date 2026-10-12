# MatchLedger

MatchLedger is a multi-tenant procurement application for managing suppliers, purchase orders, goods receipts, supplier invoices, document evidence, matching exceptions, approvals, audit history, and reports.

It supports English, Arabic, and bilingual procurement documents. Extracted values remain subject to human review, while financial matching uses deterministic rules and Python `Decimal` arithmetic.

## System architecture

```mermaid
flowchart LR
    U[Browser] --> F[Next.js frontend]
    F -->|/api proxy| A[FastAPI backend]
    A --> P[(PostgreSQL)]
    A --> R[(Redis)]
    R --> W[RQ document worker]
    A --> D[(Private document volume)]
    W --> D
    W --> O[PaddleOCR English and Arabic models]
    A --> X[(Private report volume)]
```

### Components

| Component | Responsibility |
| --- | --- |
| Next.js frontend | Authentication, procurement CRUD, document review, matching, exceptions, approvals, audit, and reports |
| FastAPI backend | Validation, session security, organization scoping, business workflows, matching orchestration, and report generation |
| PostgreSQL | Organizations, memberships, procurement records, document evidence, match history, findings, approvals, and audit events |
| Redis | Extraction job queue |
| RQ worker | Native PDF parsing, image rendering, and PaddleOCR processing |
| Private document storage | Original uploads and generated page previews |
| Private report storage | Generated PDF, XLSX, and CSV exports |

### Main data flows

**Authentication**

1. A user registers or signs in through Next.js.
2. FastAPI creates an expiring server-side session.
3. The browser stores an HttpOnly session cookie.
4. Mutating requests also require the active CSRF token.
5. Every business query is restricted to the selected organization.

**Document processing**

1. The backend validates the file extension, MIME type, real content, size, page count, and image dimensions.
2. The original file is stored in private tenant-scoped storage.
3. FastAPI places an extraction job in Redis.
4. The worker uses native PDF text when available and PaddleOCR for scanned English or Arabic pages.
5. Extracted evidence, warnings, and source coordinates are saved as a version.
6. A reviewer corrects and confirms the draft before a procurement record is created.

**Matching and approval**

1. Two-way matching compares a purchase order with an invoice.
2. Three-way matching also considers verified goods receipts.
3. The engine stores an immutable match run, its inputs, calculations, and findings.
4. Reviewers assign, discuss, escalate, resolve, or accept authorized variances.
5. Approved invoices retain their match and decision history. Approval does not represent payment.

## Technology

- Next.js App Router, TypeScript, Tailwind CSS
- FastAPI, SQLAlchemy, Pydantic
- PostgreSQL and Alembic
- Redis and RQ
- PaddleOCR with English and Arabic recognition
- pytest and Playwright
- Docker Compose

## Repository layout

```text
ocr/
├── backend/
│   ├── app/                 FastAPI routes, models, schemas, services, and worker
│   ├── migrations/          Alembic migrations
│   ├── Dockerfile
│   └── requirements*.txt
├── frontend/
│   ├── src/app/             Next.js routes
│   ├── src/components/      Application workspaces and UI components
│   └── package.json
├── sample_data/
│   ├── documents/           English, Arabic, bilingual, scanned, and low-quality fixtures
│   └── procurement.json     Reference procurement data
├── tests/
│   ├── backend/             Unit and API integration tests
│   ├── e2e/                 Playwright browser workflows
│   └── ocr/                 Real OCR tests
├── docs/                    Detailed workflow guides
├── compose.yaml
├── TEST.md                  Complete manual acceptance checklist
└── VERIFICATION.md          Recorded verification results
```

## Run with Docker Compose

### Requirements

- Windows 10 or 11
- Docker Desktop using Linux containers and the WSL2 engine
- Git

Node.js and Python are only required when running tests or services directly on Windows.

### 1. Open the project

```powershell
Set-Location D:\ocr
```

### 2. Create the environment file

Preserve an existing `.env`. For a new setup:

```powershell
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    $dbPassword = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
    (Get-Content .env) -replace '^POSTGRES_PASSWORD=$', "POSTGRES_PASSWORD=$dbPassword" |
        Set-Content -Encoding utf8 .env
}
```

The generated password remains in the ignored local `.env` file and is not stored in source code.

Validate the configuration:

```powershell
docker compose config --quiet
```

No output and exit code `0` means the configuration is valid.

### 3. Build and start the application

```powershell
docker compose up --build -d
docker compose ps
```

Five services should be running:

| Service | Expected state |
| --- | --- |
| `db` | Running and healthy |
| `redis` | Running and healthy |
| `backend` | Running and healthy |
| `worker` | Running |
| `frontend` | Running |

The first build can take several minutes. The first scanned-document extraction may also download OCR models into the persistent `ocr_models` volume.

### 4. Check the application

```powershell
Invoke-RestMethod http://localhost:8000/api/health
```

The response should contain `status` with the value `ok`.

Open:

- Application: <http://localhost:3000>
- FastAPI documentation: <http://localhost:8000/docs>

There are no default users. Select **Create workspace** to register an owner and organization.

### 5. Inspect logs

```powershell
docker compose logs --tail 100 backend
docker compose logs --tail 100 worker
docker compose logs --tail 100 frontend
```

Follow a service continuously when troubleshooting:

```powershell
docker compose logs -f worker
```

Press `Ctrl+C` to stop following logs. This does not stop the container.

## Load sample data

Register first, then open the browser developer console at <http://localhost:3000> and run:

```javascript
(await (await fetch('/api/auth/me')).json()).organization_id
```

Copy the returned organization UUID into PowerShell:

```powershell
$organizationId = 'PASTE-ORGANIZATION-UUID-HERE'
docker compose exec backend python -m app.seed --organization-id $organizationId
```

The reference data contains:

- Purchase order `PO-2026-001`: 100 cable rolls at SAR 50, total SAR 5,000
- Goods receipt `GR-2026-001`: 90 cable rolls
- Supplier invoice `INV-2026-001`: 100 cable rolls at SAR 55, total SAR 5,500

Load additional exception, approval, reporting, and Arabic scenarios:

```powershell
docker compose exec backend python -m app.seed_milestone4 --organization-id $organizationId
```

Both seed commands are repeatable and do not create users or passwords.

## Run automated tests

Keep the Docker Compose application running while using these commands.

### Backend tests against PostgreSQL

Run this from `D:\ocr`:

```powershell
docker compose exec backend sh -lc 'cd /workspace && TEST_DATABASE_URL="$DATABASE_URL" python -m pytest -q'
```

`/workspace` is a path inside the Linux container. It is not a folder on the Windows host. The Windows project remains at `D:\ocr`.

Confirm the container layout if needed:

```powershell
docker compose exec backend sh -lc 'pwd; ls -la /workspace'
```

The tests create and remove random PostgreSQL `test_*` schemas. A successful run reaches `100%` with no failed tests.

### Real OCR tests

```powershell
docker compose exec worker sh -lc 'cd /workspace && RUN_OCR_TESTS=1 python -m pytest tests/ocr -q'
```

These tests use the real English and Arabic OCR models and can take longer on CPU.

### Frontend checks

Node.js 22 or newer is recommended.

```powershell
Set-Location D:\ocr\frontend
npm.cmd ci
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
```

### Browser tests

Keep the full Compose stack running:

```powershell
Set-Location D:\ocr\frontend
npx.cmd playwright install chromium
npm.cmd run test:e2e
```

The browser tests create isolated organizations and exercise real API, database, worker, matching, exception, approval, audit, and document workflows.

See [TEST.md](TEST.md) for the complete manual acceptance procedure and expected values.

## Run services directly on Windows

Use Docker only for PostgreSQL and Redis:

```powershell
Set-Location D:\ocr
docker compose up -d db redis

if (-not (Test-Path .venv)) {
    python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -r backend\requirements-ocr.txt

$dbPassword = ((Get-Content .env | Where-Object { $_ -match '^POSTGRES_PASSWORD=' }) -split '=', 2)[1]
$env:DATABASE_URL = "postgresql+psycopg://matchledger:${dbPassword}@127.0.0.1:5432/matchledger"
$env:REDIS_URL = 'redis://127.0.0.1:6379/0'
$env:APP_ORIGIN = 'http://localhost:3000'
$env:PADDLE_PDX_CACHE_HOME = 'D:\ocr\.paddlex'
```

Start the backend in one PowerShell window:

```powershell
Set-Location D:\ocr\backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Start the worker in a second window with the same environment variables:

```powershell
Set-Location D:\ocr\backend
..\.venv\Scripts\python.exe -m app.worker
```

Start the frontend in a third window:

```powershell
Set-Location D:\ocr\frontend
npm.cmd ci
npm.cmd run dev
```

## Configuration

Important settings are documented in `.env.example`:

| Variable | Purpose |
| --- | --- |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Local database credentials |
| `APP_ORIGIN` | Exact browser origin accepted for authenticated mutations |
| `COOKIE_SECURE` | Set to `true` behind production HTTPS |
| `SESSION_HOURS` | Server-side session lifetime |
| `REDIS_URL` | Extraction queue connection |
| `DOCUMENT_STORAGE_PATH` | Private source-document storage |
| `REPORT_STORAGE_PATH` | Private generated-report storage |
| `MAX_UPLOAD_SIZE_MB` | Maximum upload size |
| `MAX_DOCUMENT_PAGES` | Maximum PDF page count |
| `MAX_IMAGE_PIXELS` | Maximum image pixel count |
| `OCR_LANGUAGES` | Enabled OCR languages; defaults to English and Arabic |
| `OCR_DPI` | PDF rasterization resolution for OCR |
| `DATE_ORDER` | Ambiguous numeric date order |
| `OLLAMA_ENABLED` | Optional local suggestion provider; disabled by default |

Do not commit `.env`, uploaded documents, generated reports, database files, or credentials.

## Persistent Docker data

Docker Compose uses named volumes:

| Volume | Contents |
| --- | --- |
| `postgres_data` | PostgreSQL database |
| `redis_data` | Redis queue data |
| `document_files` | Private uploads and previews |
| `report_files` | Generated exports |
| `ocr_models` | Downloaded OCR models |

Stop and remove containers while preserving these volumes:

```powershell
Set-Location D:\ocr
docker compose down
```

Restart with the existing data:

```powershell
docker compose up -d
```

To permanently delete the local database, files, reports, queue data, and OCR models:

```powershell
docker compose down -v
```

Use `down -v` only for an intentionally disposable environment.

## Security and financial boundaries

- Business records are scoped to an organization in application queries and composite foreign keys.
- Sessions use random tokens; only token digests are stored in the database.
- Passwords are Argon2-hashed.
- Mutations require session authentication, CSRF protection, and an accepted origin.
- Money uses PostgreSQL `NUMERIC` and Python `Decimal`, never floating-point calculations.
- Source documents and reports require authenticated downloads and are not public frontend assets.
- OCR output is evidence for review and never becomes an authoritative record without confirmation.
- Matching is deterministic and never performs automatic currency conversion.
- Approval records a review decision; it does not initiate or record payment.

The project is not production-ready. A production deployment still requires HTTPS, managed secrets, rate limiting, email verification and password recovery, malware scanning, monitoring, backups, dependency review, database-access controls, and load testing.

## Additional documentation

- [Complete acceptance guide](TEST.md)
- [Recorded verification results](VERIFICATION.md)
- [Document ingestion and OCR](docs/MILESTONE2.md)
- [Deterministic matching](docs/MILESTONE3.md)
- [Exceptions, approvals, and reports](docs/MILESTONE4.md)

## License

MatchLedger is available under the [MIT License](LICENSE).
