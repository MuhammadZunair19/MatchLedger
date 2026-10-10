import os
import uuid

import pytest
from app.db import Base, get_db
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def database():
    url = os.getenv('TEST_DATABASE_URL')
    if url:
        # Use a disposable schema, never drop an existing database or public tables.
        schema = 'test_' + uuid.uuid4().hex
        admin = create_engine(url)
        with admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA {schema}')
        engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
    else:
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        @event.listens_for(engine, 'connect')
        def enable_foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    def override():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = override
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()
    if url:
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
        admin.dispose()


@pytest.fixture
def client(database):
    with TestClient(app) as client:
        yield client


def register(client, email='owner@example.com'):
    response = client.post('/api/auth/register', json={'email': email, 'password': 'test-only-password-123', 'name': 'Test Owner', 'organization_name': 'Test Procurement'})
    assert response.status_code == 201, response.text
    payload = response.json()
    client.headers['X-CSRF-Token'] = payload['csrf_token']
    return payload


@pytest.fixture
def auth(client):
    return register(client)


@pytest.fixture
def records(client, auth):
    supplier = client.post('/api/suppliers', json={'name': 'Cable Supplier'}).json()
    po = client.post('/api/purchase-orders', json={'supplier_id': supplier['id'], 'number': 'PO-001', 'date': '2026-10-09', 'lines': [{'description': 'Cable rolls', 'quantity': '100', 'unit_price': '50.00'}]})
    assert po.status_code == 201, po.text
    return supplier, po.json()
