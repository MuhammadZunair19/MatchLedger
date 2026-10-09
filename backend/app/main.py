import logging
import uuid
from decimal import Decimal
from fastapi import FastAPI, Depends, HTTPException, Request, Response, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, func, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession
from .db import get_db
from .config import settings
from . import models as m, schemas as s
from .security import current, Context, owner, passwords, DUMMY_HASH, issue_session, COOKIE

app = FastAPI(title='MatchLedger', version='0.1.0')
log = logging.getLogger('matchledger')


@app.middleware('http')
async def safety(request: Request, call_next):
    request_id = str(uuid.uuid4())
    if request.url.path == '/api/documents/upload':
        length = request.headers.get('content-length', '')
        if not length.isdigit() or int(length) > settings.max_upload_size_mb * 1024 * 1024 + 65536:
            return JSONResponse({'error': {'code': '413', 'message': 'Upload exceeds the size limit or has no Content-Length'}}, status_code=413)
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('origin') not in (None, settings.app_origin):
        return JSONResponse({'error': {'code': '403', 'message': 'Origin is not allowed'}}, status_code=403)
    try:
        response = await call_next(request)
    except Exception as exc:
        if request.url.path.startswith('/api/documents'):
            log.error('Document request %s failed (%s)', request_id, type(exc).__name__)
        else:
            log.exception('Unhandled request %s', request_id)
        response = JSONResponse({'error': {'code': '500', 'message': 'Unexpected server error', 'request_id': request_id}}, status_code=500)
    response.headers['X-Request-ID'] = request_id
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse({'error': {'code': str(exc.status_code), 'message': exc.detail}}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    details = [{'field': '.'.join(map(str, e['loc'][1:])), 'message': e['msg']} for e in exc.errors()]
    return JSONResponse({'error': {'code': 'validation', 'message': 'Please check the submitted fields', 'details': details}}, status_code=422)


@app.exception_handler(IntegrityError)
async def conflict(request, exc):
    return JSONResponse({'error': {'code': 'conflict', 'message': 'This record already exists or is referenced by another record.'}}, status_code=409)


def scoped(model, ctx):
    return select(model).where(model.organization_id == ctx.org)


def get_record(db, model, id, ctx, lock=False):
    query = scoped(model, ctx).where(model.id == id)
    if lock:
        query = query.with_for_update()
    row = db.scalar(query)
    if not row:
        raise HTTPException(404, 'Record not found')
    return row


def audit(db, ctx, action, row):
    db.add(m.AuditEvent(organization_id=ctx.org, created_by=ctx.user.id, updated_by=ctx.user.id,
                        action=action, entity_type=row.__tablename__, entity_id=row.id))


def public(row):
    result = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        result[column.name] = str(value) if isinstance(value, Decimal) else value
    return result


def auth_payload(db, session):
    user = db.get(m.User, session.user_id)
    memberships = db.execute(select(m.Membership, m.Organization).join(m.Organization).where(m.Membership.user_id == user.id)).all()
    return {'user': {'id': user.id, 'name': user.name, 'email': user.email}, 'csrf_token': session.csrf_token,
            'organization_id': session.organization_id,
            'organizations': [{'id': org.id, 'name': org.name, 'role': membership.role} for membership, org in memberships]}


@app.get('/api/health')
def health(db: DBSession = Depends(get_db)):
    db.execute(select(1))
    return {'status': 'ok'}


@app.post('/api/auth/register', status_code=201)
def register(data: s.Register, request: Request, response: Response, db: DBSession = Depends(get_db)):
    user = m.User(email=str(data.email).lower(), name=data.name, password_hash=passwords.hash(data.password))
    org = m.Organization(name=data.organization_name)
    db.add_all([user, org]); db.flush()
    member = m.Membership(user_id=user.id, organization_id=org.id, role='owner')
    db.add(member)
    session = issue_session(db, response, user.id, org.id)
    db.flush()
    audit(db, Context(user, member, session), 'register', org)
    db.commit()
    return auth_payload(db, session)


@app.post('/api/auth/login')
def login(data: s.Login, response: Response, db: DBSession = Depends(get_db)):
    user = db.scalar(select(m.User).where(m.User.email == str(data.email).lower()))
    valid = passwords.verify(data.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid:
        raise HTTPException(401, 'Invalid email or password')
    membership = db.scalar(select(m.Membership).where(m.Membership.user_id == user.id).order_by(m.Membership.created_at))
    if not membership:
        raise HTTPException(403, 'No organization membership')
    session = issue_session(db, response, user.id, membership.organization_id)
    audit(db, Context(user, membership, session), 'login', user)
    db.commit()
    return auth_payload(db, session)


@app.get('/api/auth/me')
def me(ctx: Context = Depends(current), db: DBSession = Depends(get_db)):
    return auth_payload(db, ctx.session)


@app.post('/api/auth/logout', status_code=204)
def logout(response: Response, ctx: Context = Depends(current), db: DBSession = Depends(get_db)):
    audit(db, ctx, 'logout', ctx.user)
    db.delete(ctx.session); db.commit()
    response.delete_cookie(COOKIE, path='/', secure=settings.cookie_secure, httponly=True, samesite='lax')


@app.post('/api/auth/organization')
def switch_org(data: s.SwitchOrganization, ctx: Context = Depends(current), db: DBSession = Depends(get_db)):
    membership = db.scalar(select(m.Membership).where(m.Membership.user_id == ctx.user.id, m.Membership.organization_id == data.organization_id))
    if not membership:
        raise HTTPException(404, 'Organization not found')
    ctx.session.organization_id = data.organization_id
    db.commit()
    return auth_payload(db, ctx.session)


@app.get('/api/members')
def members(ctx: Context = Depends(current), db: DBSession = Depends(get_db)):
    rows = db.execute(select(m.Membership, m.User).join(m.User).where(m.Membership.organization_id == ctx.org)).all()
    return [{'id': mem.id, 'name': user.name, 'email': user.email, 'role': mem.role} for mem, user in rows]


@app.post('/api/members', status_code=201)
def add_member(data: s.MemberInput, ctx: Context = Depends(current), db: DBSession = Depends(get_db)):
    owner(ctx)
    user = db.scalar(select(m.User).where(m.User.email == str(data.email).lower()))
    if not user:
        raise HTTPException(404, 'Ask this colleague to register first, then add their email here')
    row = m.Membership(user_id=user.id, organization_id=ctx.org, role='member')
    db.add(row); db.flush(); audit(db, ctx, 'add_member', row); db.commit()
    return {'id': row.id, 'name': user.name, 'email': user.email, 'role': row.role}


@app.delete('/api/members/{id}', status_code=204)
def remove_member(id: str, ctx: Context = Depends(current), db: DBSession = Depends(get_db)):
    owner(ctx)
    row = get_record(db, m.Membership, id, ctx)
    if row.role == 'owner':
        raise HTTPException(409, 'The organization owner cannot be removed')
    audit(db, ctx, 'remove_member', row)
    db.execute(delete(m.Session).where(m.Session.organization_id == ctx.org, m.Session.user_id == row.user_id))
    db.delete(row); db.commit()


RESOURCES = {
    'suppliers': (m.Supplier, None, s.SupplierInput),
    'purchase-orders': (m.PurchaseOrder, m.PurchaseOrderLine, s.POInput),
    'receipts': (m.GoodsReceipt, m.GoodsReceiptLine, s.ReceiptInput),
    'invoices': (m.SupplierInvoice, m.SupplierInvoiceLine, s.InvoiceInput),
}


def serialize(db, row, line_model, ctx):
    result = public(row)
    if line_model:
        lines = db.scalars(scoped(line_model, ctx).where(line_model.parent_id == row.id).order_by(line_model.created_at, line_model.id)).all()
        result['lines'] = [public(line) for line in lines]
        if hasattr(row, 'currency'):
            amounts = []
            for line, output in zip(lines, result['lines']):
                amount = s.line_total(line.quantity, line.unit_price)
                output['amount'] = str(amount)
                amounts.append(amount)
            result['total'] = str(s.sum_money(amounts))
    return result


def validate_links(db, data, ctx):
    get_record(db, m.Supplier, data.supplier_id, ctx, lock=True)
    if hasattr(data, 'purchase_order_id'):
        po = get_record(db, m.PurchaseOrder, data.purchase_order_id, ctx, lock=True)
        if po.supplier_id != data.supplier_id:
            raise HTTPException(422, 'The purchase order belongs to a different supplier')
        if hasattr(data, 'currency') and data.currency != po.currency:
            raise HTTPException(422, 'Invoice currency must match the purchase order')
        seen = set()
        for line in data.lines:
            linked = get_record(db, m.PurchaseOrderLine, line.purchase_order_line_id, ctx)
            if linked.parent_id != po.id or linked.id in seen:
                raise HTTPException(422, 'Each line must reference a distinct line from the selected purchase order')
            seen.add(linked.id)


def register_resource(path, model, line_model, input_schema):
    def listing(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), q: str = Query('', max_length=100),
                ctx: Context = Depends(current), db: DBSession = Depends(get_db)):
        query = scoped(model, ctx)
        if q:
            column = model.name if model == m.Supplier else model.number
            query = query.where(column.icontains(q, autoescape=True))
        count = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.scalars(query.order_by(model.created_at.desc(), model.id).offset((page-1)*page_size).limit(page_size)).all()
        return {'items': [serialize(db, row, line_model, ctx) for row in rows], 'total': count, 'page': page, 'page_size': page_size}

    def detail(id: str, ctx: Context = Depends(current), db: DBSession = Depends(get_db)):
        return serialize(db, get_record(db, model, id, ctx), line_model, ctx)

    def write(data, ctx, db, id=None):
        row = get_record(db, model, id, ctx, lock=True) if id else model(organization_id=ctx.org, created_by=ctx.user.id)
        if id and model == m.PurchaseOrder:
            for dependent in (m.GoodsReceipt, m.SupplierInvoice):
                if db.scalar(scoped(dependent, ctx).where(dependent.purchase_order_id == id).limit(1)):
                    raise HTTPException(409, 'Remove linked receipts and invoices before editing this purchase order')
        if line_model:
            validate_links(db, data, ctx)
        fields = data.model_dump(exclude={'lines'})
        for key, value in fields.items():
            setattr(row, key, value.isoformat() if key == 'date' else value)
        row.updated_by = ctx.user.id
        row.updated_at = m.now()
        db.add(row); db.flush()
        if line_model:
            if id:
                db.execute(delete(line_model).where(line_model.organization_id == ctx.org, line_model.parent_id == id))
            for line in data.lines:
                db.add(line_model(**line.model_dump(), organization_id=ctx.org, parent_id=row.id, created_by=ctx.user.id, updated_by=ctx.user.id))
        db.flush(); audit(db, ctx, 'update' if id else 'create', row); db.commit()
        return serialize(db, row, line_model, ctx)

    def create(data: input_schema, ctx: Context = Depends(current), db: DBSession = Depends(get_db)):
        return write(data, ctx, db)

    def update(id: str, data: input_schema, ctx: Context = Depends(current), db: DBSession = Depends(get_db)):
        return write(data, ctx, db, id)

    def remove(id: str, ctx: Context = Depends(current), db: DBSession = Depends(get_db)):
        row = get_record(db, model, id, ctx, lock=True)
        audit(db, ctx, 'delete', row)
        db.delete(row); db.commit()
        return Response(status_code=204)

    for suffix, endpoint, methods, code in [('', listing, ['GET'], 200), ('/{id}', detail, ['GET'], 200),
            ('', create, ['POST'], 201), ('/{id}', update, ['PUT'], 200), ('/{id}', remove, ['DELETE'], 204)]:
        app.add_api_route('/api/' + path + suffix, endpoint, methods=methods, status_code=code, name=f'{methods[0]}_{path}')


for path, spec in RESOURCES.items():
    register_resource(path, *spec)


@app.get('/api/dashboard')
def dashboard(ctx: Context = Depends(current), db: DBSession = Depends(get_db)):
    counts = {path: db.scalar(select(func.count()).select_from(scoped(spec[0], ctx).subquery())) for path, spec in RESOURCES.items()}
    totals = {}
    for row in db.scalars(scoped(m.SupplierInvoice, ctx)):
        value = Decimal(serialize(db, row, m.SupplierInvoiceLine, ctx)['total'])
        totals[row.currency] = s.sum_money([totals.get(row.currency, Decimal('0.00')), value])
    recent = db.scalars(scoped(m.AuditEvent, ctx).order_by(m.AuditEvent.created_at.desc()).limit(8)).all()
    return {'counts': counts, 'invoice_totals': {k: str(v) for k, v in totals.items()}, 'activity': [public(row) for row in recent]}


from .document_routes import router as document_router
app.include_router(document_router)
