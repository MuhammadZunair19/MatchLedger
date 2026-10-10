"""Repeatable Milestone 4 demo scenarios for an existing organization."""
import argparse
from decimal import Decimal
from sqlalchemy import select
from . import models as m
from .db import SessionLocal
from .matching_schemas import MatchRunInput
from .security import Context
from .services.matching.matching_service import execute
from .services import review_service


SCENARIOS = [
    # code, supplier, description, ordered, received, invoiced, PO price, invoice price, due date
    ('A-MATCHED', 'Demo Gulf Industrial Supply', 'Safety gloves', '40', '40', '40', '25', '25', '2026-11-15'),
    ('B-PRICE', 'Demo Najd Components', 'Control relay', '50', '50', '50', '80', '88', '2026-11-20'),
    ('C-PARTIAL', 'Demo Eastern Logistics', 'Packing cartons', '200', '120', '180', '4', '4', '2026-11-25'),
    ('E-REJECTED', 'Demo Red Sea Trading', 'Circuit breaker', '20', '20', '20', '110', '110', '2026-11-28'),
    ('F-OVERRIDE', 'Demo Authorized Variance Co', 'Copper connector', '100', '100', '100', '10', '10.50', '2026-11-30'),
    ('G-NO-DUE', 'Demo Central Office Supply', 'Archive box', '30', '30', '30', '12', '12', None),
    ('H-ARABIC', 'شركة الإمدادات العربية التجريبية', 'لفات كابلات كهربائية', '75', '75', '75', '60', '60', '2026-12-05'),
]


def create_scenario(db, ctx, spec):
    code, supplier_name, description, ordered, received, invoiced, po_price, invoice_price, due_date = spec
    number = f'DEMO-INV-{code}'
    existing = db.scalar(select(m.SupplierInvoice).where(m.SupplierInvoice.organization_id == ctx.org, m.SupplierInvoice.number == number))
    if existing:
        run = review_service.latest_run(db, ctx.org, existing.id)
        return existing, run
    common = {'organization_id':ctx.org,'created_by':ctx.user.id,'updated_by':ctx.user.id}
    supplier = db.scalar(select(m.Supplier).where(m.Supplier.organization_id == ctx.org, m.Supplier.name == supplier_name))
    if not supplier:
        supplier=m.Supplier(name=supplier_name,**common);db.add(supplier);db.flush()
    po=m.PurchaseOrder(supplier_id=supplier.id,number=f'DEMO-PO-{code}',date='2026-10-01',currency='SAR',notes=f'Milestone 4 scenario {code}',**common);db.add(po);db.flush()
    po_line=m.PurchaseOrderLine(parent_id=po.id,description=description,sku=f'DEMO-{code}',unit_of_measure='unit',quantity=Decimal(ordered),unit_price=Decimal(po_price),**common);db.add(po_line);db.flush()
    receipt=m.GoodsReceipt(supplier_id=supplier.id,purchase_order_id=po.id,number=f'DEMO-GR-{code}',date='2026-10-05',notes=f'Milestone 4 scenario {code}',**common);db.add(receipt);db.flush()
    db.add(m.GoodsReceiptLine(parent_id=receipt.id,purchase_order_line_id=po_line.id,description=description,sku=po_line.sku,unit_of_measure='unit',quantity=Decimal(received),**common))
    total=(Decimal(invoiced)*Decimal(invoice_price)).quantize(Decimal('0.01'))
    invoice=m.SupplierInvoice(supplier_id=supplier.id,purchase_order_id=po.id,number=number,date='2026-10-10',due_date=due_date,currency='SAR',subtotal=total,discount=Decimal('0'),vat_amount=Decimal('0'),grand_total=total,notes=f'Milestone 4 scenario {code}',**common);db.add(invoice);db.flush()
    db.add(m.SupplierInvoiceLine(parent_id=invoice.id,purchase_order_line_id=po_line.id,description=description,sku=po_line.sku,unit_of_measure='unit',quantity=Decimal(invoiced),unit_price=Decimal(invoice_price),**common));db.commit()
    run_id=execute(db,ctx,MatchRunInput(invoice_id=invoice.id,purchase_order_id=po.id,matching_mode='THREE_WAY',receipt_ids=[receipt.id]))
    return invoice,db.get(m.MatchRun,run_id)


def seed(organization_id):
    with SessionLocal() as db:
        organization=db.get(m.Organization,organization_id)
        if not organization: raise SystemExit('Organization not found. Register in the application first.')
        membership=db.scalar(select(m.Membership).where(m.Membership.organization_id==organization_id,m.Membership.role=='owner'))
        if not membership: raise SystemExit('Organization owner not found.')
        ctx=Context(db.get(m.User,membership.user_id),membership,None)
        created={}
        for spec in SCENARIOS:
            invoice,run=create_scenario(db,ctx,spec);created[spec[0]]=(invoice,run)
        # Scenario D uses normalized duplicate references while retaining distinct ledger numbers.
        duplicate_spec=('D-DUPLICATE','Demo Duplicate Invoice Supplier','Network switch','10','10','10','500','500','2026-11-22')
        invoice,run=create_scenario(db,ctx,duplicate_spec)
        twin_number='DEMO/INV/D/DUPLICATE'
        twin=db.scalar(select(m.SupplierInvoice).where(m.SupplierInvoice.organization_id==ctx.org,m.SupplierInvoice.number==twin_number))
        if not twin:
            line=db.scalar(select(m.SupplierInvoiceLine).where(m.SupplierInvoiceLine.parent_id==invoice.id)); po=db.get(m.PurchaseOrder,invoice.purchase_order_id)
            common={'organization_id':ctx.org,'created_by':ctx.user.id,'updated_by':ctx.user.id}
            twin=m.SupplierInvoice(supplier_id=invoice.supplier_id,purchase_order_id=po.id,number=twin_number,date='2026-10-11',due_date='2026-11-22',currency='SAR',subtotal=Decimal('5000'),discount=Decimal('0'),vat_amount=Decimal('0'),grand_total=Decimal('5000'),notes='Milestone 4 duplicate-number scenario',**common);db.add(twin);db.flush()
            db.add(m.SupplierInvoiceLine(parent_id=twin.id,purchase_order_line_id=line.purchase_order_line_id,description=line.description,sku=line.sku,unit_of_measure=line.unit_of_measure,quantity=Decimal('10'),unit_price=Decimal('500'),**common));db.commit()
            execute(db,ctx,MatchRunInput(invoice_id=twin.id,purchase_order_id=po.id,matching_mode='THREE_WAY',receipt_ids=[]))
        # Persist a real rejected decision for scenario E.
        rejected,_=created['E-REJECTED']; approval=review_service.approval(db,ctx,rejected)
        if approval.status=='DRAFT': approval=review_service.decision(db,ctx,rejected,approval,'PENDING_REVIEW','Submitted for finance demonstration')
        if approval.status=='PENDING_REVIEW': review_service.decision(db,ctx,rejected,approval,'REJECTED','Demo rejection: supplier documentation requires correction')
        # Persist a clearly labeled authorized variance and approval for scenario F.
        override,override_run=created['F-OVERRIDE']
        for finding in db.scalars(select(m.MatchFinding).where(m.MatchFinding.organization_id==ctx.org,m.MatchFinding.match_run_id==override_run.id)):
            if finding.severity=='BLOCKING' and finding.resolution_status=='OPEN':
                review_service.update_exception(db,ctx,finding.id,1,'ACCEPTED_VARIANCE','variance_accepted','Demo authorized variance within signed contract amendment',resolution_type='AUTHORIZED_VARIANCE')
        approval=review_service.approval(db,ctx,override)
        if approval.status=='DRAFT': approval=review_service.decision(db,ctx,override,approval,'PENDING_REVIEW','Demo procurement review complete')
        if approval.status=='PENDING_REVIEW': approval=review_service.decision(db,ctx,override,approval,'PENDING_APPROVAL','Demo supervisor review complete')
        if approval.status=='PENDING_APPROVAL': review_service.decision(db,ctx,override,approval,'APPROVED','Demo approval after authorized variance')
        print('Milestone 4 demo scenarios A-H are ready. Existing scenario references were preserved.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--organization-id',required=True);seed(parser.parse_args().organization_id)
