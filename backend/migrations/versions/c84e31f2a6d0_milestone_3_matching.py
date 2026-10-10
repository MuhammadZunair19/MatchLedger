"""milestone 3 deterministic matching and verified invoice fields"""
from alembic import op
import sqlalchemy as sa

revision = 'c84e31f2a6d0'
down_revision = 'a35db39e3e1a'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('suppliers') as batch:
        batch.add_column(sa.Column('external_identifier', sa.String(100), nullable=True))
        batch.add_column(sa.Column('tax_id', sa.String(100), nullable=True))
        batch.create_index('ix_suppliers_org_tax_id', ['organization_id', 'tax_id'], unique=False)
    for table in ('purchase_orders', 'goods_receipts', 'supplier_invoices'):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('record_status', sa.String(20), server_default='VERIFIED', nullable=False))
    uniques = sa.inspect(op.get_bind()).get_unique_constraints('supplier_invoices')
    old_invoice_unique = next((item['name'] for item in uniques
        if set(item['column_names']) == {'organization_id', 'number'}), None)
    naming = {'uq': 'uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s'}
    with op.batch_alter_table('supplier_invoices', naming_convention=naming) as batch:
        batch.drop_constraint(old_invoice_unique or 'uq_supplier_invoices_organization_id_number', type_='unique')
        batch.create_unique_constraint('uq_supplier_invoice_supplier_number', ['organization_id', 'supplier_id', 'number'])
        batch.add_column(sa.Column('due_date', sa.String(10), nullable=True))
        batch.add_column(sa.Column('subtotal', sa.Numeric(18, 2), nullable=True))
        batch.add_column(sa.Column('discount', sa.Numeric(18, 2), nullable=True))
        batch.add_column(sa.Column('vat_amount', sa.Numeric(18, 2), nullable=True))
        batch.add_column(sa.Column('grand_total', sa.Numeric(18, 2), nullable=True))
        batch.create_index('ix_supplier_invoices_org_supplier_number', ['organization_id', 'supplier_id', 'number'], unique=False)
        batch.create_index('ix_supplier_invoices_org_po', ['organization_id', 'purchase_order_id'], unique=False)
    for table in ('purchase_order_lines', 'goods_receipt_lines', 'supplier_invoice_lines'):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('sku', sa.String(100), nullable=True))
            batch.add_column(sa.Column('unit_of_measure', sa.String(40), nullable=True))
    with op.batch_alter_table('match_runs') as batch:
        batch.add_column(sa.Column('purchase_order_id', sa.String(36), nullable=True))
        batch.add_column(sa.Column('matching_mode', sa.String(16), server_default='TWO_WAY', nullable=False))
        batch.add_column(sa.Column('receipt_ids', sa.JSON(), server_default='[]', nullable=False))
        batch.add_column(sa.Column('settings_snapshot', sa.JSON(), server_default='{}', nullable=False))
        batch.add_column(sa.Column('document_versions', sa.JSON(), server_default='{}', nullable=False))
        batch.add_column(sa.Column('source_record_versions', sa.JSON(), server_default='{}', nullable=False))
        batch.add_column(sa.Column('result_summary', sa.JSON(), server_default='{}', nullable=False))
        batch.add_column(sa.Column('review_notes', sa.String(2000), nullable=True))
        batch.add_column(sa.Column('input_fingerprint', sa.String(64), nullable=True))
        batch.add_column(sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key('fk_match_runs_purchase_order', 'purchase_orders',
                                 ['organization_id', 'purchase_order_id'], ['organization_id', 'id'])
        batch.create_index('ix_match_runs_input_fingerprint', ['input_fingerprint'], unique=False)
        batch.create_index('ix_match_runs_org_invoice', ['organization_id', 'invoice_id'], unique=False)
    with op.batch_alter_table('match_findings') as batch:
        batch.add_column(sa.Column('severity', sa.String(16), server_default='WARNING', nullable=False))
        batch.add_column(sa.Column('explanation', sa.String(2000), server_default='', nullable=False))
        batch.add_column(sa.Column('purchase_order_line_id', sa.String(36), nullable=True))
        batch.add_column(sa.Column('invoice_line_id', sa.String(36), nullable=True))
        batch.add_column(sa.Column('receipt_line_id', sa.String(36), nullable=True))
        batch.add_column(sa.Column('expected_value', sa.String(100), nullable=True))
        batch.add_column(sa.Column('actual_value', sa.String(100), nullable=True))
        batch.add_column(sa.Column('difference', sa.String(100), nullable=True))
        batch.add_column(sa.Column('unit', sa.String(40), nullable=True))
        batch.add_column(sa.Column('evidence', sa.JSON(), server_default='{}', nullable=False))
        batch.add_column(sa.Column('applicable_tolerance', sa.JSON(), server_default='{}', nullable=False))
        batch.add_column(sa.Column('review_required', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch.add_column(sa.Column('resolution_status', sa.String(24), server_default='OPEN', nullable=False))
    op.create_table('matching_settings',
        sa.Column('price_tolerance_percent', sa.Numeric(9, 4), server_default='0', nullable=False),
        sa.Column('price_tolerance_absolute', sa.Numeric(18, 2), server_default='0', nullable=False),
        sa.Column('quantity_tolerance', sa.Numeric(18, 3), server_default='0', nullable=False),
        sa.Column('total_tolerance_absolute', sa.Numeric(18, 2), server_default='0.01', nullable=False),
        sa.Column('unit_conversions', sa.JSON(), server_default='{}', nullable=False),
        sa.Column('organization_id', sa.String(36), nullable=False), sa.Column('created_by', sa.String(36), nullable=True),
        sa.Column('updated_by', sa.String(36), nullable=True), sa.Column('id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']), sa.ForeignKeyConstraint(['updated_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'), sa.UniqueConstraint('organization_id'), sa.UniqueConstraint('organization_id', 'id'))
    op.create_index('ix_matching_settings_organization_id', 'matching_settings', ['organization_id'])
    op.create_table('item_mappings',
        sa.Column('supplier_id', sa.String(36), nullable=False), sa.Column('source_sku', sa.String(100), nullable=True),
        sa.Column('source_description', sa.String(500), nullable=False),
        sa.Column('purchase_order_line_id', sa.String(36), nullable=False),
        sa.Column('organization_id', sa.String(36), nullable=False), sa.Column('created_by', sa.String(36), nullable=True),
        sa.Column('updated_by', sa.String(36), nullable=True), sa.Column('id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']), sa.ForeignKeyConstraint(['updated_by'], ['users.id']),
        sa.ForeignKeyConstraint(['organization_id', 'supplier_id'], ['suppliers.organization_id', 'suppliers.id']),
        sa.ForeignKeyConstraint(['organization_id', 'purchase_order_line_id'], ['purchase_order_lines.organization_id', 'purchase_order_lines.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'supplier_id', 'source_sku', 'source_description'))
    op.create_index('ix_item_mappings_organization_id', 'item_mappings', ['organization_id'])


def downgrade():
    op.drop_table('item_mappings')
    op.drop_table('matching_settings')
    with op.batch_alter_table('match_findings') as batch:
        for column in ('resolution_status', 'review_required', 'applicable_tolerance', 'evidence', 'unit', 'difference',
                       'actual_value', 'expected_value', 'receipt_line_id', 'invoice_line_id',
                       'purchase_order_line_id', 'explanation', 'severity'):
            batch.drop_column(column)
    with op.batch_alter_table('match_runs') as batch:
        batch.drop_index('ix_match_runs_org_invoice')
        batch.drop_index('ix_match_runs_input_fingerprint')
        batch.drop_constraint('fk_match_runs_purchase_order', type_='foreignkey')
        for column in ('completed_at', 'input_fingerprint', 'review_notes', 'result_summary', 'source_record_versions',
                       'document_versions', 'settings_snapshot', 'receipt_ids', 'matching_mode', 'purchase_order_id'):
            batch.drop_column(column)
    for table in ('supplier_invoice_lines', 'goods_receipt_lines', 'purchase_order_lines'):
        with op.batch_alter_table(table) as batch:
            batch.drop_column('unit_of_measure'); batch.drop_column('sku')
    with op.batch_alter_table('supplier_invoices') as batch:
        batch.drop_index('ix_supplier_invoices_org_po')
        batch.drop_index('ix_supplier_invoices_org_supplier_number')
        batch.drop_constraint('uq_supplier_invoice_supplier_number', type_='unique')
        batch.create_unique_constraint('uq_supplier_invoices_organization_id_number', ['organization_id', 'number'])
        for column in ('grand_total', 'vat_amount', 'discount', 'subtotal', 'due_date'):
            batch.drop_column(column)
    for table in ('supplier_invoices', 'goods_receipts', 'purchase_orders'):
        with op.batch_alter_table(table) as batch:
            batch.drop_column('record_status')
    with op.batch_alter_table('suppliers') as batch:
        batch.drop_index('ix_suppliers_org_tax_id')
        batch.drop_column('tax_id'); batch.drop_column('external_identifier')
