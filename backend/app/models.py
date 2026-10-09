import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, Numeric, ForeignKey, ForeignKeyConstraint, UniqueConstraint, CheckConstraint, DateTime, JSON
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
    role: Mapped[str] = mapped_column(String(16), default='member')
    __table_args__ = (UniqueConstraint('organization_id', 'user_id'), CheckConstraint("role IN ('owner', 'member')"))


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
    __table_args__ = (UniqueConstraint('organization_id', 'id'), UniqueConstraint('organization_id', 'name'))


class Header(Tenant):
    supplier_id: Mapped[str] = mapped_column(String(36))
    number: Mapped[str] = mapped_column(String(80))
    date: Mapped[str] = mapped_column(String(10))
    notes: Mapped[str | None] = mapped_column(String(2000))


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
    __table_args__ = header_constraints(__tablename__, True)


class Line(Tenant):
    parent_id: Mapped[str] = mapped_column(String(36), index=True)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))


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
    status: Mapped[str] = mapped_column(String(24), default='pending')
    engine_version: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (UniqueConstraint('organization_id', 'id'), ForeignKeyConstraint(['organization_id', 'invoice_id'], ['supplier_invoices.organization_id', 'supplier_invoices.id']))


class MatchFinding(Tenant, Base):
    __tablename__ = 'match_findings'
    match_run_id: Mapped[str] = mapped_column(String(36))
    code: Mapped[str] = mapped_column(String(80))
    detail: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (ForeignKeyConstraint(['organization_id', 'match_run_id'], ['match_runs.organization_id', 'match_runs.id']),)


class AuditEvent(Tenant, Base):
    __tablename__ = 'audit_events'
    action: Mapped[str] = mapped_column(String(40))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(36))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
