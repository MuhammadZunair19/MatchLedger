from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from ... import models as m, schemas as s
from .validation_service import validate_review


def flatten(data):
    result = {f'fields.{key}': value for key, value in data.get('fields', {}).items()}
    result.update({k: data.get(k) for k in ('supplier_id', 'purchase_order_id')})
    for line in data.get('lines', []):
        for key, value in line.items(): result[f'lines.{line["id"]}.{key}'] = value
    return result


def save_draft(db, doc, request, ctx):
    from ...main import get_record, audit
    if doc.status == 'VERIFIED': raise HTTPException(409, 'Verified documents are read-only')
    if request.revision != doc.review_revision: raise HTTPException(409, 'This review changed. Reload before saving.')
    data = request.data.model_dump()
    run = get_record(db, m.DocumentExtraction, data['extraction_id'], ctx)
    if run.document_id != doc.id or run.extracted_data is None: raise HTTPException(422, 'Review must reference a completed extraction for this document')
    if data['supplier_id']: get_record(db, m.Supplier, data['supplier_id'], ctx)
    if data['purchase_order_id']: get_record(db, m.PurchaseOrder, data['purchase_order_id'], ctx)
    before, after = flatten(doc.review_data or {}), flatten(data)
    revision = doc.review_revision + 1
    for key in before.keys() | after.keys():
        if before.get(key) != after.get(key):
            db.add(m.FieldCorrection(organization_id=ctx.org, created_by=ctx.user.id, updated_by=ctx.user.id,
                document_id=doc.id, extraction_id=run.id, revision=revision, field_path=key,
                previous_value={'value': before.get(key)}, reviewed_value={'value': after.get(key)}))
    doc.review_data = data; doc.review_revision = revision; doc.reviewed_by = ctx.user.id; doc.reviewed_at = m.now()
    doc.updated_by = ctx.user.id
    audit(db, ctx, 'save_review', doc)


def confirm(db, doc, request, ctx):
    from ...main import get_record, validate_links, audit
    if doc.status == 'VERIFIED': raise HTTPException(409, 'This document has already created a business record')
    if doc.status != 'REVIEW_REQUIRED' or not doc.review_data: raise HTTPException(409, 'Complete extraction and save a review first')
    if request.revision != doc.review_revision or not doc.reviewed_at: raise HTTPException(409, 'Save the current draft before confirmation')
    data = doc.review_data; fields = data['fields']
    warnings = validate_review(data, doc.document_type)
    if warnings and not request.acknowledge_warnings: raise HTTPException(422, 'Review and acknowledge validation warnings before confirming')
    supplier_id = data.get('supplier_id')
    if not supplier_id and request.create_supplier:
        try: supplier_input = s.SupplierInput(name=fields.get('supplier_name'))
        except ValidationError: raise HTTPException(422, 'A supplier name is required') from None
        existing = db.scalar(select(m.Supplier).where(m.Supplier.organization_id == ctx.org, m.Supplier.name == supplier_input.name))
        if existing: raise HTTPException(409, 'A supplier with this name exists. Select that supplier in the review.')
        supplier = m.Supplier(**supplier_input.model_dump(), organization_id=ctx.org, created_by=ctx.user.id, updated_by=ctx.user.id)
        db.add(supplier); db.flush(); supplier_id = supplier.id; audit(db, ctx, 'create', supplier)
    if not supplier_id: raise HTTPException(422, 'Select an existing supplier or explicitly choose to create one')
    get_record(db, m.Supplier, supplier_id, ctx)
    kind = doc.document_type
    lines = []
    for line in data['lines']:
        values = {k: line.get(k) for k in ('description', 'quantity')}
        if kind != 'goods_receipt': values['unit_price'] = line.get('unit_price')
        if kind != 'purchase_order': values['purchase_order_line_id'] = line.get('purchase_order_line_id')
        lines.append(values)
    values = {'supplier_id': supplier_id, 'number': fields.get('number'), 'date': fields.get('date'), 'notes': fields.get('notes'), 'lines': lines}
    if kind != 'goods_receipt': values['currency'] = fields.get('currency')
    if kind != 'purchase_order': values['purchase_order_id'] = data.get('purchase_order_id')
    specs = {'purchase_order': (s.POInput, m.PurchaseOrder, m.PurchaseOrderLine),
        'supplier_invoice': (s.InvoiceInput, m.SupplierInvoice, m.SupplierInvoiceLine), 'goods_receipt': (s.ReceiptInput, m.GoodsReceipt, m.GoodsReceiptLine)}
    schema, model, line_model = specs[kind]
    try: validated = schema(**values)
    except ValidationError as exc:
        messages = ['.'.join(map(str, e['loc'])) + ': ' + e['msg'] for e in exc.errors()]
        raise HTTPException(422, '; '.join(messages)) from None
    validate_links(db, validated, ctx)
    common = {'organization_id': ctx.org, 'created_by': ctx.user.id, 'updated_by': ctx.user.id}
    row = model(**{**validated.model_dump(exclude={'lines'}), 'date': validated.date.isoformat()}, **common)
    db.add(row); db.flush()
    for line in validated.lines: db.add(line_model(**line.model_dump(), parent_id=row.id, **common))
    db.flush(); audit(db, ctx, 'create_from_document', row)
    doc.status = 'VERIFIED'; doc.verified_at = m.now(); doc.reviewed_by = ctx.user.id; doc.updated_by = ctx.user.id
    doc.business_entity_type = row.__tablename__; doc.business_entity_id = row.id
    audit(db, ctx, 'verify_document', doc)
    return row
