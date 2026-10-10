"""Seed an existing organization using application validation; no embedded accounts."""
import argparse
import json
from pathlib import Path
from sqlalchemy import select
from .db import SessionLocal
from . import models as m, schemas as s
from .main import validate_links, audit
from .security import Context


def seed(organization_id):
    data = json.loads((Path(__file__).resolve().parents[2] / 'sample_data' / 'procurement.json').read_text())
    with SessionLocal.begin() as db:
        organization = db.get(m.Organization, organization_id)
        if not organization:
            raise SystemExit('Organization not found. Register in the application first.')
        member = db.scalar(select(m.Membership).where(m.Membership.organization_id == organization_id, m.Membership.role == 'owner'))
        user = db.get(m.User, member.user_id)
        ctx = Context(user, member, None)
        common = dict(organization_id=organization_id, created_by=user.id, updated_by=user.id)
        if db.scalar(select(m.PurchaseOrder).where(m.PurchaseOrder.organization_id == organization_id, m.PurchaseOrder.number == data['purchase_order']['number'])):
            print('Sample order already exists; no changes made.'); return
        supplier = db.scalar(select(m.Supplier).where(m.Supplier.organization_id == organization_id, m.Supplier.name == data['supplier']['name']))
        if not supplier:
            supplier = m.Supplier(**s.SupplierInput(**data['supplier']).model_dump(), **common)
            db.add(supplier); db.flush(); audit(db, ctx, 'seed', supplier)
        po_data = s.POInput(**data['purchase_order'], supplier_id=supplier.id)
        po = m.PurchaseOrder(**{**po_data.model_dump(exclude={'lines'}), 'date': po_data.date.isoformat()}, **common)
        db.add(po); db.flush()
        line = m.PurchaseOrderLine(**po_data.lines[0].model_dump(), parent_id=po.id, **common)
        db.add(line); db.flush(); audit(db, ctx, 'seed', po)
        for key, schema, model, line_model in [('receipt', s.ReceiptInput, m.GoodsReceipt, m.GoodsReceiptLine), ('invoice', s.InvoiceInput, m.SupplierInvoice, m.SupplierInvoiceLine)]:
            fields = dict(data[key]); quantity = fields.pop('quantity'); price = fields.pop('unit_price', None)
            line_data = dict(description=line.description, sku=line.sku, unit_of_measure=line.unit_of_measure,
                             quantity=quantity, purchase_order_line_id=line.id)
            if price is not None: line_data['unit_price'] = price
            validated = schema(**fields, supplier_id=supplier.id, purchase_order_id=po.id, lines=[line_data])
            validate_links(db, validated, ctx)
            values = {**validated.model_dump(exclude={'lines'}), 'date': validated.date.isoformat()}
            if key == 'invoice' and validated.due_date:
                values['due_date'] = validated.due_date.isoformat()
            row = model(**values, **common)
            db.add(row); db.flush()
            db.add(line_model(**validated.lines[0].model_dump(), parent_id=row.id, **common)); audit(db, ctx, 'seed', row)
        print('Seeded PO 100 × SAR 50, receipt 90, invoice 100 × SAR 55 (excluding VAT).')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--organization-id', required=True)
    seed(parser.parse_args().organization_id)
