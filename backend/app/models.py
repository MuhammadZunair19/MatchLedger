import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, Numeric, ForeignKey, ForeignKeyConstraint, UniqueConstraint, CheckConstraint, DateTime, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc)


class Identity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Tenant(Identity):
    organization_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'), index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))


class Organization(Identity, Base):
    __tablename__ = 'organizations'
    name: Mapped[str] = mapped_column(String(160))
    currency: Mapped[str] = mapped_column(String(3), default='SAR')


class User(Identity, Base):
    __tablename__ = 'users'
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(512))


class Membership(Identity, Base):
    __tablename__ = 'memberships'
    organization_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    role: Mapped[str] = mapped_column(String(32), default='member')
    __table_args__ = (UniqueConstraint('organization_id', 'user_id'),
        CheckConstraint("role IN ('owner','member','organization_admin','procurement_reviewer','finance_approver','viewer')"))


class Session(Identity, Base):
    __tablename__ = 'sessions'
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Supplier(Tenant, Base):
    __tablename__ = 'suppliers'
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(String(1000))
    external_identifier: Mapped[str | None] = mapped_column(String(100))
    tax_id: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = (UniqueConstraint('organization_id', 'id'), UniqueConstraint('organization_id', 'name'))


class Header(Tenant):
    supplier_id: Mapped[str] = mapped_column(String(36))
    number: Mapped[str] = mapped_column(String(80))
    date: Mapped[str] = mapped_column(String(10))
    notes: Mapped[str | None] = mapped_column(String(2000))
    record_status: Mapped[str] = mapped_column(String(20), default='VERIFIED', server_default='VERIFIED')


def header_constraints(table, po=False):
    constraints = [UniqueConstraint('organization_id', 'id'), UniqueConstraint('organization_id', 'number'),
        ForeignKeyConstraint(['organization_id', 'supplier_id'], ['suppliers.organization_id', 'suppliers.id'])]
    if po:
        constraints.append(ForeignKeyConstraint(['organization_id', 'purchase_order_id'], ['purchase_orders.organization_id', 'purchase_orders.id']))
    return tuple(constraints)


class PurchaseOrder(Header, Base):
    __tablename__ = 'purchase_orders'
    currency: Mapped[str] = mapped_column(String(3), default='SAR')
    __table_args__ = header_constraints(__tablename__)


class GoodsReceipt(Header, Base):
    __tablename__ = 'goods_receipts'
    purchase_order_id: Mapped[str] = mapped_column(String(36))
    __table_args__ = header_constraints(__tablename__, True)


class SupplierInvoice(Header, Base):
    __tablename__ = 'supplier_invoices'
    purchase_order_id: Mapped[str] = mapped_column(String(36))
    currency: Mapped[str] = mapped_column(String(3), default='SAR')
    due_date: Mapped[str | None] = mapped_column(String(10))
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    discount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    vat_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    grand_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    __table_args__ = (UniqueConstraint('organization_id', 'id'),
        UniqueConstraint('organization_id', 'supplier_id', 'number', name='uq_supplier_invoice_supplier_number'),
        ForeignKeyConstraint(['organization_id', 'supplier_id'], ['suppliers.organization_id', 'suppliers.id']),
        ForeignKeyConstraint(['organization_id', 'purchase_order_id'], ['purchase_orders.organization_id', 'purchase_orders.id']))


class Line(Tenant):
    parent_id: Mapped[str] = mapped_column(String(36), index=True)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    sku: Mapped[str | None] = mapped_column(String(100))
    unit_of_measure: Mapped[str | None] = mapped_column(String(40))


def line_constraints(parent, with_po=False):
    constraints = [UniqueConstraint('organization_id', 'id'), CheckConstraint('quantity > 0'),
        ForeignKeyConstraint(['organization_id', 'parent_id'], [f'{parent}.organization_id', f'{parent}.id'], ondelete='CASCADE')]
    if with_po:
        constraints.append(ForeignKeyConstraint(['organization_id', 'purchase_order_line_id'], ['purchase_order_lines.organization_id', 'purchase_order_lines.id']))
    return tuple(constraints)


class PurchaseOrderLine(Line, Base):
    __tablename__ = 'purchase_order_lines'
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    __table_args__ = line_constraints('purchase_orders') + (CheckConstraint('unit_price >= 0'),)


class GoodsReceiptLine(Line, Base):
    __tablename__ = 'goods_receipt_lines'
    purchase_order_line_id: Mapped[str] = mapped_column(String(36))
    __table_args__ = line_constraints('goods_receipts', True)


class SupplierInvoiceLine(Line, Base):
    __tablename__ = 'supplier_invoice_lines'
    purchase_order_line_id: Mapped[str] = mapped_column(String(36))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    __table_args__ = line_constraints('supplier_invoices', True) + (CheckConstraint('unit_price >= 0'),)


class Document(Tenant, Base):
    __tablename__ = 'documents'
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    document_type: Mapped[str] = mapped_column(String(24), default='purchase_order', server_default='purchase_order')
    status: Mapped[str] = mapped_column(String(24), default='UPLOADED', server_default='UPLOADED')
    page_count: Mapped[int] = mapped_column(default=1, server_default='1')
    detected_languages: Mapped[list] = mapped_column(JSON, default=list, server_default='[]')
    last_error: Mapped[str | None] = mapped_column(String(1000))
    review_data: Mapped[dict | None] = mapped_column(JSON)
    review_revision: Mapped[int] = mapped_column(default=0, server_default='0')
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    business_entity_type: Mapped[str | None] = mapped_column(String(40))
    business_entity_id: Mapped[str | None] = mapped_column(String(36))
    __table_args__ = (UniqueConstraint('organization_id', 'id'), CheckConstraint('size_bytes > 0'))


class DocumentExtraction(Tenant, Base):
    __tablename__ = 'document_extractions'
    document_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int]
    engine: Mapped[str] = mapped_column(String(120), default='native-pdf+paddleocr/deterministic-v1')
    status: Mapped[str] = mapped_column(String(24), default='QUEUED')
    job_id: Mapped[str] = mapped_column(String(100), unique=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_pages: Mapped[list | None] = mapped_column(JSON)
    extracted_data: Mapped[dict | None] = mapped_column(JSON)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(String(1000))
    __table_args__ = (UniqueConstraint('organization_id', 'id'), UniqueConstraint('organization_id', 'document_id', 'version'),
        ForeignKeyConstraint(['organization_id', 'document_id'], ['documents.organization_id', 'documents.id'], ondelete='CASCADE'))


class FieldCorrection(Tenant, Base):
    __tablename__ = 'field_corrections'
    document_id: Mapped[str] = mapped_column(String(36), index=True)
    extraction_id: Mapped[str] = mapped_column(String(36))
    revision: Mapped[int]
    field_path: Mapped[str] = mapped_column(String(200))
    previous_value: Mapped[dict] = mapped_column(JSON)
    reviewed_value: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (ForeignKeyConstraint(['organization_id', 'document_id'], ['documents.organization_id', 'documents.id'], ondelete='CASCADE'),
        ForeignKeyConstraint(['organization_id', 'extraction_id'], ['document_extractions.organization_id', 'document_extractions.id'], ondelete='CASCADE'))


class MatchRun(Tenant, Base):
    __tablename__ = 'match_runs'
    invoice_id: Mapped[str] = mapped_column(String(36))
    purchase_order_id: Mapped[str | None] = mapped_column(String(36))
    matching_mode: Mapped[str] = mapped_column(String(16), default='TWO_WAY', server_default='TWO_WAY')
    receipt_ids: Mapped[list] = mapped_column(JSON, default=list, server_default='[]')
    status: Mapped[str] = mapped_column(String(32), default='REVIEW_REQUIRED', server_default='REVIEW_REQUIRED')
    engine_version: Mapped[str | None] = mapped_column(String(40), default='deterministic-v1')
    settings_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, server_default='{}')
    document_versions: Mapped[dict] = mapped_column(JSON, default=dict, server_default='{}')
    source_record_versions: Mapped[dict] = mapped_column(JSON, default=dict, server_default='{}')
    result_summary: Mapped[dict] = mapped_column(JSON, default=dict, server_default='{}')
    review_notes: Mapped[str | None] = mapped_column(String(2000))
    input_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint('organization_id', 'id'),
        ForeignKeyConstraint(['organization_id', 'invoice_id'], ['supplier_invoices.organization_id', 'supplier_invoices.id']),
        ForeignKeyConstraint(['organization_id', 'purchase_order_id'], ['purchase_orders.organization_id', 'purchase_orders.id']))


class MatchFinding(Tenant, Base):
    __tablename__ = 'match_findings'
    match_run_id: Mapped[str] = mapped_column(String(36))
    code: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(16), default='WARNING', server_default='WARNING')
    explanation: Mapped[str] = mapped_column(String(2000), default='', server_default='')
    purchase_order_line_id: Mapped[str | None] = mapped_column(String(36))
    invoice_line_id: Mapped[str | None] = mapped_column(String(36))
    receipt_line_id: Mapped[str | None] = mapped_column(String(36))
    expected_value: Mapped[str | None] = mapped_column(String(100))
    actual_value: Mapped[str | None] = mapped_column(String(100))
    difference: Mapped[str | None] = mapped_column(String(100))
    unit: Mapped[str | None] = mapped_column(String(40))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, server_default='{}')
    applicable_tolerance: Mapped[dict] = mapped_column(JSON, default=dict, server_default='{}')
    review_required: Mapped[bool] = mapped_column(default=False, server_default='false')
    resolution_status: Mapped[str] = mapped_column(String(24), default='OPEN', server_default='OPEN')
    detail: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint('organization_id', 'id'),
        ForeignKeyConstraint(['organization_id', 'match_run_id'], ['match_runs.organization_id', 'match_runs.id'], ondelete='CASCADE'))


class MatchingSettings(Tenant, Base):
    __tablename__ = 'matching_settings'
    price_tolerance_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=Decimal('0'), server_default='0')
    price_tolerance_absolute: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal('0'), server_default='0')
    quantity_tolerance: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=Decimal('0'), server_default='0')
    total_tolerance_absolute: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal('0.01'), server_default='0.01')
    unit_conversions: Mapped[dict] = mapped_column(JSON, default=dict, server_default='{}')
    __table_args__ = (UniqueConstraint('organization_id'), UniqueConstraint('organization_id', 'id'))


class ItemMapping(Tenant, Base):
    __tablename__ = 'item_mappings'
    supplier_id: Mapped[str] = mapped_column(String(36))
    source_sku: Mapped[str | None] = mapped_column(String(100))
    source_description: Mapped[str] = mapped_column(String(500))
    purchase_order_line_id: Mapped[str] = mapped_column(String(36))
    __table_args__ = (UniqueConstraint('organization_id', 'supplier_id', 'source_sku', 'source_description'),
        ForeignKeyConstraint(['organization_id', 'supplier_id'], ['suppliers.organization_id', 'suppliers.id']),
        ForeignKeyConstraint(['organization_id', 'purchase_order_line_id'], ['purchase_order_lines.organization_id', 'purchase_order_lines.id']))


class AuditEvent(Tenant, Base):
    __tablename__ = 'audit_events'
    action: Mapped[str] = mapped_column(String(40))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(36))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    old_state: Mapped[dict | None] = mapped_column(JSON)
    new_state: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(String(2000))
    request_id: Mapped[str | None] = mapped_column(String(64))


class ExceptionReview(Tenant, Base):
    __tablename__ = 'exception_reviews'
    match_finding_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(32), default='OPEN', server_default='OPEN')
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    resolution_type: Mapped[str | None] = mapped_column(String(40))
    resolution_reason: Mapped[str | None] = mapped_column(String(2000))
    resolved_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(default=1, server_default='1')
    __table_args__ = (UniqueConstraint('organization_id', 'id'), UniqueConstraint('organization_id', 'match_finding_id'),
        ForeignKeyConstraint(['organization_id', 'match_finding_id'], ['match_findings.organization_id', 'match_findings.id'], ondelete='CASCADE'))


class InvoiceApproval(Tenant, Base):
    __tablename__ = 'invoice_approvals'
    invoice_id: Mapped[str] = mapped_column(String(36))
    match_run_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(32), default='DRAFT', server_default='DRAFT')
    submitted_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(String(2000))
    invoice_version: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(default=1, server_default='1')
    __table_args__ = (UniqueConstraint('organization_id', 'id'), UniqueConstraint('organization_id', 'invoice_id'),
        ForeignKeyConstraint(['organization_id', 'invoice_id'], ['supplier_invoices.organization_id', 'supplier_invoices.id'], ondelete='CASCADE'),
        ForeignKeyConstraint(['organization_id', 'match_run_id'], ['match_runs.organization_id', 'match_runs.id']))


class ApprovalDecision(Tenant, Base):
    __tablename__ = 'approval_decisions'
    invoice_id: Mapped[str] = mapped_column(String(36))
    match_run_id: Mapped[str | None] = mapped_column(String(36))
    reviewer_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    decision: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(String(2000))
    invoice_version: Mapped[str] = mapped_column(String(64))
    match_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, server_default='{}')
    overridden_findings: Mapped[list] = mapped_column(JSON, default=list, server_default='[]')
    __table_args__ = (UniqueConstraint('organization_id', 'id'),
        ForeignKeyConstraint(['organization_id', 'invoice_id'], ['supplier_invoices.organization_id', 'supplier_invoices.id'], ondelete='CASCADE'),
        ForeignKeyConstraint(['organization_id', 'match_run_id'], ['match_runs.organization_id', 'match_runs.id']))


class ReviewComment(Tenant, Base):
    __tablename__ = 'review_comments'
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(36))
    author_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    body: Mapped[str] = mapped_column(String(4000))
    __table_args__ = (Index('ix_review_comments_entity', 'organization_id', 'entity_type', 'entity_id'),)


class ReviewPolicy(Tenant, Base):
    __tablename__ = 'review_policies'
    segregation_of_duties: Mapped[bool] = mapped_column(default=False, server_default='false')
    __table_args__ = (UniqueConstraint('organization_id'), UniqueConstraint('organization_id', 'id'))


class ReportExport(Tenant, Base):
    __tablename__ = 'report_exports'
    report_type: Mapped[str] = mapped_column(String(40))
    related_entity_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(20), default='PROCESSING', server_default='PROCESSING')
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    storage_key: Mapped[str | None] = mapped_column(String(500))
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict, server_default='{}')
    error: Mapped[str | None] = mapped_column(String(1000))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint('organization_id', 'id'),
        Index('ix_report_exports_related', 'organization_id', 'report_type', 'related_entity_id'))
