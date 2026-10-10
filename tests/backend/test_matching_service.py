from types import SimpleNamespace

from app import models as m
from app.matching_schemas import MatchRunInput
from app.services.matching.matching_service import execute, serialize_run
from fastapi import HTTPException
from sqlalchemy import select


def add_tenant(factory, suffix):
    with factory() as db:
        user = m.User(email=f'{suffix}@example.com', name=suffix, password_hash='test')
        organization = m.Organization(name=f'Org {suffix}')
        db.add_all([user, organization]); db.flush()
        supplier = m.Supplier(organization_id=organization.id, created_by=user.id, updated_by=user.id, name=f'Supplier {suffix}')
        db.add(supplier); db.flush()
        order = m.PurchaseOrder(organization_id=organization.id, created_by=user.id, updated_by=user.id,
            supplier_id=supplier.id, number=f'PO-{suffix}', date='2026-10-01', currency='SAR')
        db.add(order); db.flush()
        order_line = m.PurchaseOrderLine(organization_id=organization.id, created_by=user.id, updated_by=user.id,
            parent_id=order.id, description='Cable rolls', sku='CAB-50', unit_of_measure='roll', quantity='100', unit_price='50.00')
        db.add(order_line); db.flush()
        receipt = m.GoodsReceipt(organization_id=organization.id, created_by=user.id, updated_by=user.id,
            supplier_id=supplier.id, purchase_order_id=order.id, number=f'GR-{suffix}', date='2026-10-02')
        invoice = m.SupplierInvoice(organization_id=organization.id, created_by=user.id, updated_by=user.id,
            supplier_id=supplier.id, purchase_order_id=order.id, number=f'INV-{suffix}', date='2026-10-01', due_date='2026-10-31',
            currency='SAR', subtotal='5500.00', discount='0', vat_amount='0', grand_total='5500.00')
        db.add_all([receipt, invoice]); db.flush()
        db.add_all([m.GoodsReceiptLine(organization_id=organization.id, created_by=user.id, updated_by=user.id,
            parent_id=receipt.id, purchase_order_line_id=order_line.id, description='Cable rolls', sku='CAB-50', unit_of_measure='roll', quantity='90'),
            m.SupplierInvoiceLine(organization_id=organization.id, created_by=user.id, updated_by=user.id,
            parent_id=invoice.id, purchase_order_line_id=order_line.id, description='Cable rolls', sku='CAB-50', unit_of_measure='roll', quantity='100', unit_price='55.00')])
        db.commit()
        return SimpleNamespace(org=organization.id, user=SimpleNamespace(id=user.id)), order.id, receipt.id, invoice.id


def test_persisted_match_is_tenant_scoped_and_rerunnable(database):
    context, order_id, receipt_id, invoice_id = add_tenant(database, 'one')
    other, _, _, _ = add_tenant(database, 'two')
    with database() as db:
        identifier = execute(db, context, MatchRunInput(invoice_id=invoice_id, purchase_order_id=order_id,
            matching_mode='THREE_WAY', receipt_ids=[receipt_id]))
        row = db.scalar(select(m.MatchRun).where(m.MatchRun.id == identifier, m.MatchRun.organization_id == context.org))
        output = serialize_run(db, row, context.org)
        assert output['status'] == 'EXCEPTION'
        assert output['result_summary']['difference_against_supported'] == '1000.00'
        assert {item['code'] for item in output['findings']} >= {'PRICE_MISMATCH', 'QUANTITY_MISMATCH'}
        assert db.scalar(select(m.MatchRun).where(m.MatchRun.id == identifier, m.MatchRun.organization_id == other.org)) is None
        assert db.scalar(select(m.AuditEvent).where(m.AuditEvent.organization_id == context.org,
            m.AuditEvent.entity_id == identifier, m.AuditEvent.action == 'match_run')) is not None
        second = execute(db, context, MatchRunInput(invoice_id=invoice_id, purchase_order_id=order_id,
            matching_mode='THREE_WAY', receipt_ids=[receipt_id]))
        assert second != identifier


def test_cross_tenant_match_inputs_are_rejected(database):
    context, order_id, _, _ = add_tenant(database, 'alpha')
    _, _, _, foreign_invoice_id = add_tenant(database, 'beta')
    with database() as db:
        try:
            execute(db, context, MatchRunInput(invoice_id=foreign_invoice_id, purchase_order_id=order_id))
        except HTTPException as exc:
            assert getattr(exc, 'status_code', None) == 404
        else:
            raise AssertionError('Cross-tenant invoice must not be visible')
