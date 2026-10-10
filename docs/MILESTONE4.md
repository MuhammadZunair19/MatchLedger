# Milestone 4: exception review, approvals and reports

Milestone 4 turns persisted matching findings into an operational review workflow. It is a development milestone and is not production-ready financial software.

## Roles and decisions

- **Owner / organization admin:** membership roles, review policy, assignment, variance acceptance, review, approval and exports.
- **Procurement reviewer / member:** review findings, comments, escalation, resolution, and invoice submission.
- **Finance approver:** finance approval, rejection/change requests, reports and exports.
- **Viewer:** read-only workspaces and permitted exports.

The optional segregation-of-duties policy prevents the user who submitted an invoice from making its final approval. Role changes revoke the affected member's current organization sessions. Backend permission checks are authoritative.

An invoice progresses through `DRAFT`, `PENDING_REVIEW`, `PENDING_APPROVAL`, and `APPROVED`. A finance approver may choose `REJECTED` or `CHANGES_REQUESTED` with a reason. Approval is refused when the latest match is stale or has unresolved blocking findings. Each transition uses a row lock and client-visible version so concurrent stale decisions return HTTP 409. Historical `ApprovalDecision` rows are append-only through the API.

Approval is not payment. MatchLedger stores no payment instruction, payment status, settlement, bank account, or disbursement event.

## Workspaces

- `/exceptions` provides real counts, search and filters, evidence links, reviewer assignment, comments, resolution, clarification, escalation, authorized variance acceptance and reopening.
- `/approvals` provides a due-date ordered queue, current match evidence, blockers, comments, decision history, workflow actions, and matching-report exports.
- `/reports` computes distinct-invoice metrics from the current database and exports the exception register, approval register, supplier discrepancy summary and organization matching history as XLSX or CSV.
- `/audit` searches recorded actions and displays before/after state and decision reasons.

## Report behavior

Matching PDF and Excel reports use a saved match-run snapshot plus current persisted resolution and approval state. The PDF contains invoice and PO references, due date, receipt references, values, line comparison, exceptions, approval state and audit/source references. Arial on Windows and DejaVu Sans in the application image provide Unicode and Arabic glyph support; Arabic strings are reshaped and rendered right-to-left.

The Excel report contains Summary, Line Item Comparison, Exceptions, Approval History and Audit References sheets. Quantities and money are numeric cells with number formats. User text beginning with `=`, `+`, `-`, or `@` is escaped before spreadsheet output. CSV is UTF-8 with a BOM. Report files live in `REPORT_STORAGE_PATH`, are never exposed as static assets, and require an authenticated, authorized download request.

## Demo data

Register an owner and copy the active organization ID from `/api/auth/me`, then run:

```powershell
docker compose exec backend python -m app.seed --organization-id YOUR_ORGANIZATION_ID
docker compose exec backend python -m app.seed_milestone4 --organization-id YOUR_ORGANIZATION_ID
```

The first command creates the established 100 ordered / 90 received / 100 invoiced cable-roll scenario. The second creates labeled scenarios A-H: matched, price mismatch, partial delivery, normalized duplicate invoice, rejected invoice, authorized variance, missing due date, and Arabic supplier/product content. It also records a real rejected decision and a clearly labeled authorized variance/approval. Both scripts are repeatable and create no users or secrets.

## Configuration

`REPORT_STORAGE_PATH` defaults to `../private_reports` locally. Docker Compose mounts `/workspace/private_reports` as a named private volume. Generate reports only after applying the latest migration:

```powershell
Set-Location D:\ocr\backend
..\.venv\Scripts\python -m alembic upgrade head
```

Small exports are generated synchronously and rate-limited to ten per user per minute. The `ReportExport` model already carries queued/processing/completed/failed status fields for a later background-worker threshold.
