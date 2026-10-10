import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select
from ... import models as m
from ...request_context import request_id
from .matching_orchestrator import ENGINE_VERSION, run_match
from .line_item_matcher import match_lines
from .reference_matcher import normalize_reference


def public(row):
    output = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        output[column.name] = str(value) if isinstance(value, Decimal) else value.isoformat() if isinstance(value, (date, datetime)) else value
    return output


def _one(db, model, organization_id, identifier):
    row = db.scalar(select(model).where(model.organization_id == organization_id, model.id == identifier))
    if not row:
        raise HTTPException(404, 'Record not found')
    return row


def _record(db, row, line_model, organization_id):
    output = public(row)
    output['lines'] = [public(line) for line in db.scalars(select(line_model).where(
        line_model.organization_id == organization_id, line_model.parent_id == row.id).order_by(line_model.created_at, line_model.id))]
    return output


def get_settings(db, organization_id, user_id=None, create=True):
    row = db.scalar(select(m.MatchingSettings).where(m.MatchingSettings.organization_id == organization_id))
    if not row and create:
        row = m.MatchingSettings(organization_id=organization_id, created_by=user_id, updated_by=user_id)
        db.add(row); db.flush()
    return row


def settings_dict(row):
    return {'price_tolerance_percent': str(row.price_tolerance_percent),
            'price_tolerance_absolute': str(row.price_tolerance_absolute),
            'quantity_tolerance': str(row.quantity_tolerance),
            'total_tolerance_absolute': str(row.total_tolerance_absolute),
            'unit_conversions': {key: str(value) for key, value in (row.unit_conversions or {}).items()}}


def candidates(db, organization_id, invoice_id):
    invoice = _one(db, m.SupplierInvoice, organization_id, invoice_id)
    orders = db.scalars(select(m.PurchaseOrder).where(m.PurchaseOrder.organization_id == organization_id,
        m.PurchaseOrder.supplier_id == invoice.supplier_id, m.PurchaseOrder.record_status == 'VERIFIED').order_by(m.PurchaseOrder.created_at.desc())).all()
    receipts = db.scalars(select(m.GoodsReceipt).where(m.GoodsReceipt.organization_id == organization_id,
        m.GoodsReceipt.purchase_order_id.in_([row.id for row in orders] or ['']))).all()
    invoice_data = _record(db, invoice, m.SupplierInvoiceLine, organization_id)
    order_data = [_record(db, row, m.PurchaseOrderLine, organization_id) for row in orders]
    suggestions = {row['id']: match_lines(invoice_data['lines'], row['lines']) for row in order_data}
    for values in suggestions.values():
        for item in values:
            item.pop('invoice_line', None); item.pop('po_line', None)
    return {'invoice': invoice_data,
            'purchase_orders': order_data, 'line_suggestions': suggestions,
            'receipts': [_record(db, row, m.GoodsReceiptLine, organization_id) for row in receipts]}


def _document_versions(db, organization_id, records):
    result = {}
    for kind, identifier in records.items():
        if isinstance(identifier, list):
            ids = identifier
        else:
            ids = [identifier]
        rows = db.scalars(select(m.Document).where(m.Document.organization_id == organization_id,
            m.Document.business_entity_type == kind, m.Document.business_entity_id.in_(ids))).all()
        result[kind] = [{'document_id': row.id, 'business_entity_id': row.business_entity_id,
            'review_revision': row.review_revision, 'status': row.status} for row in rows]
    return result


def execute(db, ctx, data):
    invoice = _one(db, m.SupplierInvoice, ctx.org, data.invoice_id)
    order = _one(db, m.PurchaseOrder, ctx.org, data.purchase_order_id)
    if invoice.record_status != 'VERIFIED' or order.record_status != 'VERIFIED':
        raise HTTPException(422, 'Only verified business records can be matched')
    receipts = [_one(db, m.GoodsReceipt, ctx.org, identifier) for identifier in data.receipt_ids]
    if any(row.purchase_order_id != order.id or row.record_status != 'VERIFIED' for row in receipts):
        raise HTTPException(422, 'Every selected receipt must be verified and belong to the selected purchase order')
    snapshot = {'invoice': _record(db, invoice, m.SupplierInvoiceLine, ctx.org),
                'purchase_order': _record(db, order, m.PurchaseOrderLine, ctx.org),
                'receipts': [_record(db, row, m.GoodsReceiptLine, ctx.org) for row in receipts]}
    # A verified ledger link is authoritative evidence of the selected PO. A reviewed
    # document reference, when present, is retained so a conflict remains detectable.
    snapshot['invoice']['po_reference'] = order.number if invoice.purchase_order_id == order.id else None
    document_versions = _document_versions(db, ctx.org, {'supplier_invoices': invoice.id,
        'purchase_orders': order.id, 'goods_receipts': [row.id for row in receipts]})
    invoice_docs = document_versions.get('supplier_invoices', [])
    if invoice_docs:
        document = _one(db, m.Document, ctx.org, invoice_docs[0]['document_id'])
        fields = (document.review_data or {}).get('fields', {})
        value = fields.get('purchase_order_reference', {})
        document_reference = value.get('value') if isinstance(value, dict) else value
        if document_reference:
            snapshot['invoice']['po_reference'] = document_reference
    same_supplier = db.scalars(select(m.SupplierInvoice).where(m.SupplierInvoice.organization_id == ctx.org,
        m.SupplierInvoice.supplier_id == invoice.supplier_id, m.SupplierInvoice.id != invoice.id)).all()
    normalized = normalize_reference(invoice.number)
    snapshot['duplicates'] = [{'id': row.id, 'number': row.number} for row in same_supplier if normalize_reference(row.number) == normalized]
    previous = {}
    other_ids = [row.id for row in same_supplier if row.purchase_order_id == order.id and normalize_reference(row.number) != normalized]
    if other_ids:
        for line in db.scalars(select(m.SupplierInvoiceLine).where(m.SupplierInvoiceLine.organization_id == ctx.org,
                m.SupplierInvoiceLine.parent_id.in_(other_ids))):
            previous[line.purchase_order_line_id] = previous.get(line.purchase_order_line_id, Decimal('0')) + line.quantity
    snapshot['previous_invoiced'] = {key: str(value) for key, value in previous.items()}
    settings = get_settings(db, ctx.org, ctx.user.id)
    configured = settings_dict(settings)
    remembered = {}
    mappings = db.scalars(select(m.ItemMapping).where(m.ItemMapping.organization_id == ctx.org,
        m.ItemMapping.supplier_id == invoice.supplier_id)).all()
    po_line_ids = {line['id'] for line in snapshot['purchase_order']['lines']}
    for line in snapshot['invoice']['lines']:
        match = next((item for item in mappings if item.purchase_order_line_id in po_line_ids
            and item.source_sku == line.get('sku') and item.source_description == line.get('description')), None)
        if match: remembered[line['id']] = match.purchase_order_line_id
    approved = {**remembered, **data.line_associations}
    result = run_match(snapshot, configured, data.matching_mode, approved)
    source_versions = {'invoice_updated_at': invoice.updated_at.isoformat(), 'purchase_order_updated_at': order.updated_at.isoformat(),
        'receipt_updated_at': {row.id: row.updated_at.isoformat() for row in receipts}}
    canonical = json.dumps({'snapshot': snapshot, 'settings': configured, 'mode': data.matching_mode}, sort_keys=True, separators=(',', ':'))
    run = m.MatchRun(organization_id=ctx.org, created_by=ctx.user.id, updated_by=ctx.user.id,
        invoice_id=invoice.id, purchase_order_id=order.id, matching_mode=data.matching_mode,
        receipt_ids=data.receipt_ids, status=result['status'], engine_version=ENGINE_VERSION,
        settings_snapshot=configured, document_versions=document_versions, source_record_versions=source_versions,
        result_summary=result['summary'], review_notes=data.review_notes,
        input_fingerprint=hashlib.sha256(canonical.encode()).hexdigest(), completed_at=m.now())
    db.add(run); db.flush()
    for item in result['findings']:
        db.add(m.MatchFinding(organization_id=ctx.org, created_by=ctx.user.id, updated_by=ctx.user.id,
            match_run_id=run.id, **item))
    if data.save_mappings:
        inv_lines = {line['id']: line for line in snapshot['invoice']['lines']}
        po_ids = {line['id'] for line in snapshot['purchase_order']['lines']}
        for invoice_line_id, po_line_id in data.line_associations.items():
            if invoice_line_id not in inv_lines or po_line_id not in po_ids:
                raise HTTPException(422, 'A confirmed item association is outside the selected records')
            line = inv_lines[invoice_line_id]
            existing = db.scalar(select(m.ItemMapping).where(m.ItemMapping.organization_id == ctx.org,
                m.ItemMapping.supplier_id == invoice.supplier_id, m.ItemMapping.source_sku == line.get('sku'),
                m.ItemMapping.source_description == line['description']))
            if existing:
                existing.purchase_order_line_id = po_line_id; existing.updated_by = ctx.user.id
            else:
                db.add(m.ItemMapping(organization_id=ctx.org, created_by=ctx.user.id, updated_by=ctx.user.id,
                    supplier_id=invoice.supplier_id, source_sku=line.get('sku'), source_description=line['description'], purchase_order_line_id=po_line_id))
    db.add(m.AuditEvent(organization_id=ctx.org, created_by=ctx.user.id, updated_by=ctx.user.id,
        action='match_run', entity_type='match_runs', entity_id=run.id,
        detail={'status': run.status, 'invoice_id': invoice.id, 'purchase_order_id': order.id, 'mode': data.matching_mode}, request_id=request_id()))
    db.commit()
    return run.id


def serialize_run(db, row, organization_id):
    output = public(row)
    findings = db.scalars(select(m.MatchFinding).where(m.MatchFinding.organization_id == organization_id,
        m.MatchFinding.match_run_id == row.id).order_by(m.MatchFinding.created_at, m.MatchFinding.id)).all()
    output['findings'] = [public(item) for item in findings]
    return output


def serialize_runs(db, rows, organization_id):
    if not rows:
        return []
    identifiers = [row.id for row in rows]
    findings = db.scalars(select(m.MatchFinding).where(m.MatchFinding.organization_id == organization_id,
        m.MatchFinding.match_run_id.in_(identifiers)).order_by(m.MatchFinding.created_at, m.MatchFinding.id)).all()
    grouped = {identifier: [] for identifier in identifiers}
    for item in findings:
        grouped[item.match_run_id].append(public(item))
    output = []
    for row in rows:
        value = public(row); value['findings'] = grouped[row.id]; output.append(value)
    return output
