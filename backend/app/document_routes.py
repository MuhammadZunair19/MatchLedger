import hashlib
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from redis.exceptions import RedisError
from starlette.concurrency import run_in_threadpool
from .db import get_db
from .security import current, Context
from .config import settings
from . import models as m
from .document_schemas import DocumentType, SaveReview, ConfirmReview
from .main import scoped, get_record, public, audit
from .services.documents.storage_service import LocalStorage
from .services.documents.upload_service import safe_filename, bounded_parse, validate_extension
from .services.documents import jobs
from .services.documents.verification_service import save_draft, confirm
from .services.documents.validation_service import validate_review

router = APIRouter(prefix='/api/documents', tags=['Documents'])


def document_json(row):
    data = public(row)
    data.pop('storage_key', None)
    return data


@router.post('/upload', status_code=201)
async def upload(document_type: Annotated[DocumentType, Form()], file: Annotated[UploadFile, File()],
                 ctx: Context = Depends(current), db: Session = Depends(get_db)):
    size = 0; chunks = []
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > settings.max_upload_size_mb * 1024 * 1024: raise HTTPException(413, 'Document exceeds the upload size limit')
        chunks.append(chunk)
    await file.close()
    if not size: raise HTTPException(422, 'Empty files are not supported')
    content = b''.join(chunks)
    storage = LocalStorage(); key = storage.put(ctx.org, content)
    try:
        metadata = await run_in_threadpool(bounded_parse, storage.path(ctx.org, key))
        filename = safe_filename(file.filename)
        validate_extension(filename, metadata['content_type'])
        row = m.Document(organization_id=ctx.org, created_by=ctx.user.id, updated_by=ctx.user.id,
            filename=filename, storage_key=key, document_type=document_type, size_bytes=size,
            sha256=hashlib.sha256(content).hexdigest(), **metadata)
        db.add(row); db.flush(); audit(db, ctx, 'upload_document', row); db.commit()
        return document_json(row)
    except ValueError as exc:
        storage.delete(ctx.org, key)
        raise HTTPException(422, str(exc)) from None
    except Exception:
        storage.delete(ctx.org, key)
        raise


@router.get('')
def listing(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), q: str = Query('', max_length=100),
            status: str | None = None, document_type: DocumentType | None = None,
            ctx: Context = Depends(current), db: Session = Depends(get_db)):
    query = scoped(m.Document, ctx)
    if q: query = query.where(m.Document.filename.icontains(q, autoescape=True))
    if status: query = query.where(m.Document.status == status)
    if document_type: query = query.where(m.Document.document_type == document_type)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(m.Document.created_at.desc()).offset((page-1)*page_size).limit(page_size)).all()
    items = []
    for row in rows:
        jobs.recover_stale(db, row)
        data = document_json(row)
        data['supplier_name'] = (row.review_data or {}).get('fields', {}).get('supplier_name')
        data.pop('review_data', None); items.append(data)
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}


@router.get('/{id}')
def detail(id: str, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    row = get_record(db, m.Document, id, ctx)
    jobs.recover_stale(db, row)
    return document_json(row)


@router.get('/{id}/file')
def file(id: str, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    row = get_record(db, m.Document, id, ctx)
    path = LocalStorage().path(ctx.org, row.storage_key)
    if not path.is_file(): raise HTTPException(404, 'Document file is unavailable')
    return FileResponse(path, media_type=row.content_type, filename=row.filename,
        headers={'Content-Security-Policy': "sandbox; default-src 'none'", 'Cache-Control': 'no-store'}, content_disposition_type='attachment')


@router.get('/{id}/pages/{page}')
def preview(id: str, page: int, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    row = get_record(db, m.Document, id, ctx)
    if not 1 <= page <= row.page_count: raise HTTPException(404, 'Page not found')
    try: content = bounded_parse(LocalStorage().path(ctx.org, row.storage_key), 'render', page)
    except ValueError as exc: raise HTTPException(422, str(exc)) from None
    return Response(content, media_type='image/png', headers={'Cache-Control': 'no-store'})


@router.post('/{id}/extract', status_code=202)
def extract(id: str, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    doc = get_record(db, m.Document, id, ctx, lock=True)
    jobs.recover_stale(db, doc)
    doc = get_record(db, m.Document, id, ctx, lock=True)
    if doc.status in ('QUEUED', 'PROCESSING', 'VERIFIED'): raise HTTPException(409, 'Document is already processing or verified')
    version = (db.scalar(select(func.max(m.DocumentExtraction.version)).where(m.DocumentExtraction.organization_id == ctx.org, m.DocumentExtraction.document_id == id)) or 0) + 1
    if version > settings.max_extraction_attempts: raise HTTPException(409, 'Extraction attempt limit reached; review available results or upload a clearer document')
    run = m.DocumentExtraction(organization_id=ctx.org, created_by=ctx.user.id, updated_by=ctx.user.id, document_id=id,
        version=version, job_id=f'doc-{id}-v{version}')
    db.add(run); doc.status = 'QUEUED'; doc.last_error = None; db.flush(); audit(db, ctx, 'queue_extraction', doc); db.commit()
    try: jobs.enqueue(run)
    except (RedisError, OSError):
        doc.status = run.status = 'FAILED'; run.error = doc.last_error = 'Processing queue unavailable. Start Redis and the worker, then retry.'
        run.completed_at = m.now(); db.commit()
        raise HTTPException(503, doc.last_error) from None
    return {'id': run.id, 'version': run.version, 'status': run.status, 'job_id': run.job_id}


@router.get('/{id}/extraction')
def extraction(id: str, version: int | None = Query(None, ge=1), ctx: Context = Depends(current), db: Session = Depends(get_db)):
    doc = get_record(db, m.Document, id, ctx); jobs.recover_stale(db, doc)
    query = scoped(m.DocumentExtraction, ctx).where(m.DocumentExtraction.document_id == id)
    if version: query = query.where(m.DocumentExtraction.version == version)
    runs = db.scalars(query.order_by(m.DocumentExtraction.version.desc())).all()
    return {'latest': public(runs[0]) if runs else None,
        'history': [{k: public(run)[k] for k in ('id', 'version', 'status', 'engine', 'created_at', 'completed_at', 'error')} for run in runs],
        'review_data': doc.review_data, 'review_revision': doc.review_revision,
        'validation_warnings': validate_review(doc.review_data, doc.document_type) if doc.review_data else []}


@router.get('/{id}/status')
def status(id: str, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    doc = get_record(db, m.Document, id, ctx); jobs.recover_stale(db, doc)
    return {'id': doc.id, 'status': doc.status, 'last_error': doc.last_error, 'updated_at': doc.updated_at}


@router.put('/{id}/review')
def review(id: str, data: SaveReview, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    doc = get_record(db, m.Document, id, ctx, lock=True)
    save_draft(db, doc, data, ctx); db.commit()
    return {'review_revision': doc.review_revision, 'review_data': doc.review_data,
        'validation_warnings': validate_review(doc.review_data, doc.document_type)}


@router.get('/{id}/corrections')
def corrections(id: str, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    get_record(db, m.Document, id, ctx)
    return [public(row) for row in db.scalars(scoped(m.FieldCorrection, ctx).where(m.FieldCorrection.document_id == id).order_by(m.FieldCorrection.created_at.desc()).limit(1000))]


@router.post('/{id}/verify')
def verify(id: str, data: ConfirmReview, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    doc = get_record(db, m.Document, id, ctx, lock=True)
    row = confirm(db, doc, data, ctx); db.commit()
    return {'document': document_json(doc), 'business_entity_type': row.__tablename__, 'business_entity_id': row.id}


@router.delete('/{id}', status_code=204)
def remove(id: str, ctx: Context = Depends(current), db: Session = Depends(get_db)):
    doc = get_record(db, m.Document, id, ctx, lock=True); jobs.recover_stale(db, doc)
    if doc.status in ('QUEUED', 'PROCESSING'): raise HTTPException(409, 'Wait for processing to finish before deleting')
    key = doc.storage_key
    audit(db, ctx, 'delete_document', doc); db.delete(doc); db.commit()
    LocalStorage().delete(ctx.org, key)
    return Response(status_code=204)
