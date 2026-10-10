from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import models as m
from .db import get_db
from .review_schemas import ApprovalAction, PolicyInput
from .security import Context, current, require_permission
from .services import review_service as service

router = APIRouter(prefix='/api/approvals', tags=['approvals'])


def output(db, ctx, invoice, approval=None):
    run = service.latest_run(db, ctx.org, invoice.id)
    supplier = db.scalar(select(m.Supplier).where(m.Supplier.organization_id == ctx.org, m.Supplier.id == invoice.supplier_id))
    approval = approval or service.approval(db, ctx, invoice, create=False)
    lines = db.scalars(select(m.SupplierInvoiceLine).where(m.SupplierInvoiceLine.organization_id == ctx.org,
        m.SupplierInvoiceLine.parent_id == invoice.id)).all()
    total = invoice.grand_total or invoice.subtotal or sum((line.quantity*line.unit_price for line in lines), Decimal('0'))
    blockers = service.unresolved_blocking(db, ctx.org, run.id) if run else []
    submitted_user = db.get(m.User, approval.submitted_by) if approval and approval.submitted_by else None
    decided_user = db.get(m.User, approval.decided_by) if approval and approval.decided_by else None
    return {'invoice_id': invoice.id, 'invoice_number': invoice.number, 'invoice_date': invoice.date, 'due_date': invoice.due_date,
        'supplier_id': supplier.id, 'supplier_name': supplier.name, 'currency': invoice.currency, 'total': str(total),
        'approval_status': approval.status if approval else 'DRAFT', 'approval_version': approval.version if approval else 1,
        'match_run': service.public(run) if run else None, 'match_status': run.status if run else 'NOT_RUN',
        'exception_count': len(db.scalars(select(m.MatchFinding).where(m.MatchFinding.organization_id == ctx.org,
            m.MatchFinding.match_run_id == run.id)).all()) if run else 0,
        'blocking_count': len(blockers), 'matching_stale': service.is_stale(invoice, run),
        'submitted_by': approval.submitted_by if approval else None, 'submitted_name': submitted_user.name if submitted_user else None,
        'submitted_at': approval.submitted_at.isoformat() if approval and approval.submitted_at else None,
        'decided_by': approval.decided_by if approval else None, 'decided_at': approval.decided_at.isoformat() if approval and approval.decided_at else None,
        'decided_name': decided_user.name if decided_user else None, 'decision_reason': approval.decision_reason if approval else None}


@router.get('')
def approvals(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), q: str = '', status: str | None = None,
              ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'view'); invoices = db.scalars(select(m.SupplierInvoice).where(m.SupplierInvoice.organization_id == ctx.org).order_by(m.SupplierInvoice.created_at.desc())).all()
    rows = [output(db, ctx, row) for row in invoices]
    if status: rows = [row for row in rows if row['approval_status'] == status]
    if q: rows = [row for row in rows if q.casefold() in f"{row['invoice_number']} {row['supplier_name']}".casefold()]
    rows.sort(key=lambda row: row['due_date'] or '9999-12-31')
    start=(page-1)*page_size
    return {'items': rows[start:start+page_size], 'total': len(rows), 'page': page, 'page_size': page_size}


@router.get('/policy')
def get_policy(ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'view'); row = db.scalar(select(m.ReviewPolicy).where(m.ReviewPolicy.organization_id == ctx.org))
    return {'segregation_of_duties': row.segregation_of_duties if row else False}


@router.put('/policy')
def set_policy(data: PolicyInput, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'admin'); row = db.scalar(select(m.ReviewPolicy).where(m.ReviewPolicy.organization_id == ctx.org))
    if not row:
        row = m.ReviewPolicy(organization_id=ctx.org, created_by=ctx.user.id, updated_by=ctx.user.id)
        db.add(row); db.flush()
    old={'segregation_of_duties': row.segregation_of_duties}; row.segregation_of_duties=data.segregation_of_duties
    service.audit(db, ctx, 'review_policy_changed', 'review_policies', row.id, old, {'segregation_of_duties': row.segregation_of_duties})
    db.add(row); db.commit(); return {'segregation_of_duties': row.segregation_of_duties}


@router.get('/{invoice_id}')
def approval_detail(invoice_id: str, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'view'); invoice = service.invoice(db, ctx.org, invoice_id); result = output(db, ctx, invoice)
    run = service.latest_run(db, ctx.org, invoice.id)
    result['findings'] = [service.public(row) for row in db.scalars(select(m.MatchFinding).where(m.MatchFinding.organization_id == ctx.org,
        m.MatchFinding.match_run_id == run.id)).all()] if run else []
    result['comments'] = [service.public(row) for row in db.scalars(select(m.ReviewComment).where(m.ReviewComment.organization_id == ctx.org,
        m.ReviewComment.entity_type == 'invoice', m.ReviewComment.entity_id == invoice.id).order_by(m.ReviewComment.created_at)).all()]
    result['decisions'] = [service.public(row) for row in db.scalars(select(m.ApprovalDecision).where(m.ApprovalDecision.organization_id == ctx.org,
        m.ApprovalDecision.invoice_id == invoice.id).order_by(m.ApprovalDecision.created_at)).all()]
    result['documents'] = (run.document_versions if run else {})
    return result


def locked(db, ctx, invoice_id, version):
    invoice = service.invoice(db, ctx.org, invoice_id)
    approval = service.approval(db, ctx, invoice)
    db.refresh(approval, with_for_update=True)
    if approval.version != version: raise HTTPException(409, 'This approval changed. Reload and try again.')
    return invoice, approval


@router.post('/{invoice_id}/submit')
def submit(invoice_id: str, data: ApprovalAction, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'review'); invoice, approval = locked(db, ctx, invoice_id, data.version)
    if approval.status in ('PENDING_APPROVAL', 'APPROVED'): return output(db, ctx, invoice, approval)
    if approval.status not in ('DRAFT', 'CHANGES_REQUESTED', 'PENDING_REVIEW'): raise HTTPException(409, 'Invoice cannot be submitted from its current status')
    target = 'PENDING_REVIEW' if approval.status in ('DRAFT', 'CHANGES_REQUESTED') else 'PENDING_APPROVAL'
    return output(db, ctx, invoice, service.decision(db, ctx, invoice, approval, target, data.reason))


def _decide(db, ctx, invoice_id, data, target):
    require_permission(ctx, 'approve'); invoice, approval = locked(db, ctx, invoice_id, data.version)
    if approval.status == target: return output(db, ctx, invoice, approval)
    allowed = {'APPROVED': {'PENDING_APPROVAL'}, 'REJECTED': {'PENDING_APPROVAL', 'PENDING_REVIEW'}, 'CHANGES_REQUESTED': {'PENDING_APPROVAL', 'PENDING_REVIEW'}}
    if approval.status not in allowed[target]: raise HTTPException(409, f'Invoice cannot transition from {approval.status} to {target}')
    if target in ('REJECTED', 'CHANGES_REQUESTED') and not data.reason: raise HTTPException(422, 'A reason is required')
    policy = db.scalar(select(m.ReviewPolicy).where(m.ReviewPolicy.organization_id == ctx.org))
    if target == 'APPROVED' and policy and policy.segregation_of_duties and approval.submitted_by == ctx.user.id:
        raise HTTPException(403, 'Segregation of duties prevents the submitter from approving this invoice')
    return output(db, ctx, invoice, service.decision(db, ctx, invoice, approval, target, data.reason))


@router.post('/{invoice_id}/approve')
def approve(invoice_id: str, data: ApprovalAction, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    return _decide(db, ctx, invoice_id, data, 'APPROVED')


@router.post('/{invoice_id}/reject')
def reject(invoice_id: str, data: ApprovalAction, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    return _decide(db, ctx, invoice_id, data, 'REJECTED')


@router.post('/{invoice_id}/request-changes')
def request_changes(invoice_id: str, data: ApprovalAction, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    return _decide(db, ctx, invoice_id, data, 'CHANGES_REQUESTED')
