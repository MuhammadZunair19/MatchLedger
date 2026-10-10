"""milestone 4 exception review approvals audit and reports"""
from alembic import op
import sqlalchemy as sa

revision = 'd19f4a8c2b71'
down_revision = 'c84e31f2a6d0'
branch_labels = None
depends_on = None


def tenant_columns():
    return [sa.Column('organization_id', sa.String(36), nullable=False),
        sa.Column('created_by', sa.String(36), nullable=True), sa.Column('updated_by', sa.String(36), nullable=True),
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']), sa.ForeignKeyConstraint(['updated_by'], ['users.id'])]


def upgrade():
    checks = sa.inspect(op.get_bind()).get_check_constraints('memberships')
    role_item = next((item for item in checks if 'role' in (item.get('sqltext') or '')), None)
    role_check = (role_item or {}).get('name') or ('ck_memberships_' if role_item else None)
    naming = {'ck': 'ck_%(table_name)s_%(column_0_name)s'}
    with op.batch_alter_table('memberships', naming_convention=naming) as batch:
        if role_check:
            batch.drop_constraint(role_check, type_='check')
        batch.alter_column('role', existing_type=sa.String(16), type_=sa.String(32), existing_nullable=False)
        batch.create_check_constraint('membership_role', "role IN ('owner','member','organization_admin','procurement_reviewer','finance_approver','viewer')")
    with op.batch_alter_table('match_findings') as batch:
        batch.create_unique_constraint('uq_match_findings_org_id', ['organization_id', 'id'])
    with op.batch_alter_table('audit_events') as batch:
        batch.add_column(sa.Column('old_state', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('new_state', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('reason', sa.String(2000), nullable=True))
        batch.add_column(sa.Column('request_id', sa.String(64), nullable=True))
        batch.create_index('ix_audit_events_org_action_created', ['organization_id', 'action', 'created_at'])
    op.create_table('exception_reviews',
        sa.Column('match_finding_id', sa.String(36), nullable=False), sa.Column('status', sa.String(32), server_default='OPEN', nullable=False),
        sa.Column('assigned_to', sa.String(36)), sa.Column('resolution_type', sa.String(40)), sa.Column('resolution_reason', sa.String(2000)),
        sa.Column('resolved_by', sa.String(36)), sa.Column('resolved_at', sa.DateTime(timezone=True)), sa.Column('version', sa.Integer(), server_default='1', nullable=False),
        *tenant_columns(), sa.ForeignKeyConstraint(['assigned_to'], ['users.id']), sa.ForeignKeyConstraint(['resolved_by'], ['users.id']),
        sa.ForeignKeyConstraint(['organization_id', 'match_finding_id'], ['match_findings.organization_id', 'match_findings.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('organization_id', 'id'), sa.UniqueConstraint('organization_id', 'match_finding_id'))
    op.create_index('ix_exception_reviews_organization_id', 'exception_reviews', ['organization_id'])
    op.create_index('ix_exception_reviews_org_status', 'exception_reviews', ['organization_id', 'status'])
    op.create_table('invoice_approvals',
        sa.Column('invoice_id', sa.String(36), nullable=False), sa.Column('match_run_id', sa.String(36)),
        sa.Column('status', sa.String(32), server_default='DRAFT', nullable=False), sa.Column('submitted_by', sa.String(36)),
        sa.Column('submitted_at', sa.DateTime(timezone=True)), sa.Column('decided_by', sa.String(36)), sa.Column('decided_at', sa.DateTime(timezone=True)),
        sa.Column('decision_reason', sa.String(2000)), sa.Column('invoice_version', sa.String(64)), sa.Column('version', sa.Integer(), server_default='1', nullable=False),
        *tenant_columns(), sa.ForeignKeyConstraint(['submitted_by'], ['users.id']), sa.ForeignKeyConstraint(['decided_by'], ['users.id']),
        sa.ForeignKeyConstraint(['organization_id', 'invoice_id'], ['supplier_invoices.organization_id', 'supplier_invoices.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id', 'match_run_id'], ['match_runs.organization_id', 'match_runs.id']),
        sa.UniqueConstraint('organization_id', 'id'), sa.UniqueConstraint('organization_id', 'invoice_id'))
    op.create_index('ix_invoice_approvals_organization_id', 'invoice_approvals', ['organization_id'])
    op.create_index('ix_invoice_approvals_org_status', 'invoice_approvals', ['organization_id', 'status'])
    op.create_table('approval_decisions',
        sa.Column('invoice_id', sa.String(36), nullable=False), sa.Column('match_run_id', sa.String(36)), sa.Column('reviewer_id', sa.String(36), nullable=False),
        sa.Column('decision', sa.String(32), nullable=False), sa.Column('reason', sa.String(2000)), sa.Column('invoice_version', sa.String(64), nullable=False),
        sa.Column('match_snapshot', sa.JSON(), server_default='{}', nullable=False), sa.Column('overridden_findings', sa.JSON(), server_default='[]', nullable=False),
        *tenant_columns(), sa.ForeignKeyConstraint(['reviewer_id'], ['users.id']),
        sa.ForeignKeyConstraint(['organization_id', 'invoice_id'], ['supplier_invoices.organization_id', 'supplier_invoices.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id', 'match_run_id'], ['match_runs.organization_id', 'match_runs.id']), sa.UniqueConstraint('organization_id', 'id'))
    op.create_index('ix_approval_decisions_organization_id', 'approval_decisions', ['organization_id'])
    op.create_table('review_comments',
        sa.Column('entity_type', sa.String(32), nullable=False), sa.Column('entity_id', sa.String(36), nullable=False),
        sa.Column('author_id', sa.String(36), nullable=False), sa.Column('body', sa.String(4000), nullable=False),
        *tenant_columns(), sa.ForeignKeyConstraint(['author_id'], ['users.id']))
    op.create_index('ix_review_comments_organization_id', 'review_comments', ['organization_id'])
    op.create_index('ix_review_comments_entity', 'review_comments', ['organization_id', 'entity_type', 'entity_id'])
    op.create_table('review_policies',
        sa.Column('segregation_of_duties', sa.Boolean(), server_default=sa.false(), nullable=False), *tenant_columns(),
        sa.UniqueConstraint('organization_id'), sa.UniqueConstraint('organization_id', 'id'))
    op.create_index('ix_review_policies_organization_id', 'review_policies', ['organization_id'])
    op.create_table('report_exports',
        sa.Column('report_type', sa.String(40), nullable=False), sa.Column('related_entity_id', sa.String(36)),
        sa.Column('status', sa.String(20), server_default='PROCESSING', nullable=False), sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('content_type', sa.String(100), nullable=False), sa.Column('storage_key', sa.String(500)), sa.Column('snapshot', sa.JSON(), server_default='{}', nullable=False),
        sa.Column('error', sa.String(1000)), sa.Column('generated_at', sa.DateTime(timezone=True)), *tenant_columns(), sa.UniqueConstraint('organization_id', 'id'))
    op.create_index('ix_report_exports_organization_id', 'report_exports', ['organization_id'])
    op.create_index('ix_report_exports_related', 'report_exports', ['organization_id', 'report_type', 'related_entity_id'])


def downgrade():
    for table in ('report_exports', 'review_policies', 'review_comments', 'approval_decisions', 'invoice_approvals', 'exception_reviews'):
        op.drop_table(table)
    with op.batch_alter_table('audit_events') as batch:
        batch.drop_index('ix_audit_events_org_action_created')
        for column in ('request_id', 'reason', 'new_state', 'old_state'):
            batch.drop_column(column)
    with op.batch_alter_table('match_findings') as batch:
        batch.drop_constraint('uq_match_findings_org_id', type_='unique')
    with op.batch_alter_table('memberships') as batch:
        batch.drop_constraint('membership_role', type_='check')
        batch.alter_column('role', existing_type=sa.String(32), type_=sa.String(16), existing_nullable=False)
        batch.create_check_constraint('membership_role_legacy', "role IN ('owner','member')")
