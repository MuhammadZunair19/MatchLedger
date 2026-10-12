# MatchLedger Milestones 1–4 Test Runbook

This guide tests MatchLedger from a clean local setup through Milestone 4. It uses Windows PowerShell, Docker Compose, the real PostgreSQL and Redis services, the real OCR worker, pytest, and Playwright. No API endpoint is mocked in the browser tests.

Use a disposable local development database for this run. The test and seed steps create organizations, suppliers, orders, receipts, invoices, match runs, approvals, audit events, documents, and report files.

## 1. What counts as a pass

The project passes this runbook when all of the following are true:

- All five Compose services start: `db`, `redis`, `backend`, `worker`, and `frontend`.
- The backend health endpoint returns `status: ok` and the browser opens MatchLedger.
- The backend, frontend, OCR, and Playwright commands exit with code 0 and report no failed tests.
- Milestone 1 records calculate SAR 5,000 for the purchase order and SAR 5,500 for the invoice.
- Milestone 2 extracts the supplied English and Arabic fixtures, preserves corrections, and only creates a ledger record after confirmation.
- Milestone 3 produces the exact SAR 5,500 / SAR 4,500 / SAR 1,000 reference comparison described below.
- Milestone 4 supports exception review, approval decisions, audit history, and downloadable PDF/XLSX/CSV reports.
- A second organization cannot see or modify the first organization’s data.

Passing this guide establishes local milestone acceptance. It does not make the application production-ready.

## 2. Prerequisites

Install and start:

- Docker Desktop using Linux containers and the WSL2 engine
- Git
- Node.js 22 or newer and npm, for host-side frontend checks
- A Chromium-capable Playwright installation, installed later in this guide

Open PowerShell and verify the tools:

```powershell
docker version
docker compose version
node --version
npm.cmd --version
git --version
```

**Expected result:** every command prints a version. `docker version` must show both Client and Server sections. If the Server section is missing, start Docker Desktop before continuing.

## 3. Prepare the local environment

Move to the repository:

```powershell
Set-Location D:\ocr
```

Create `.env` only if it does not already exist. Do not overwrite an existing environment file or commit it.

```powershell
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    $dbPassword = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
    (Get-Content .env) -replace '^POSTGRES_PASSWORD=$', "POSTGRES_PASSWORD=$dbPassword" |
        Set-Content -Encoding utf8 .env
}
```

Validate Compose without starting anything:

```powershell
docker compose config --quiet
if ($LASTEXITCODE -eq 0) { 'Compose configuration: PASS' }
```

**Expected result:** `Compose configuration: PASS` and no error about `POSTGRES_PASSWORD`.

### Optional clean reset

Only use this before testing if the current Docker data is disposable. It permanently removes the MatchLedger database, uploaded documents, reports, Redis data, and downloaded OCR model volume.

```powershell
docker compose down -v
```

For an ordinary restart, use `docker compose down` without `-v` so data remains available.

## 4. Build and start the complete application

```powershell
docker compose up --build -d
docker compose ps
```

The first build and the first OCR run can take several minutes. Check readiness:

```powershell
$deadline = (Get-Date).AddMinutes(5)
do {
    try {
        $health = Invoke-RestMethod http://localhost:8000/api/health
        if ($health.status -eq 'ok') { break }
    } catch {}
    Start-Sleep -Seconds 5
} while ((Get-Date) -lt $deadline)

$health
docker compose ps
```

**Expected result:**

- The health response contains `status` with the value `ok`.
- `db`, `redis`, and `backend` show healthy.
- `worker` and `frontend` show running/up.
- <http://localhost:3000> opens the MatchLedger sign-in screen.
- <http://localhost:8000/docs> opens FastAPI documentation.

If a service is not ready, inspect its logs:

```powershell
docker compose logs --tail 150 db redis backend worker frontend
```

Do not continue until the health endpoint succeeds.

## 5. Run the automated checks

Run these before the manual workflow. A command passes only when its exit code is 0 and its summary contains no `failed` or `error` entries.

### 5.1 Backend suite on PostgreSQL

The tests create and remove random `test_*` PostgreSQL schemas. They do not need a separate database when run with the Compose database user.

```powershell
Set-Location D:\ocr
docker compose exec backend sh -lc 'cd /workspace && TEST_DATABASE_URL="$DATABASE_URL" python -m pytest -q'
```

**Expected result:** pytest reaches `100%`, reports only passed tests, and exits with code 0. The exact number may increase as tests are added. Coverage includes authentication, CSRF, CRUD, validation, tenant isolation, migrations, document review, deterministic matching, approvals, and reports.

If this command stalls before the first API request on Windows, run it inside the Linux container exactly as shown rather than with the host Python interpreter.

### 5.2 Real English and Arabic OCR tests

These tests load the real PaddleOCR models. The first run downloads models into the `ocr_models` volume and is much slower than later runs.

```powershell
docker compose exec worker sh -lc 'cd /workspace && RUN_OCR_TESTS=1 python -m pytest tests/ocr -q'
```

**Expected result:** all OCR tests pass. The Arabic test must detect Arabic supplier or item text plus invoice/date evidence, SAR, due date, unit price, and line total. The low-quality test may retain uncertainty; it must not invent authoritative values.

### 5.3 Frontend type, lint, and production-build checks

```powershell
Set-Location D:\ocr\frontend
npm.cmd ci
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
```

**Expected result:** every command exits with code 0. TypeScript prints no type errors, ESLint prints no errors, and Next.js reports a successful production build.

### 5.4 Real browser workflows

Keep the Compose application running. Playwright creates unique test organizations and records in the development database.

```powershell
Set-Location D:\ocr\frontend
npx.cmd playwright install chromium
npm.cmd run test:e2e
```

**Expected result:** two browser tests pass:

1. Registration, supplier/PO/receipt/invoice CRUD, matching, exception resolution, approval, reports, audit, persistence, logout/login, and mobile navigation.
2. Private purchase-order upload, real worker extraction, saved correction, reload, confirmation, and creation of a SAR 5,000 purchase order.

Failure traces and screenshots are written under `frontend\test-results`. A successful run may still leave test organizations in the disposable database.

## 6. Create the manual-test organization

Open <http://localhost:3000> and select **Create workspace**. Use test-only values such as:

| Field | Test value |
| --- | --- |
| Full name | Manual Tester |
| Organization | MatchLedger Manual QA |
| Email | `manual-owner@example.test` |
| Password | A unique local test password with at least 12 characters |

**Expected result:** registration signs you in and opens **Procurement overview**. The sidebar shows Overview, Suppliers, Purchase orders, Goods receipts, Supplier invoices, Documents, Matching, Exceptions, Approvals, Reports, Audit trail, and Team members.

Retrieve the active organization ID in the browser developer console:

```javascript
(await (await fetch('/api/auth/me')).json()).organization_id
```

Copy the returned UUID. In PowerShell, assign it and seed the reference records:

```powershell
$organizationId = 'PASTE-THE-UUID-HERE'
docker compose exec backend python -m app.seed --organization-id $organizationId
```

**Expected result:** the command completes without an error. Refresh the browser and compare the seeded records:

| Record | Expected value |
| --- | --- |
| Supplier | Riyadh Electrical Supplies |
| Purchase order | `PO-2026-001` |
| PO line | 100 cable rolls × SAR 50.00 |
| PO total | SAR 5,000.00 excluding VAT |
| Receipt | `GR-2026-001`, 90 rolls |
| Invoice | `INV-2026-001`, 100 rolls × SAR 55.00 |
| Invoice subtotal/grand total | SAR 5,500.00 excluding VAT |

Running the seed command a second time must not duplicate the reference records.

## 7. Milestone 1 manual acceptance

### 7.1 Authentication and session persistence

1. Refresh the overview page.
2. Sign out.
3. Sign in again using the manual owner account.
4. Open the application in another tab and refresh both tabs.

**Expected result:** protected pages redirect signed-out users to sign-in. Correct credentials restore the same organization and persisted records. An incorrect password shows an error and does not create a session. No password or session token is displayed in the UI or URL.

### 7.2 Supplier CRUD

1. Open **Suppliers** and create `QA Cable Supplier`.
2. Add a test identifier, tax ID, email, phone, and address.
3. Search for `QA Cable`.
4. Edit the phone or address, save, and refresh.
5. Create a second unused supplier, then delete that second supplier.

**Expected result:** the first supplier remains after refresh and reflects the edit. Search narrows the table. The unused supplier can be deleted. A supplier referenced by a PO cannot be deleted and must return a truthful validation error.

### 7.3 Purchase order CRUD and Decimal totals

Create this purchase order:

| Field | Value |
| --- | --- |
| Reference | `PO-QA-001` |
| Date | `2026-10-01` |
| Currency | `SAR` |
| Supplier | QA Cable Supplier |
| SKU | `CBL-100` |
| Description | Cable rolls |
| Quantity | `100` |
| Unit | `roll` |
| Unit price | `50.00` |

**Expected result:** the saved PO displays **SAR 5,000.00**. Refreshing does not change the value. Money is displayed to two decimals and is never shown with floating-point artifacts such as `4999.999999`.

Try saving another PO without a reference or with an invalid currency code.

**Expected result:** validation prevents the save and displays a real error. No success message or partial record appears.

### 7.4 Receipt and invoice CRUD

Create a receipt:

| Field | Value |
| --- | --- |
| Reference | `GR-QA-001` |
| Date | `2026-10-05` |
| PO | `PO-QA-001` |
| Received quantity | `90` |

Create an invoice:

| Field | Value |
| --- | --- |
| Invoice number | `INV-QA-001` |
| Invoice date | `2026-10-09` |
| Due date | `2026-10-31` |
| PO | `PO-QA-001` |
| Quantity | `100` |
| Unit price | `55.00` |

**Expected result:** the receipt shows 90 rolls and the invoice displays **SAR 5,500.00**. Edit the invoice notes, save, refresh, and confirm the change persists. The linked PO cannot be deleted while the receipt or invoice exists.

### 7.5 Membership, roles, and tenant isolation

Use a private/incognito browser session to register a second account and a second organization, for example `tenant-two@example.test` and `Tenant Two QA`.

Before adding that user to the first organization:

1. Search all second-organization lists for `PO-QA-001`, `GR-QA-001`, and `INV-QA-001`.
2. Confirm none appears.
3. Upload a small document in the first organization, copy its review URL, and request that URL while signed into the second organization.

**Expected result:** the second organization sees empty or independent lists. A foreign document URL returns not found/404 and never reveals metadata, preview pixels, or the original file.

Then sign back into the first organization, open **Team members**, and add the already registered second email as **Viewer**.

**Expected result:** the second user can select the first organization and read its records, but cannot create or edit procurement records. Change the role to **Procurement reviewer**; the user’s existing session for that organization is revoked, and after signing in again the permitted review controls appear. Remove the membership and confirm access to the first organization disappears. The owner cannot be removed.

## 8. Milestone 2 document ingestion and bilingual OCR

Use files from `D:\ocr\sample_data\documents`.

### 8.1 Native English purchase order

1. Open **Documents** and select **Upload documents**.
2. Choose type **Purchase order**.
3. Upload `purchase_order_en.pdf`.
4. Open the document and select **Start extraction**.
5. Wait for `REVIEW REQUIRED` and compare the source preview with the extracted fields.

Expected reviewed values:

| Field | Expected value |
| --- | --- |
| Supplier | Noor Cable Supplies |
| Buyer | Madar Projects |
| Number | `PO-2026-001` |
| Date | `2026-10-09` |
| Expected delivery | `2026-10-15` |
| Currency | `SAR` |
| Supplier VAT | `300000000000003` |
| Line SKU | `CBL-100` |
| Description | Electrical Cable Rolls |
| Quantity | `100` |
| Unit | `roll` |
| Unit price | `50.00` |
| Line/grand total | `5000.00` |

Change the number to a unique value such as `PO-DOC-MANUAL-001`, select or create the supplier, and save the draft. Refresh the page.

**Expected result:** the correction survives refresh and appears in correction history. Confirmation remains disabled while there are unsaved edits. After checking the source and acknowledging any warnings, confirm the extraction. The status becomes **Verified and saved**, confirmation cannot be repeated, and Purchase orders contains the new SAR 5,000 record.

### 8.2 Receipt and invoice documents

Upload and review:

- `delivery_note_en.pdf` as a goods receipt
- `invoice_en.pdf` as a supplier invoice

For both documents, select the existing supplier and `PO-DOC-MANUAL-001`, and map the extracted line to its PO line before confirmation.

Expected delivery-note values are `DN-2026-001`, date `2026-10-09`, PO reference `PO-2026-001`, and 90 rolls. Expected invoice values are:

| Field | Expected value |
| --- | --- |
| Invoice number | `INV-2026-001` |
| Invoice date | `2026-10-09` |
| Due date | `2026-11-08` |
| PO reference | `PO-2026-001` |
| Currency | `SAR` |
| Quantity | `100` |
| Unit price | `55.00` |
| Grand total | `5500.00` |

Use unique ledger numbers if the seed has already created the same references.

**Expected result:** confirmation creates one receipt and one invoice linked to the selected PO. Repeating confirmation does not create duplicates. Merely extracting a document does not create a ledger record or run matching.

### 8.3 Arabic, bilingual, scanned, and low-quality evidence

Repeat upload and extraction with:

- `invoice_ar.pdf`
- `invoice_bilingual.pdf`
- `invoice_multipage.pdf`
- `invoice_scanned.png` or `invoice_scanned.pdf`
- `invoice_low_quality.jpg`

For `invoice_ar.pdf`, compare against these values:

| Field | Expected value |
| --- | --- |
| Supplier | `شركة النور للكابلات` |
| Buyer | `شركة المدار للمقاولات` |
| Invoice number | `INV-2026-001` |
| Invoice date | `2026-10-09` |
| Due date | `2026-11-08` |
| Currency | `SAR` |
| Description | `لفات كابلات كهربائية` |
| Quantity | Arabic `١٠٠` normalized to `100` |
| Unit | `لفة` |
| Unit price | `55.00` |
| Grand total | `5500.00` |

**Expected result:** Arabic text is readable in the source and review UI. Number, date, currency, monetary values, and line fields should not become strings such as `svgp.1`. Bilingual evidence remains linked to the source. Multipage totals reflect both pages. Scanned extraction may take longer than native PDF extraction. Low-quality evidence may leave fields empty or uncertain and show warnings; missing values must stay empty until a reviewer corrects them.

### 8.4 Document validation and privacy checks

Create a fake PDF, try to upload it, and remove it afterward:

```powershell
Set-Location D:\ocr
Set-Content -LiteralPath .\not-a-real-document.pdf -Value 'This is not a PDF.'
# Upload this file through Documents, then run:
Remove-Item -LiteralPath .\not-a-real-document.pdf
```

**Expected result:** the upload is rejected because actual content does not match PDF content. Files over the configured size/page/pixel limits, corrupt PDFs, and password-protected PDFs must also return truthful errors. Originals and previews are accessible only to an authenticated member of the owning organization.

## 9. Milestone 3 deterministic matching

Open **Matching**, choose **New match**, and use the original seeded records:

- Supplier invoice: `INV-2026-001`
- Purchase order: `PO-2026-001`
- Mode: three-way
- Receipt: `GR-2026-001`
- Set price, quantity, and absolute tolerances to zero for the reference comparison. Keep total tolerance at zero or `0.01`.

Run the deterministic match and compare every value:

| Result | Expected value |
| --- | ---: |
| Status | Exception |
| Invoice value | SAR 5,500.00 |
| Supported value | SAR 4,500.00 (`90 × 50`) |
| Price variance | SAR 500.00 (`100 × (55 − 50)`) |
| Quantity variance | SAR 500.00 (`(100 − 90) × 50`) |
| Difference against supported | SAR 1,000.00 |
| Required findings | `PRICE MISMATCH`, `QUANTITY MISMATCH`, `PARTIAL DELIVERY` |

Open the line comparison and verify it links the invoice line, PO line, and receipt evidence. Rerun the match.

**Expected result:** rerun creates another immutable run/history entry; it does not overwrite the prior result or modify the PO, receipt, or invoice.

Run the same invoice in **two-way** mode without selecting a receipt.

**Expected result:** price mismatch remains, but receipt-based quantity mismatch is not reported. The engine never performs currency conversion and never changes source ledger records.

Optional tolerance check: set price tolerance to 10% and rerun. A PO price of 50 and invoice price of 55 is exactly at 10%, so the price should pass that tolerance. Restore zero tolerances afterward if you want the reference exception to remain open.

## 10. Milestone 4 exception, approval, audit, and report workflows

### 10.1 Seed scenarios A–H

```powershell
Set-Location D:\ocr
docker compose exec backend python -m app.seed_milestone4 --organization-id $organizationId
```

**Expected result:** the command prints `Milestone 4 demo scenarios A-H are ready`. Running it again must preserve the same references without duplicating them.

Compare the seeded scenarios:

| Scenario | Reference | Expected state or issue |
| --- | --- | --- |
| A | `DEMO-INV-A-MATCHED` | 40 ordered/received/invoiced at SAR 25; matched |
| B | `DEMO-INV-B-PRICE` | 50 at PO price 80 vs invoice price 88; price exception |
| C | `DEMO-INV-C-PARTIAL` | 200 ordered, 120 received, 180 invoiced; partial-delivery/quantity exception |
| D | `DEMO-INV-D-DUPLICATE` and `DEMO/INV/D/DUPLICATE` | normalized duplicate reference finding |
| E | `DEMO-INV-E-REJECTED` | persisted `REJECTED` approval with a reason |
| F | `DEMO-INV-F-OVERRIDE` | authorized variance and persisted `APPROVED` decision |
| G | `DEMO-INV-G-NO-DUE` | missing due date warning/review condition |
| H | `DEMO-INV-H-ARABIC` | Arabic supplier/item text renders correctly and matches |

### 10.2 Exception review

1. Open **Exceptions**.
2. Filter by **BLOCKING** and open the reference match’s price or quantity finding.
3. Assign it to the manual owner/reviewer.
4. Add a comment.
5. Enter a clear decision reason and select **Resolve**.
6. Reopen it, then place it in review or escalate it.

**Expected result:** each action changes persisted state, increments the visible version, and appears after refresh. Comments retain actor and timestamp. The finding remains linked to its source match evidence. Submitting an action from an older tab/version returns a conflict rather than overwriting the newer decision.

Only an owner or organization admin should be able to accept an authorized variance. The reason is required and the resolution remains visible in history.

### 10.3 Approval workflow and blockers

Use a matched invoice such as scenario A:

1. Open **Approvals** and select `DEMO-INV-A-MATCHED`.
2. Select **Submit for review**.
3. Select **Send for finance approval**.
4. Enter a decision reason and select **Approve**.

**Expected result:** the state progresses:

```text
DRAFT -> PENDING_REVIEW -> PENDING_APPROVAL -> APPROVED
```

The decision history records actor, time, transition, and reason. Approval does not create a payment or claim that a supplier has been paid.

Try the same progression on an invoice whose latest run has an unresolved blocking finding or whose source data changed after matching.

**Expected result:** progression is refused with a blocker or stale-match message. Resolve the finding or rerun matching before approval.

For rejection or change-request testing, select an invoice in the applicable review state and choose **Reject** or **Request changes**.

**Expected result:** a reason is mandatory, and the resulting state and reason appear in approval history and Audit trail.

### 10.4 Reports and exports

Open **Reports**.

**Expected result:** cards display real database-derived values for invoices processed, matched, with exceptions, pending approval, approved/rejected, and average review duration. Counts may be higher than the seed baseline if automated or manual tests created extra records; verify the labeled scenarios individually rather than expecting a fixed global total.

Download every available register as both XLSX and CSV:

- Exception register
- Approval register
- Supplier discrepancy summary
- Organization matching history

**Expected result:**

- Downloads require an authenticated session and are not public static URLs.
- CSV opens as UTF-8 and preserves Arabic text.
- XLSX money and quantity cells are numeric, while identifiers remain text.
- User-controlled text beginning with `=`, `+`, `-`, or `@` is escaped and does not execute as a spreadsheet formula.

From a match/approval detail, generate the matching PDF and Excel report.

Compare the PDF against the selected run. It should contain invoice and PO references, due date, receipt references, invoice/supported/variance values, line comparison, exceptions, approval state, and source/audit references. Arabic text must be readable and right-to-left.

Compare the Excel workbook. It must contain these five sheets:

1. `Summary`
2. `Line Item Comparison`
3. `Exceptions`
4. `Approval History`
5. `Audit References`

### 10.5 Audit trail

Open **Audit trail** and search for the approved or rejected invoice reference. Filter by actor and date.

**Expected result:** the table shows the relevant create, match, exception, comment, transition, approval/rejection, and export events. Selecting an event shows actor, entity, timestamp, request ID when available, reason, and before/after state. Audit rows cannot be edited from the UI.

## 11. Final tenant-isolation check for Milestones 2–4

Sign into the independent second organization again and verify:

- Scenario A–H invoices do not appear.
- Matching history is empty or contains only that organization’s own runs.
- Exceptions, approvals, audit events, and report metrics do not include first-organization data.
- First-organization document, match, report-export, and download URLs return not found/404.
- Attempting a mutation with a copied first-organization ID does not change the first organization.

**Expected result:** no first-organization name, reference, amount, file, finding, approval, audit event, or report row is exposed. Automated tests must also pass the database foreign-key and cross-tenant API checks.

## 12. Record your result

Copy this table into your test notes and attach screenshots or command output for any failure:

| Check | Pass/Fail | Evidence or observed result |
| --- | --- | --- |
| Compose config and five services |  |  |
| Backend health endpoint |  |  |
| PostgreSQL pytest suite |  |  |
| Real OCR suite |  |  |
| Frontend typecheck |  |  |
| Frontend lint |  |  |
| Frontend production build |  |  |
| Two Playwright workflows |  |  |
| M1 authentication and sessions |  |  |
| M1 CRUD and exact SAR totals |  |  |
| Membership and tenant isolation |  |  |
| M2 native English extraction |  |  |
| M2 Arabic/bilingual extraction |  |  |
| M2 scanned/low-quality review |  |  |
| M2 confirmation and correction history |  |  |
| M3 exact reference match arithmetic |  |  |
| M3 two-way and rerun behavior |  |  |
| M4 scenario A–H comparison |  |  |
| M4 exception workflow |  |  |
| M4 approval blockers and decisions |  |  |
| M4 PDF/XLSX/CSV reports |  |  |
| M4 audit history |  |  |
| Final cross-tenant checks |  |  |

For a failure, record:

- The exact step and command or button used
- Expected result
- Actual result and complete error text
- Browser URL and affected record reference
- `docker compose ps` output
- Relevant service logs from `docker compose logs --tail 200 SERVICE_NAME`
- A screenshot or Playwright trace when applicable

## 13. Stop the application

When testing is complete:

```powershell
Set-Location D:\ocr
docker compose down
```

**Expected result:** containers stop and are removed while PostgreSQL data, uploads, reports, Redis data, and OCR models remain in named volumes. Use `docker compose up -d` later to resume with the same data.

Use `docker compose down -v` only when you intentionally want to erase the entire disposable test environment.
