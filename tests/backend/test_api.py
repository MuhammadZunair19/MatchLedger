from datetime import timedelta
from decimal import Decimal
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from fastapi.testclient import TestClient
from app.main import app
from app import models as m
from app.schemas import line_total, sum_money, Register
from conftest import register


def payload(supplier, po, price=True):
    return {'supplier_id': supplier['id'], 'purchase_order_id': po['id'], 'number': 'DOC-001', 'date': '2026-10-09',
            'lines': [{'description': 'Cable rolls', 'quantity': '100' if price else '90', 'purchase_order_line_id': po['lines'][0]['id'], **({'unit_price': '55.00'} if price else {})}]}


def test_decimal_rounding():
    assert line_total(Decimal('0.1'), Decimal('0.20')) == Decimal('0.02')
    assert line_total(Decimal('1.005'), Decimal('1')) == Decimal('1.01')
    assert line_total(Decimal('100'), Decimal('55')) == Decimal('5500.00')
    assert sum_money([Decimal('9999999999999999999999999.99')] * 200) == Decimal('1999999999999999999999999998.00')


def test_password_whitespace_is_preserved():
    data = Register(name=' Owner ', email='owner@example.com', organization_name=' Team ', password='  long-password-123  ')
    assert data.password == '  long-password-123  '
    assert data.name == 'Owner'


def test_authentication(client, database):
    assert client.get('/api/suppliers').status_code == 401
    auth = register(client)
    assert 'HttpOnly' in client.cookies.jar._cookies['testserver.local']['/']['matchledger_session']._rest
    assert client.get('/api/auth/me').json()['user']['email'] == 'owner@example.com'
    assert client.post('/api/suppliers', json={'name': 'No CSRF'}, headers={'X-CSRF-Token': ''}).status_code == 403
    assert client.post('/api/suppliers', json={'name': 'Bad origin'}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.post('/api/auth/logout').status_code == 204
    assert client.get('/api/auth/me').status_code == 401
    assert client.post('/api/auth/login', json={'email': 'owner@example.com', 'password': 'wrong'}).status_code == 401
    login = client.post('/api/auth/login', json={'email': 'owner@example.com', 'password': 'test-only-password-123'})
    assert login.status_code == 200
    with database() as db:
        session = db.scalar(select(m.Session))
        assert session.token_hash != client.cookies.get('matchledger_session')
        session.expires_at = m.now() - timedelta(seconds=1); db.commit()
    assert client.get('/api/auth/me').status_code == 401


def test_supplier_crud_and_pagination(client, auth):
    response = client.post('/api/suppliers', json={'name': 'Supplier A', 'email': 'sales@example.com'})
    assert response.status_code == 201
    id = response.json()['id']
    assert client.get(f'/api/suppliers/{id}').json()['name'] == 'Supplier A'
    assert client.put(f'/api/suppliers/{id}', json={'name': 'Updated'}).json()['name'] == 'Updated'
    assert client.post('/api/suppliers', json={'name': 'Updated'}).status_code == 409
    client.post('/api/suppliers', json={'name': 'Other'})
    assert len(client.get('/api/suppliers?page_size=1').json()['items']) == 1
    assert client.get('/api/suppliers?q=Updated').json()['total'] == 1
    assert client.get('/api/suppliers?page=0').status_code == 422
    assert client.delete(f'/api/suppliers/{id}').status_code == 204
    assert client.get(f'/api/suppliers/{id}').status_code == 404


@pytest.mark.parametrize('resource', ['receipts', 'invoices'])
def test_document_crud(client, records, resource):
    supplier, po = records
    assert po['total'] == '5000.00'
    body = payload(supplier, po, resource == 'invoices')
    response = client.post('/api/' + resource, json=body)
    assert response.status_code == 201, response.text
    row = response.json()
    if resource == 'invoices': assert row['total'] == '5500.00'
    else: assert row['lines'][0]['quantity'] == '90.000'
    path = f"/api/{resource}/{row['id']}"
    assert client.get(path).status_code == 200
    body['notes'] = 'Updated'; body['lines'][0]['quantity'] = '80'
    response = client.put(path, json=body)
    assert response.status_code == 200, response.text
    assert response.json()['notes'] == 'Updated'
    assert client.delete('/api/purchase-orders/' + po['id']).status_code == 409
    assert client.delete(path).status_code == 204
    assert client.get(path).status_code == 404
    assert client.delete('/api/purchase-orders/' + po['id']).status_code == 204
    assert client.delete('/api/suppliers/' + supplier['id']).status_code == 204


def test_po_update_validation_and_audit(client, records, database):
    supplier, po = records
    body = {'supplier_id': supplier['id'], 'number': 'PO-UPDATED', 'date': '2026-10-09', 'lines': [{'description': 'Roll', 'quantity': '2.5', 'unit_price': '10.10'}]}
    response = client.put('/api/purchase-orders/' + po['id'], json=body)
    assert response.json()['total'] == '25.25'
    assert client.delete('/api/suppliers/' + supplier['id']).status_code == 409
    for bad in [{'currency': 'BAD'}, {'lines': []}, {'organization_id': 'injected'}]:
        assert client.post('/api/purchase-orders', json={**body, **bad}).status_code == 422
    body['lines'][0]['unit_price'] = '0.001'
    assert client.post('/api/purchase-orders', json=body).status_code == 422
    with database() as db:
        assert db.scalar(select(m.AuditEvent).where(m.AuditEvent.action == 'update'))


@pytest.mark.parametrize('resource', ['suppliers', 'purchase-orders', 'receipts', 'invoices'])
def test_tenant_isolation_all_operations(client, records, resource, database):
    supplier, po = records
    if resource == 'suppliers': row, body = supplier, {'name': 'Stolen'}
    elif resource == 'purchase-orders':
        row = po; body = {'supplier_id': supplier['id'], 'number': 'Stolen', 'date': '2026-10-09', 'lines': [{'description': 'Roll', 'quantity': '1', 'unit_price': '1'}]}
    else:
        body = payload(supplier, po, resource == 'invoices')
        row = client.post('/api/' + resource, json=body).json()
    with TestClient(app) as other:
        register(other, 'other@example.com')
        path = f"/api/{resource}/{row['id']}"
        assert other.get('/api/' + resource).json()['total'] == 0
        assert other.get(path).status_code == 404
        assert other.put(path, json=body).status_code == 404
        assert other.delete(path).status_code == 404
        if resource != 'suppliers': assert other.post('/api/' + resource, json=body).status_code == 404
        assert other.get('/api/dashboard').json()['counts'][resource] == 0


def test_cross_tenant_database_constraint(client, records, database):
    supplier, po = records
    with TestClient(app) as other:
        auth = register(other, 'other@example.com')
    with database() as db:
        db.add(m.PurchaseOrder(organization_id=auth['organization_id'], supplier_id=supplier['id'], number='Illegal', date='2026-10-09'))
        with pytest.raises(IntegrityError): db.commit()


def test_links_and_po_lock(client, records):
    supplier, po = records
    second = client.post('/api/suppliers', json={'name': 'Second'}).json()
    body = payload(supplier, po)
    assert client.post('/api/invoices', json={**body, 'supplier_id': second['id']}).status_code == 422
    assert client.post('/api/invoices', json={**body, 'currency': 'USD'}).status_code == 422
    split_invoice = client.post('/api/invoices', json={**body, 'lines': body['lines'] * 2})
    assert split_invoice.status_code == 201
    assert len(split_invoice.json()['lines']) == 2
    assert split_invoice.json()['total'] == '11000.00'
    update = {'supplier_id': supplier['id'], 'number': 'Edited', 'date': '2026-10-09', 'lines': [{'description': 'Roll', 'quantity': '1', 'unit_price': '1'}]}
    assert client.put('/api/purchase-orders/' + po['id'], json=update).status_code == 409


def test_membership_switch_and_revocation(client, auth, database):
    with TestClient(app) as colleague:
        second = register(colleague, 'member@example.com')
        member = client.post('/api/members', json={'email': 'member@example.com'})
        assert member.status_code == 201
        assert colleague.post('/api/auth/organization', json={'organization_id': auth['organization_id']}).status_code == 200
        assert colleague.post('/api/members', json={'email': 'nobody@example.com'}).status_code == 403
        assert colleague.post('/api/suppliers', json={'name': 'Shared supplier'}).status_code == 201
        assert client.get('/api/suppliers').json()['total'] == 1
        assert client.post('/api/auth/organization', json={'organization_id': second['organization_id']}).status_code == 404
        assert client.delete('/api/members/' + member.json()['id']).status_code == 204
        assert colleague.get('/api/suppliers').status_code == 401
