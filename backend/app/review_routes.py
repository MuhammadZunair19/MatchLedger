from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import models as m
from .db import get_db
from .review_schemas import AssignException, CommentInput, ExceptionAction
from .security import Context, current, require_permission
from .services import review_service as service

router = APIRouter(tags=['review'])


def _exception_output(db, finding, review=None):
    run = db.scalar(select(m.MatchRun).where(m.MatchRun.organization_id == finding.organization_id, m.MatchRun.id == finding.match_run_id))
    invoice = db.scalar(select(m.SupplierInvoice).where(m.SupplierInvoice.organization_id == finding.organization_id, m.SupplierInvoice.id == run.invoice_id))
    order = db.scalar(select(m.PurchaseOrder).where(m.PurchaseOrder.organization_id == finding.organization_id, m.PurchaseOrder.id == run.purchase_order_id))
    supplier = db.scalar(select(m.Supplier).where(m.Supplier.organization_id == finding.organization_id, m.Supplier.id == invoice.supplier_id))
    assigned = db.get(m.User, review.assigned_to) if review and review.assigned_to else None
    result = service.public(finding)
    result.update({'invoice_id': invoice.id, 'invoice_number': invoice.number, 'invoice_total': str(invoice.grand_total or invoice.subtotal or (run.result_summary or {}).get('invoice_value') or '0'),
        'purchase_order_id': order.id if order else None, 'purchase_order_number': order.number if order else None,
        'supplier_id': supplier.id, 'supplier_name': supplier.name, 'match_status': run.status,
        'document_versions': run.document_versions, 'status': review.status if review else finding.resolution_status,
        'assigned_to': review.assigned_to if review else None, 'assigned_name': assigned.name if assigned else None,
        'resolution_type': review.resolution_type if review else None, 'resolution_reason': review.resolution_reason if review else None,
        'version': review.version if review else 1})
    return result


@router.get('/api/exceptions')
def exceptions(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), q: str = '',
               status: str | None = None, severity: str | None = None, code: str | None = None,
               assigned_to: str | None = None, supplier_id: str | None = None,
               date_from: datetime | None = None, date_to: datetime | None = None,
               ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'view')
    query = select(m.MatchFinding).where(m.MatchFinding.organization_id == ctx.org)
    if severity: query = query.where(m.MatchFinding.severity == severity)
    if code: query = query.where(m.MatchFinding.code == code)
    if date_from: query = query.where(m.MatchFinding.created_at >= date_from)
    if date_to: query = query.where(m.MatchFinding.created_at <= date_to)
    findings = db.scalars(query.order_by(m.MatchFinding.created_at.desc())).all()
    rows = []
    for finding in findings:
        review = db.scalar(select(m.ExceptionReview).where(m.ExceptionReview.organization_id == ctx.org,
            m.ExceptionReview.match_finding_id == finding.id))
        output = _exception_output(db, finding, review)
        if status and output['status'] != status: continue
        if assigned_to and output['assigned_to'] != assigned_to: continue
        if supplier_id and output['supplier_id'] != supplier_id: continue
        if q and q.casefold() not in f"{output['invoice_number']} {output['purchase_order_number']} {output['supplier_name']} {output['code']}".casefold(): continue
        rows.append(output)
    start = (page-1)*page_size
    distinct_invoices = {row['invoice_id']: (Decimal(row['invoice_total']),
        db.get(m.SupplierInvoice, row['invoice_id']).currency) for row in rows}
    flagged_by_currency = {}
    for amount, currency in distinct_invoices.values():
        flagged_by_currency[currency] = flagged_by_currency.get(currency, Decimal('0')) + amount
    metrics = {'open': sum(row['status'] == 'OPEN' for row in rows), 'in_review': sum(row['status'] == 'IN_REVIEW' for row in rows),
        'resolved': sum(row['status'] in ('RESOLVED', 'ACCEPTED_VARIANCE') for row in rows),
        'escalated': sum(row['status'] == 'ESCALATED' for row in rows), 'invoices_requiring_review': len(distinct_invoices),
        'flagged_invoice_value': str(sum((amount for amount, _ in distinct_invoices.values()), Decimal('0'))),
        'flagged_value_by_currency': {currency: str(amount) for currency, amount in sorted(flagged_by_currency.items())},
        'by_category': {name: sum(row['code'] == name for row in rows) for name in sorted({row['code'] for row in rows})}}
    return {'items': rows[start:start+page_size], 'total': len(rows), 'page': page, 'page_size': page_size, 'metrics': metrics}


@router.get('/api/exceptions/{identifier}')
def exception_detail(identifier: str, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'view'); finding = service.finding(db, ctx.org, identifier)
    review = service.exception_review(db, ctx, finding, create=False)
    output = _exception_output(db, finding, review)
    output['comments'] = comments(entity_type='exception', entity_id=identifier, ctx=ctx, db=db)
    output['history'] = [service.public(row) for row in db.scalars(select(m.AuditEvent).where(m.AuditEvent.organization_id == ctx.org,
        m.AuditEvent.entity_type == 'match_findings', m.AuditEvent.entity_id == identifier).order_by(m.AuditEvent.created_at)).all()]
    return output


def _assignee(db, ctx, user_id):
    membership = db.scalar(select(m.Membership).where(m.Membership.organization_id == ctx.org, m.Membership.user_id == user_id))
    if not membership or membership.role not in ('owner', 'organization_admin', 'member', 'procurement_reviewer'):
        raise HTTPException(422, 'Assignee must be an organization reviewer')


@router.post('/api/exceptions/{identifier}/assign')
def assign_exception(identifier: str, data: AssignException, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'admin'); _assignee(db, ctx, data.user_id)
    return service.public(service.update_exception(db, ctx, identifier, data.version, 'IN_REVIEW', 'exception_assigned', assigned_to=data.user_id))


@router.post('/api/exceptions/{identifier}/resolve')
def resolve_exception(identifier: str, data: ExceptionAction, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'review')
    return service.public(service.update_exception(db, ctx, identifier, data.version, 'RESOLVED', 'exception_resolved', data.reason, resolution_type='CORRECTED_OR_EXPLAINED'))


@router.post('/api/exceptions/{identifier}/accept-variance')
def accept_variance(identifier: str, data: ExceptionAction, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'admin')
    return service.public(service.update_exception(db, ctx, identifier, data.version, 'ACCEPTED_VARIANCE', 'variance_accepted', data.reason, resolution_type='AUTHORIZED_VARIANCE'))


@router.post('/api/exceptions/{identifier}/escalate')
def escalate(identifier: str, data: ExceptionAction, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'review')
    return service.public(service.update_exception(db, ctx, identifier, data.version, 'ESCALATED', 'exception_escalated', data.reason))


@router.post('/api/exceptions/{identifier}/request-clarification')
def request_clarification(identifier: str, data: ExceptionAction, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'review')
    return service.public(service.update_exception(db, ctx, identifier, data.version, 'AWAITING_SUPPLIER', 'clarification_requested', data.reason))


@router.post('/api/exceptions/{identifier}/reopen')
def reopen(identifier: str, data: ExceptionAction, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'review')
    return service.public(service.update_exception(db, ctx, identifier, data.version, 'OPEN', 'exception_reopened', data.reason))


@router.get('/api/reviews/comments')
def comments(entity_type: str, entity_id: str, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'view')
    rows = db.scalars(select(m.ReviewComment).where(m.ReviewComment.organization_id == ctx.org,
        m.ReviewComment.entity_type == entity_type, m.ReviewComment.entity_id == entity_id).order_by(m.ReviewComment.created_at)).all()
    result = []
    for row in rows:
        value = service.public(row); author = db.get(m.User, row.author_id); value['author_name'] = author.name if author else 'Unknown'; result.append(value)
    return result


@router.post('/api/reviews/comments', status_code=201)
def add_comment(data: CommentInput, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    permission = 'review' if data.entity_type == 'exception' else 'approve'
    if data.entity_type == 'invoice' and ctx.membership.role in ('owner', 'organization_admin', 'member', 'procurement_reviewer'):
        permission = 'review'
    require_permission(ctx, permission)
    if data.entity_type == 'exception': service.finding(db, ctx.org, data.entity_id)
    else: service.invoice(db, ctx.org, data.entity_id)
    row = m.ReviewComment(organization_id=ctx.org, created_by=ctx.user.id, updated_by=ctx.user.id,
        entity_type=data.entity_type, entity_id=data.entity_id, author_id=ctx.user.id, body=data.body)
    db.add(row); db.flush(); service.audit(db, ctx, 'review_comment_added', data.entity_type, data.entity_id, new={'comment_id': row.id}); db.commit()
    value = service.public(row); value['author_name'] = ctx.user.name; return value


@router.get('/api/audit/events')
def audit_events(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100), q: str = '', action: str | None = None,
                 user_id: str | None = None, date_from: datetime | None = None, date_to: datetime | None = None,
                 ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'view'); query = select(m.AuditEvent).where(m.AuditEvent.organization_id == ctx.org)
    if action: query = query.where(m.AuditEvent.action == action)
    if user_id: query = query.where(m.AuditEvent.created_by == user_id)
    if date_from: query = query.where(m.AuditEvent.created_at >= date_from)
    if date_to: query = query.where(m.AuditEvent.created_at <= date_to)
    rows = db.scalars(query.order_by(m.AuditEvent.created_at.desc())).all()
    if q:
        invoice_ids = set(db.scalars(select(m.SupplierInvoice.id).where(m.SupplierInvoice.organization_id == ctx.org,
            m.SupplierInvoice.number.icontains(q, autoescape=True))).all())
        finding_ids = set(db.scalars(select(m.MatchFinding.id).join(m.MatchRun,
            m.MatchRun.id == m.MatchFinding.match_run_id).where(m.MatchFinding.organization_id == ctx.org,
            m.MatchRun.organization_id == ctx.org, m.MatchRun.invoice_id.in_(invoice_ids or ['']))).all())
        rows = [row for row in rows if row.entity_id in invoice_ids | finding_ids or
            q.casefold() in f'{row.action} {row.entity_type} {row.entity_id} {row.reason or ""}'.casefold()]
    start=(page-1)*page_size
    items = []
    for row in rows[start:start+page_size]:
        value = service.public(row); actor = db.get(m.User, row.created_by) if row.created_by else None
        value['actor_name'] = actor.name if actor else 'System'; items.append(value)
    return {'items': items, 'total': len(rows), 'page': page, 'page_size': page_size}


@router.get('/api/audit/events/{identifier}')
def audit_event(identifier: str, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'view'); row = db.scalar(select(m.AuditEvent).where(m.AuditEvent.organization_id == ctx.org, m.AuditEvent.id == identifier))
    if not row: raise HTTPException(404, 'Audit event not found')
    value = service.public(row); actor = db.get(m.User, row.created_by) if row.created_by else None
    value['actor_name'] = actor.name if actor else 'System'; return value
