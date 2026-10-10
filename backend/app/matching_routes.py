from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from . import models as m
from .db import get_db
from .matching_schemas import MatchRunInput, MatchingSettingsInput
from .security import Context, current, require_permission
from .request_context import request_id
from .services.matching import matching_service as service

router = APIRouter(prefix='/api/matching', tags=['matching'])


@router.get('/settings')
def get_settings(ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'view')
    row = service.get_settings(db, ctx.org, ctx.user.id); db.commit()
    return service.settings_dict(row)


@router.put('/settings')
def update_settings(data: MatchingSettingsInput, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'admin')
    row = service.get_settings(db, ctx.org, ctx.user.id)
    for key, value in data.model_dump().items():
        setattr(row, key, {k: str(v) for k, v in value.items()} if key == 'unit_conversions' else value)
    row.updated_by = ctx.user.id; row.updated_at = m.now()
    db.add(m.AuditEvent(organization_id=ctx.org, created_by=ctx.user.id, updated_by=ctx.user.id,
        action='update_matching_settings', entity_type='matching_settings', entity_id=row.id, detail=service.settings_dict(row), request_id=request_id()))
    db.commit()
    return service.settings_dict(row)


@router.get('/candidates')
def get_candidates(invoice_id: str, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'view')
    return service.candidates(db, ctx.org, invoice_id)


@router.get('/invoices/{invoice_id}/candidates')
def get_invoice_candidates(invoice_id: str, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'view')
    return service.candidates(db, ctx.org, invoice_id)


@router.post('/runs', status_code=201)
def create_run(data: MatchRunInput, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'review')
    identifier = service.execute(db, ctx, data)
    row = db.scalar(select(m.MatchRun).where(m.MatchRun.organization_id == ctx.org, m.MatchRun.id == identifier))
    return service.serialize_run(db, row, ctx.org)


@router.get('/runs')
def list_runs(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), status: str | None = None,
              invoice_id: str | None = None, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'view')
    query = select(m.MatchRun).where(m.MatchRun.organization_id == ctx.org)
    if status: query = query.where(m.MatchRun.status == status)
    if invoice_id: query = query.where(m.MatchRun.invoice_id == invoice_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(m.MatchRun.created_at.desc()).offset((page-1)*page_size).limit(page_size)).all()
    return {'items': service.serialize_runs(db, rows, ctx.org), 'total': total, 'page': page, 'page_size': page_size}


@router.get('/runs/{identifier}')
def get_run(identifier: str, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'view')
    row = db.scalar(select(m.MatchRun).where(m.MatchRun.organization_id == ctx.org, m.MatchRun.id == identifier))
    if not row: raise HTTPException(404, 'Match run not found')
    return service.serialize_run(db, row, ctx.org)


@router.get('/runs/{identifier}/findings')
def get_findings(identifier: str, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'view')
    run = db.scalar(select(m.MatchRun).where(m.MatchRun.organization_id == ctx.org, m.MatchRun.id == identifier))
    if not run: raise HTTPException(404, 'Match run not found')
    rows = db.scalars(select(m.MatchFinding).where(m.MatchFinding.organization_id == ctx.org,
        m.MatchFinding.match_run_id == identifier).order_by(m.MatchFinding.created_at, m.MatchFinding.id)).all()
    return {'items': [service.public(row) for row in rows], 'total': len(rows)}


@router.post('/runs/{identifier}/rerun', status_code=201)
def rerun(identifier: str, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    require_permission(ctx, 'review')
    row = db.scalar(select(m.MatchRun).where(m.MatchRun.organization_id == ctx.org, m.MatchRun.id == identifier))
    if not row: raise HTTPException(404, 'Match run not found')
    data = MatchRunInput(invoice_id=row.invoice_id, purchase_order_id=row.purchase_order_id,
        matching_mode=row.matching_mode, receipt_ids=row.receipt_ids, review_notes=row.review_notes)
    new_id = service.execute(db, ctx, data)
    db.add(m.AuditEvent(organization_id=ctx.org, created_by=ctx.user.id, updated_by=ctx.user.id,
        action='match_result_superseded', entity_type='match_runs', entity_id=row.id,
        old_state={'status': row.status}, new_state={'superseded_by': new_id}, request_id=request_id()))
    db.commit()
    new_row = db.scalar(select(m.MatchRun).where(m.MatchRun.organization_id == ctx.org, m.MatchRun.id == new_id))
    return service.serialize_run(db, new_row, ctx.org)
