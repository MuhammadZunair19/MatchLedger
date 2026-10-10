from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select
from .. import models as m
from ..request_context import request_id

FINAL_EXCEPTION = {'RESOLVED', 'ACCEPTED_VARIANCE', 'REJECTED'}


def public(row):
    result = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        if isinstance(value, Decimal): value = str(value)
        elif hasattr(value, 'isoformat'): value = value.isoformat()
        result[column.name] = value
    return result


def finding(db, org, identifier):
    row = db.scalar(select(m.MatchFinding).where(m.MatchFinding.organization_id == org, m.MatchFinding.id == identifier))
    if not row: raise HTTPException(404, 'Exception not found')
    return row


def exception_review(db, ctx, finding_row, create=True):
    row = db.scalar(select(m.ExceptionReview).where(m.ExceptionReview.organization_id == ctx.org,
        m.ExceptionReview.match_finding_id == finding_row.id))
    if not row and create:
        row = m.ExceptionReview(organization_id=ctx.org, created_by=ctx.user.id, updated_by=ctx.user.id,
            match_finding_id=finding_row.id, status=finding_row.resolution_status or 'OPEN')
        db.add(row); db.flush()
    return row


def audit(db, ctx, action, entity_type, entity_id, old=None, new=None, reason=None, detail=None):
    db.add(m.AuditEvent(organization_id=ctx.org, created_by=ctx.user.id, updated_by=ctx.user.id,
        action=action, entity_type=entity_type, entity_id=entity_id, detail=detail or {},
        old_state=old, new_state=new, reason=reason, request_id=request_id()))


def update_exception(db, ctx, identifier, version, status, action, reason=None, assigned_to=None, resolution_type=None):
    finding_row = finding(db, ctx.org, identifier)
    if finding_row.severity == 'BLOCKING' and status == 'RESOLVED' and ctx.membership.role not in ('owner', 'organization_admin'):
        raise HTTPException(403, 'An organization administrator must resolve a blocking finding; reviewers can escalate it')
    review = exception_review(db, ctx, finding_row)
    db.refresh(review, with_for_update=True)
    if review.version != version: raise HTTPException(409, 'This exception changed. Reload and try again.')
    old = {'status': review.status, 'assigned_to': review.assigned_to, 'version': review.version}
    if status == 'OPEN' and review.status not in FINAL_EXCEPTION | {'ESCALATED', 'AWAITING_SUPPLIER'}:
        raise HTTPException(409, 'Only a resolved, rejected, escalated or awaiting-supplier exception can be reopened')
    review.status = status; review.version += 1; review.updated_by = ctx.user.id; review.updated_at = m.now()
    if assigned_to is not None: review.assigned_to = assigned_to
    if resolution_type is not None: review.resolution_type = resolution_type
    if status in FINAL_EXCEPTION:
        review.resolution_reason = reason; review.resolved_by = ctx.user.id; review.resolved_at = m.now()
    elif status == 'OPEN':
        review.resolution_reason = None; review.resolved_by = None; review.resolved_at = None
    finding_row.resolution_status = status
    audit(db, ctx, action, 'match_findings', finding_row.id, old,
        {'status': review.status, 'assigned_to': review.assigned_to, 'version': review.version}, reason)
    db.commit()
    return review


def latest_run(db, org, invoice_id):
    return db.scalar(select(m.MatchRun).where(m.MatchRun.organization_id == org,
        m.MatchRun.invoice_id == invoice_id).order_by(m.MatchRun.created_at.desc(), m.MatchRun.id.desc()).limit(1))


def approval(db, ctx, invoice, create=True):
    row = db.scalar(select(m.InvoiceApproval).where(m.InvoiceApproval.organization_id == ctx.org,
        m.InvoiceApproval.invoice_id == invoice.id))
    if not row and create:
        row = m.InvoiceApproval(organization_id=ctx.org, created_by=ctx.user.id, updated_by=ctx.user.id,
            invoice_id=invoice.id, status='DRAFT')
        db.add(row); db.flush()
    return row


def invoice(db, org, identifier):
    row = db.scalar(select(m.SupplierInvoice).where(m.SupplierInvoice.organization_id == org, m.SupplierInvoice.id == identifier))
    if not row: raise HTTPException(404, 'Invoice not found')
    return row


def is_stale(invoice_row, run):
    if not run: return True
    source = (run.source_record_versions or {}).get('invoice_updated_at')
    return source != invoice_row.updated_at.isoformat()


def unresolved_blocking(db, org, run_id):
    findings = db.scalars(select(m.MatchFinding).where(m.MatchFinding.organization_id == org,
        m.MatchFinding.match_run_id == run_id, m.MatchFinding.severity == 'BLOCKING')).all()
    result = []
    for item in findings:
        review = db.scalar(select(m.ExceptionReview).where(m.ExceptionReview.organization_id == org,
            m.ExceptionReview.match_finding_id == item.id))
        if not review or review.status not in {'RESOLVED', 'ACCEPTED_VARIANCE'}: result.append(item)
    return result


def decision(db, ctx, invoice_row, approval_row, target, reason):
    if invoice_row.record_status != 'VERIFIED':
        raise HTTPException(409, 'Only a verified invoice can enter or complete approval')
    run = latest_run(db, ctx.org, invoice_row.id)
    if is_stale(invoice_row, run): raise HTTPException(409, 'The latest matching result is missing or stale. Run matching again.')
    blockers = unresolved_blocking(db, ctx.org, run.id)
    if target in ('PENDING_APPROVAL', 'APPROVED') and blockers:
        raise HTTPException(409, f'{len(blockers)} unresolved blocking finding(s) prevent approval')
    old = {'status': approval_row.status, 'version': approval_row.version}
    approval_row.status = target; approval_row.match_run_id = run.id; approval_row.invoice_version = invoice_row.updated_at.isoformat()
    approval_row.version += 1; approval_row.updated_by = ctx.user.id; approval_row.updated_at = m.now()
    if target == 'PENDING_REVIEW':
        approval_row.submitted_by = ctx.user.id; approval_row.submitted_at = m.now()
    if target in ('APPROVED', 'REJECTED', 'CHANGES_REQUESTED', 'CANCELLED'):
        approval_row.decided_by = ctx.user.id; approval_row.decided_at = m.now(); approval_row.decision_reason = reason
    accepted = db.execute(select(m.MatchFinding, m.ExceptionReview).join(m.ExceptionReview,
        m.ExceptionReview.match_finding_id == m.MatchFinding.id).where(m.MatchFinding.organization_id == ctx.org,
        m.MatchFinding.match_run_id == run.id, m.ExceptionReview.organization_id == ctx.org,
        m.ExceptionReview.status == 'ACCEPTED_VARIANCE')).all()
    overrides = [{'finding_id': finding.id, 'code': finding.code, 'reason': review.resolution_reason,
        'authorized_by': review.resolved_by, 'authorized_at': review.resolved_at.isoformat() if review.resolved_at else None}
        for finding, review in accepted]
    db.add(m.ApprovalDecision(organization_id=ctx.org, created_by=ctx.user.id, updated_by=ctx.user.id,
        invoice_id=invoice_row.id, match_run_id=run.id, reviewer_id=ctx.user.id, decision=target,
        reason=reason, invoice_version=invoice_row.updated_at.isoformat(), match_snapshot=run.result_summary or {},
        overridden_findings=overrides))
    audit(db, ctx, f'invoice_{target.lower()}', 'supplier_invoices', invoice_row.id, old,
        {'status': approval_row.status, 'version': approval_row.version}, reason)
    db.commit()
    return approval_row
