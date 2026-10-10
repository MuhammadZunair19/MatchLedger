# Milestone 2: document ingestion and human verification

This extends the existing procurement CRUD, sessions and organization membership. It adds private uploads, native PDF extraction, real English/Arabic PaddleOCR, versioned evidence, editable drafts, correction history and transactional creation of a procurement record after human confirmation. No matching engine runs.

## Files and schema

`backend/app/document_routes.py` and `document_schemas.py` implement the API. `backend/app/services/documents/` separates private storage, bounded parsing, normalization, image preprocessing, PDF/OCR adapters, field/line extraction, validation, optional Ollama, queue processing and verification. `backend/app/worker.py` runs RQ (SpawnWorker on Windows). The frontend adds `document-workspace.tsx`, `document-review.tsx`, `src/lib/documents.ts` and `/documents/[[...segments]]`.

Migration `a35db39e3e1a_document_extraction_and_human_review.py` follows `a2b9f21b475a`. It extends Document metadata/review state and adds DocumentExtraction and FieldCorrection with tenant composite foreign keys. Extracted evidence and reviewed drafts are separate JSON structures. Decimal amounts become NUMERIC business values only through the existing validated schemas. Each correction records actor, timestamp, extraction and revision. Original extraction versions remain available; re-extraction preserves saved corrections. Verification creates a new record, never silently overwrites an existing one.

Fixtures live in `sample_data/documents/`: English/Arabic POs, invoices and delivery notes; bilingual and two-page invoices; scanned PDF/PNG/JPG and a blurred low-quality image. `generate.py` recreates synthetic files. They contain no real supplier information. Existing procurement seed remains unchanged.

## Start or stop (Windows PowerShell)

For a new checkout only, copy `.env.example` to `.env` and generate a private database password using README. Preserve an existing `.env` and database volume. Docker Desktop must use Linux containers.

```powershell
Set-Location D:\ocr
docker compose up --build -d
docker compose logs --tail 100 worker
```

Open http://localhost:3000, register or log in, and select Documents. The API docs are at http://localhost:8000/docs. Backend startup runs Alembic. Compose includes PostgreSQL, Redis, API, frontend and CPU worker. Model downloads occur on first OCR use and are cached in `ocr_models`; native PDFs do not require model downloads. Allow several minutes and sufficient disk/network access for the first model load. Worker memory is capped at 4 GB and CPU at two cores; unusually complex jobs may need tuning.

```powershell
docker compose stop
# Remove containers while keeping database, private files and cached models:
docker compose down
```

Do not use `down -v` unless intentionally discarding all persistent development data. Native PowerShell setup and worker commands are in README. `backend/requirements.lock` is a captured combined Python environment; `requirements.txt` and `requirements-ocr.txt` are the supported installation inputs.

## OCR and optional Ollama

PaddleOCR uses real PP-OCRv5 mobile detection plus English and Arabic recognition models. Defaults: `OCR_DEVICE=cpu`, `OCR_LANGUAGES=en,ar`, `OCR_DPI=150`. The default Compose image is CPU only; selecting a GPU device requires a compatible GPU PaddlePaddle image and Docker GPU runtime. Recognition confidence is preserved; native PDF text has no invented confidence. Bounding boxes are normalized page coordinates. Alternative OCR attempts and uncertainty are retained.

Native text is preferred on readable PDFs; image-only/unusable pages are rasterized for OCR. Low contrast/blur and missing/ambiguous values generate review warnings. Arabic and Eastern Arabic digits, decimal/thousands marks and SAR aliases normalize with Decimal. Missing fields stay null. `DATE_ORDER=DMY` controls ambiguous numeric dates; Hijri dates require explicit Gregorian review.

Ollama is optional and disabled by default. To enable, set `OLLAMA_ENABLED=true`, `OLLAMA_BASE_URL=http://host.docker.internal:11434` for Docker, and `OLLAMA_MODEL` to an installed local model. On a host worker use `http://127.0.0.1:11434`. Install/pull that model in Ollama yourself. Only local/private addresses are accepted; redirects are rejected. Suggestions must quote actual page text, remain flagged for human review, and cannot replace populated deterministic fields. Unavailable/invalid responses produce a warning while deterministic extraction continues. No cloud LLM API is called.

Default limits: 20 MB/file, 30 PDF pages, 25 million image pixels, 30 seconds for parser subprocesses, 900 seconds/job, five extraction attempts. Files are validated against actual PDF/JPEG/PNG content and stored with generated tenant keys outside public assets. Password-protected, repaired/corrupt or oversized PDFs are rejected. Previews rasterize without annotations; originals download through authenticated attachment responses. Linux parser subprocesses also impose CPU/address-space limits. No antivirus scanner is included.

## API endpoints

All routes below start with `/api/documents`. Session authentication, organization scope and CSRF on mutations apply. Foreign-tenant IDs return 404.

| Method and path | Behavior |
| --- | --- |
| POST `/upload` | Multipart `file` and `document_type`: `purchase_order`, `supplier_invoice`, `goods_receipt`; return stored document |
| GET `/` | Paginated list; `page`, `page_size`, `q`, `status`, `document_type` filters |
| GET `/{id}` | Safe document metadata |
| GET `/{id}/file` | Authorized original attachment |
| GET `/{id}/pages/{page}` | Authorized PNG preview; page numbering starts at 1 |
| POST `/{id}/extract` | Queue a new extraction version; reject duplicates or verified documents |
| GET `/{id}/status` | Current processing state |
| GET `/{id}/extraction` | Latest/versioned evidence, history, review draft and warnings; optional `version` |
| PUT `/{id}/review` | Save `{revision,data}` with optimistic revision check and correction audit |
| GET `/{id}/corrections` | Tenant-scoped correction history |
| POST `/{id}/verify` | `{revision,acknowledge_warnings,create_supplier}`; create validated business record atomically |
| DELETE `/{id}` | Delete inactive upload/evidence; retain any already-created procurement record |

Lifecycle: UPLOADED → QUEUED → PROCESSING → REVIEW_REQUIRED → VERIFIED. Failures become FAILED with retry. Queue outages return 503 truthfully. Stale queued/processing jobs become retryable failures after timeout plus grace period; workers recover stale jobs at startup and document requests recover their tenant's jobs. Late results cannot replace recovered state. Verification is duplicate-protected by a database row lock and persisted status. No periodic queue watchdog is included.

## Validation commands

These commands are for your own run. The handoff did not execute the final document suite or frontend build; see `../VERIFICATION.md` for actual prior results.

```powershell
Set-Location D:\ocr
.\.venv\Scripts\python -m pip install -r backend/requirements.txt -r backend/requirements-ocr.txt
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check backend
# Runs actual downloadable CPU OCR models, separately from fast tests:
$env:RUN_OCR_TESTS = '1'
$env:PADDLE_PDX_CACHE_HOME = 'D:\ocr\.paddlex'
.\.venv\Scripts\python -m pytest tests/ocr -q
Remove-Item Env:RUN_OCR_TESTS
Set-Location frontend
npm.cmd ci
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
npx.cmd playwright install chromium
# Requires the application running against a disposable development database:
npm.cmd run test:e2e
```

`tests/backend/test_documents.py` adds normalization, native evidence, limits/content validation, file authorization, tenant isolation, drafts/corrections, confirmation, linked receipts/invoices, queue failure and stale recovery tests. Isolated API tests replace queue transport only and execute the real native parser/persistence. `tests/ocr/test_real_ocr.py` exercises actual scanned/Arabic/low-quality OCR. Playwright covers Milestone 1 CRUD and adds native document upload, real worker extraction, persisted correction and PO confirmation. The new browser test has not been executed and requires Redis and a worker. PostgreSQL test-schema setup is documented in README.

## Manual acceptance guide

1. Register two independent workspaces. Upload `purchase_order_en.pdf` as a purchase order in the first. Confirm it is absent from the second; copied file/preview/review URLs must return 404 for the second session.
2. Start extraction and watch queued/processing state. Inspect raw evidence and the source highlight. Check number/date, supplier and one row: 100 cable rolls at SAR 50, total 5,000 excluding VAT.
3. Correct a field, choose an existing supplier or explicitly create one, save the draft, and inspect correction history. Reload to establish persistence. Unsaved edits disable confirmation; another stale revision must be rejected.
4. Acknowledge warnings after reviewing them and confirm. Check the new PO in Purchase orders and its audit activity. Repeat confirmation must fail rather than create another PO. Original file/extraction remain available.
5. Upload delivery note (90 rolls) and invoice (100 rolls at SAR 55). Select the existing supplier/PO and map each line to its PO line. Save and confirm; check receipt/invoice screens. No matching result should appear.
6. Exercise Arabic, bilingual and multipage native files, then scanned images/PDF. Review every uncertain/missing value, especially merged/wrapped line items. Poor scans may require manual correction. Do not treat OCR as authoritative.
7. Try a renamed executable, MIME mismatch, corrupt/encrypted PDF and files above limits. Check truthful errors. Stop Redis before extraction to check queue-unavailable behavior, then restart and retry. Interrupt a worker and wait for timeout/grace recovery before retrying.
8. Re-extract an unverified document after saving corrections; ensure correction history and reviewed values survive. Delete an inactive upload and confirm source access fails. Verified business records survive document deletion.

## Known limits and next milestone

Layout/label parsing is deterministic and intended for review, not universal supplier templates. Multiline/merged cells, unusual Arabic font maps, weak scans and reordered tables can remain uncertain or incomplete. The latest merged OCR-cell and Arabic fixture repairs need validation. Optional local Ollama has not been exercised end-to-end. Final container/build, document tests and frontend checks remain outstanding at user handoff.

Taxes, discounts, SKU/UOM, due dates and original totals remain in linked document review JSON; they are not silently projected into unsupported Milestone 1 business columns. Receipt/invoice confirmation requires an existing PO and explicit PO-line mapping. No cloud storage, malware scanner, matching/fraud verdicts or production-hardening claim is included.

The interfaces and tables support a subsequent matching milestone. Start Milestone 3 after the document acceptance checks and PostgreSQL regression suite pass; source implementation alone does not establish readiness.
