# Milestone 3: deterministic matching

Milestone 3 adds verified invoice identity fields and a deterministic matching workspace. It does not use an LLM or external financial service, and it never converts currencies or changes the underlying PO, receipt or invoice.

## Reference scenario

Seed an organization using the README command. The sample records are:

- PO `PO-2026-001`: 100 cable rolls at SAR 50, value SAR 5,000 excluding VAT.
- Receipt `GR-2026-001`: 90 rolls.
- Invoice `INV-2026-001`: invoice date 2026-10-01, due date 2026-10-31, 100 rolls at SAR 55, value SAR 5,500 excluding VAT.

Open **Matching**, choose the invoice, three-way mode, PO and receipt, then run the comparison. With zero tolerances the expected summary is invoice value SAR 5,500, supported value SAR 4,500, price variance SAR 500, quantity variance SAR 500 and total difference SAR 1,000. The run is an exception with price mismatch, quantity mismatch and partial-delivery findings.

## Matching rules

Two-way matching compares the PO and invoice. Three-way matching also limits supported quantity to verified receipts. Previous verified invoices against the PO reduce its remaining quantity. Duplicate invoice numbers are normalized only for comparison; leading zeroes remain significant.

Line association priority is a reviewer-confirmed mapping, an explicit linked PO line, exact SKU, exact normalized description, then a RapidFuzz suggestion. Fuzzy associations remain review-required until a user selects the PO line. Multiple invoice lines may map to one PO line. Units must match or use an explicit organization conversion such as `box->unit`; the engine never guesses a conversion.

Money uses PostgreSQL `NUMERIC`, Python `Decimal`, precision 50 for intermediate operations and half-up rounding to two decimals for displayed monetary results. A unit price passes when either the absolute or percentage tolerance passes. Total and quantity tolerances are evaluated separately.

Each run stores settings, selected receipt IDs, document review revisions, source record timestamps, an input fingerprint, summary and findings. Rerun creates a new run. Findings contain code, severity, explanation, line IDs, expected and actual values, difference, units, evidence and applicable tolerance.

## Invoice extraction acceptance

Supplier invoices use separate `invoice_number`, `invoice_date` and `due_date` fields. Aliases include common English forms such as Invoice No., Invoice #, Bill Number, Issue Date, Payment Due and Pay By, plus Arabic labels including رقم الفاتورة, تاريخ الفاتورة, تاريخ الإصدار, تاريخ الاستحقاق and موعد السداد. Missing due dates remain empty. Ambiguous dates remain review warnings. Confirmation persists reviewed values into the supplier invoice; matching never consumes an unverified extraction.

## Checks

```powershell
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python -m pytest tests/backend/test_matching_engine.py tests/backend/test_matching_service.py -q
.\.venv\Scripts\python -m pytest -q
Set-Location frontend
npm.cmd run typecheck
npm.cmd run build
```

For PostgreSQL integration, set `TEST_DATABASE_URL` as shown in the README. No service needs to remain running after the checks.
