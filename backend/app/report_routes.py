from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import models as m
from .config import settings
from .db import get_db
from .security import Context, current, require_permission
from .services import report_service, review_service

router = APIRouter(prefix='/api/reports', tags=['reports'])


def metadata(row):
    return {'id': row.id, 'report_type': row.report_type, 'related_entity_id': row.related_entity_id,
        'status': row.status, 'filename': row.filename, 'content_type': row.content_type,
        'generated_at': row.generated_at.isoformat() if row.generated_at else None, 'error': row.error}


def guard_rate(db, ctx):
    recent = db.scalars(select(m.ReportExport).where(m.ReportExport.organization_id == ctx.org,
        m.ReportExport.created_by == ctx.user.id, m.ReportExport.created_at >= m.now()-timedelta(minutes=1))).all()
    if len(recent) >= 10: raise HTTPException(429, 'Report generation limit reached. Try again in a minute.')


def currency_breakdown(invoices, latest):
    result = defaultdict(lambda: {'invoice_count': 0, 'flagged_value': Decimal('0')})
    for invoice in invoices:
        result[invoice.currency]['invoice_count'] += 1; run = latest.get(invoice.id)
        if run and (run.result_summary or {}).get('finding_count', 0):
            result[invoice.currency]['flagged_value'] += Decimal(str(run.result_summary.get('invoice_value', '0')))
    return {key: {'invoice_count': value['invoice_count'], 'flagged_value': str(value['flagged_value'])} for key, value in result.items()}


@router.get('/dashboard')
def dashboard(ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'view'); invoices = db.scalars(select(m.SupplierInvoice).where(m.SupplierInvoice.organization_id == ctx.org)).all()
    approvals = db.scalars(select(m.InvoiceApproval).where(m.InvoiceApproval.organization_id == ctx.org)).all()
    approval_by = {row.invoice_id: row for row in approvals}; latest = {}; categories = Counter(); flagged = {}; monthly = Counter()
    for invoice in invoices:
        run = review_service.latest_run(db, ctx.org, invoice.id); latest[invoice.id] = run; monthly[invoice.date[:7]] += 1
        if run:
            findings = db.scalars(select(m.MatchFinding).where(m.MatchFinding.organization_id == ctx.org, m.MatchFinding.match_run_id == run.id)).all()
            if findings:
                flagged[invoice.id] = Decimal(str((run.result_summary or {}).get('invoice_value', '0')))
                categories.update(item.code for item in findings)
    decided = [row for row in approvals if row.submitted_at and row.decided_at]
    durations = [(row.decided_at-row.submitted_at).total_seconds()/3600 for row in decided]
    return {'total_invoices_processed': len(invoices), 'total_invoices_matched': sum(bool(run and run.status.startswith('MATCHED')) for run in latest.values()),
        'invoices_with_exceptions': len(flagged), 'invoices_pending_approval': sum((approval_by.get(row.id).status if approval_by.get(row.id) else 'DRAFT') in ('PENDING_REVIEW', 'PENDING_APPROVAL') for row in invoices),
        'approved_invoices': sum(row.status == 'APPROVED' for row in approvals), 'rejected_invoices': sum(row.status == 'REJECTED' for row in approvals),
        'flagged_invoice_value': str(sum(flagged.values(), Decimal('0'))), 'currency_breakdown': currency_breakdown(invoices, latest),
        'exceptions_by_category': dict(categories), 'invoice_volume_over_time': dict(sorted(monthly.items())),
        'average_review_duration_hours': str(Decimal(str(sum(durations)/len(durations))).quantize(Decimal('0.01'))) if durations else None,
        'denominators': {'invoice_count': len(invoices), 'decided_invoice_count': len(decided)}}


@router.get('/exceptions')
def exception_report(ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'view'); rows = db.scalars(select(m.MatchFinding).where(m.MatchFinding.organization_id == ctx.org)).all()
    return {'total': len(rows), 'by_category': dict(Counter(row.code for row in rows)), 'by_severity': dict(Counter(row.severity for row in rows)), 'by_status': dict(Counter(row.resolution_status for row in rows))}


@router.get('/approvals')
def approval_report(ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'view'); rows = db.scalars(select(m.InvoiceApproval).where(m.InvoiceApproval.organization_id == ctx.org)).all()
    return {'total': len(rows), 'by_status': dict(Counter(row.status for row in rows))}


def existing(db, ctx, report_type, related, snapshot):
    rows = db.scalars(select(m.ReportExport).where(m.ReportExport.organization_id == ctx.org, m.ReportExport.report_type == report_type,
        m.ReportExport.related_entity_id == related, m.ReportExport.status == 'COMPLETED').order_by(m.ReportExport.created_at.desc()).limit(10)).all()
    return next((row for row in rows if row.snapshot == snapshot and row.storage_key and Path(row.storage_key).exists()), None)


@router.post('/matching/{match_id}/pdf', status_code=201)
def matching_pdf(match_id: str, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'export'); guard_rate(db, ctx); snapshot = report_service.report_snapshot(db, ctx.org, match_id)
    cached = existing(db, ctx, 'MATCHING_PDF', match_id, snapshot)
    if cached: return metadata(cached)
    organization = db.get(m.Organization, ctx.org); content = report_service.build_pdf(snapshot, organization.name, m.now().isoformat())
    return metadata(report_service.persist_export(db, ctx, 'MATCHING_PDF', match_id, f'match-{match_id}.pdf', 'application/pdf', content, snapshot))


@router.post('/matching/{match_id}/excel', status_code=201)
def matching_excel(match_id: str, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'export'); guard_rate(db, ctx); snapshot = report_service.report_snapshot(db, ctx.org, match_id)
    cached = existing(db, ctx, 'MATCHING_EXCEL', match_id, snapshot)
    if cached: return metadata(cached)
    content = report_service.build_matching_excel(snapshot)
    return metadata(report_service.persist_export(db, ctx, 'MATCHING_EXCEL', match_id, f'match-{match_id}.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', content, snapshot))


def exception_rows(db, organization_id):
    rows = []
    for item in db.scalars(select(m.MatchFinding).where(m.MatchFinding.organization_id == organization_id).order_by(m.MatchFinding.created_at.desc())):
        run = db.scalar(select(m.MatchRun).where(m.MatchRun.organization_id == organization_id, m.MatchRun.id == item.match_run_id))
        invoice = db.scalar(select(m.SupplierInvoice).where(m.SupplierInvoice.organization_id == organization_id, m.SupplierInvoice.id == run.invoice_id))
        rows.append([invoice.number, item.code, item.severity, item.expected_value, item.actual_value, item.difference, item.unit, item.resolution_status, item.created_at])
    return rows


@router.post('/exceptions/export', status_code=201)
def export_exceptions(format: str = Query('xlsx', pattern='^(xlsx|csv)$'), ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'export'); guard_rate(db, ctx); headers = ['Invoice Number', 'Finding', 'Severity', 'Expected', 'Actual', 'Difference', 'Unit', 'Status', 'Created At']; rows = exception_rows(db, ctx.org)
    content = report_service.build_csv(headers, rows) if format == 'csv' else report_service.build_register_excel(headers, rows, 'Exceptions')
    content_type = 'text/csv; charset=utf-8' if format == 'csv' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    return metadata(report_service.persist_export(db, ctx, f'EXCEPTIONS_{format.upper()}', None, f'exceptions.{format}', content_type, content, {'row_count': len(rows), 'organization_id': ctx.org}))


@router.post('/approvals/export', status_code=201)
def export_approvals(format: str = Query('xlsx', pattern='^(xlsx|csv)$'), ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'export'); guard_rate(db, ctx); headers = ['Invoice Number', 'Status', 'Submitted At', 'Decided At', 'Reason']; rows = []
    for approval in db.scalars(select(m.InvoiceApproval).where(m.InvoiceApproval.organization_id == ctx.org).order_by(m.InvoiceApproval.created_at.desc())):
        invoice = db.scalar(select(m.SupplierInvoice).where(m.SupplierInvoice.organization_id == ctx.org, m.SupplierInvoice.id == approval.invoice_id)); rows.append([invoice.number, approval.status, approval.submitted_at, approval.decided_at, approval.decision_reason])
    content = report_service.build_csv(headers, rows) if format == 'csv' else report_service.build_register_excel(headers, rows, 'Approvals')
    content_type = 'text/csv; charset=utf-8' if format == 'csv' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    return metadata(report_service.persist_export(db, ctx, f'APPROVALS_{format.upper()}', None, f'approvals.{format}', content_type, content, {'row_count': len(rows), 'organization_id': ctx.org}))


def _register_export(db, ctx, name, headers, rows, format):
    content = report_service.build_csv(headers, rows) if format == 'csv' else report_service.build_register_excel(headers, rows, name.replace('_', ' ').title())
    content_type = 'text/csv; charset=utf-8' if format == 'csv' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    return metadata(report_service.persist_export(db, ctx, f'{name.upper()}_{format.upper()}', None,
        f'{name.lower()}.{format}', content_type, content, {'row_count': len(rows), 'organization_id': ctx.org}))


@router.post('/suppliers/export', status_code=201)
def export_supplier_discrepancies(format: str = Query('xlsx', pattern='^(xlsx|csv)$'), ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'export'); guard_rate(db, ctx)
    headers = ['Supplier', 'Invoice Count', 'Invoices With Exceptions', 'Finding Count', 'Blocking Findings', 'Flagged Value By Currency']
    rows = []
    suppliers = db.scalars(select(m.Supplier).where(m.Supplier.organization_id == ctx.org).order_by(m.Supplier.name)).all()
    for supplier in suppliers:
        invoices = db.scalars(select(m.SupplierInvoice).where(m.SupplierInvoice.organization_id == ctx.org,
            m.SupplierInvoice.supplier_id == supplier.id)).all()
        flagged = defaultdict(Decimal); finding_count = blocking = exception_invoices = 0
        for invoice in invoices:
            run = review_service.latest_run(db, ctx.org, invoice.id)
            findings = db.scalars(select(m.MatchFinding).where(m.MatchFinding.organization_id == ctx.org,
                m.MatchFinding.match_run_id == run.id)).all() if run else []
            if findings:
                exception_invoices += 1; finding_count += len(findings); blocking += sum(item.severity == 'BLOCKING' for item in findings)
                flagged[invoice.currency] += Decimal(str((run.result_summary or {}).get('invoice_value', '0')))
        rows.append([supplier.name, len(invoices), exception_invoices, finding_count, blocking,
            '; '.join(f'{currency} {amount}' for currency, amount in sorted(flagged.items()))])
    return _register_export(db, ctx, 'supplier_discrepancies', headers, rows, format)


@router.post('/matching-history/export', status_code=201)
def export_matching_history(format: str = Query('xlsx', pattern='^(xlsx|csv)$'), ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'export'); guard_rate(db, ctx)
    headers = ['Run ID', 'Invoice Number', 'Purchase Order', 'Mode', 'Status', 'Currency', 'Invoice Value', 'Supported Value', 'Difference', 'Created At']
    rows = []
    runs = db.scalars(select(m.MatchRun).where(m.MatchRun.organization_id == ctx.org).order_by(m.MatchRun.created_at.desc())).all()
    for run in runs:
        summary = run.result_summary or {}
        rows.append([run.id, summary.get('invoice_number'), summary.get('purchase_order_number'), run.matching_mode, run.status,
            summary.get('currency'), Decimal(str(summary.get('invoice_value', '0'))), Decimal(str(summary.get('supported_value', '0'))),
            Decimal(str(summary.get('difference_against_supported', '0'))), run.created_at])
    return _register_export(db, ctx, 'matching_history', headers, rows, format)


@router.get('/exports/{identifier}')
def export_status(identifier: str, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'view'); row = db.scalar(select(m.ReportExport).where(m.ReportExport.organization_id == ctx.org, m.ReportExport.id == identifier))
    if not row: raise HTTPException(404, 'Report export not found')
    return metadata(row)


@router.get('/exports/{identifier}/download')
def download(identifier: str, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'export'); row = db.scalar(select(m.ReportExport).where(m.ReportExport.organization_id == ctx.org, m.ReportExport.id == identifier, m.ReportExport.status == 'COMPLETED'))
    if not row or not row.storage_key: raise HTTPException(404, 'Report export not found')
    root = Path(settings.report_storage_path).resolve(); path = Path(row.storage_key).resolve()
    if root not in path.parents or not path.is_file(): raise HTTPException(404, 'Report file is unavailable')
    return FileResponse(path, media_type=row.content_type, filename=row.filename, headers={'Cache-Control': 'private, no-store'})
