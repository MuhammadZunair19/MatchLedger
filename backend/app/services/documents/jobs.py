"""Redis/RQ transport plus durable database job state and stale-job recovery."""
import logging
from datetime import timezone
from redis import Redis
from rq import Queue
from sqlalchemy import select, update
from ...config import settings
from ...db import SessionLocal
from ...models import Document, DocumentExtraction, AuditEvent, now
from .storage_service import LocalStorage
from .extraction_orchestrator import extract_document, review_from_extraction

logger = logging.getLogger('matchledger.documents')


def queue():
    return Queue('documents', connection=Redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=5))


def enqueue(extraction):
    queue().enqueue('app.services.documents.jobs.process_document', extraction.organization_id, extraction.document_id, extraction.id,
                    job_id=extraction.job_id, job_timeout=settings.extraction_timeout, result_ttl=86400, failure_ttl=604800,
                    description=f'document extraction {extraction.id}')


def recover_stale(db, document):
    if document.status not in ('QUEUED', 'PROCESSING'): return
    run = db.scalar(select(DocumentExtraction).where(DocumentExtraction.organization_id == document.organization_id,
        DocumentExtraction.document_id == document.id).order_by(DocumentExtraction.version.desc()).limit(1))
    if not run: return
    started = run.started_at or run.created_at
    age = (now() - (started if started.tzinfo else started.replace(tzinfo=timezone.utc))).total_seconds()
    limit = settings.extraction_timeout + 120
    if age > limit:
        run.status = document.status = 'FAILED'
        run.error = document.last_error = 'Worker did not complete within the allowed time. Check the worker and retry extraction.'
        run.completed_at = now()
        db.add(AuditEvent(organization_id=document.organization_id, action='extraction_timeout', entity_type='documents', entity_id=document.id))
        db.commit()


def process_document(organization_id, document_id, extraction_id):
    # The claim is conditional and durable; duplicate deliveries do not rerun work.
    with SessionLocal.begin() as db:
        document = db.scalar(select(Document).where(Document.organization_id == organization_id, Document.id == document_id).with_for_update())
        run = db.scalar(select(DocumentExtraction).where(DocumentExtraction.organization_id == organization_id,
            DocumentExtraction.document_id == document_id, DocumentExtraction.id == extraction_id))
        if not document or not run or run.status != 'QUEUED' or document.status != 'QUEUED': return
        claimed = db.execute(update(DocumentExtraction).where(DocumentExtraction.id == extraction_id,
            DocumentExtraction.organization_id == organization_id, DocumentExtraction.status == 'QUEUED').values(status='PROCESSING', started_at=now()))
        if claimed.rowcount != 1: return
        document.status = 'PROCESSING'
        key, mime, kind = document.storage_key, document.content_type, document.document_type
    logger.info('Processing document=%s extraction=%s', document_id, extraction_id)
    try:
        result = extract_document(LocalStorage().path(organization_id, key), mime, kind)
    except Exception as exc:
        # Never log exception strings: OCR/parsers may include sensitive document text or paths.
        logger.error('Extraction=%s failed (%s)', extraction_id, type(exc).__name__)
        with SessionLocal.begin() as db:
            doc = db.scalar(select(Document).where(Document.organization_id == organization_id, Document.id == document_id).with_for_update())
            run = db.scalar(select(DocumentExtraction).where(DocumentExtraction.organization_id == organization_id, DocumentExtraction.id == extraction_id))
            if doc and run and run.status == 'PROCESSING':
                run.status = doc.status = 'FAILED'; run.completed_at = now()
                run.error = doc.last_error = 'Extraction failed. Check OCR model installation, worker resources and document readability; then retry.'
                db.add(AuditEvent(organization_id=organization_id, action='extraction_failed', entity_type='documents', entity_id=document_id))
        return
    with SessionLocal.begin() as db:
        doc = db.scalar(select(Document).where(Document.organization_id == organization_id, Document.id == document_id).with_for_update())
        run = db.scalar(select(DocumentExtraction).where(DocumentExtraction.organization_id == organization_id, DocumentExtraction.id == extraction_id))
        if not doc or not run or run.status != 'PROCESSING' or doc.status != 'PROCESSING': return
        run.raw_pages = result['pages']; run.extracted_data = result['data']; run.warnings = result['warnings']
        run.status = doc.status = 'REVIEW_REQUIRED'; run.completed_at = now(); doc.last_error = None
        doc.detected_languages = result['languages']
        if doc.review_data is None or (doc.review_revision == 0 and doc.reviewed_at is None):
            doc.review_data = review_from_extraction(result['data'], run.id)
        else:
            run.warnings = [*run.warnings, 'Previous review values retained. New extraction evidence is available in history.']
        db.add(AuditEvent(organization_id=organization_id, action='extraction_completed', entity_type='documents', entity_id=document_id))


def recover_all():
    with SessionLocal() as db:
        for document in db.scalars(select(Document).where(Document.status.in_(['QUEUED', 'PROCESSING']))).all():
            recover_stale(db, document)


if __name__ == '__main__':
    recover_all()
