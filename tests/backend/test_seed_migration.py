from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from app.config import settings
from app import seed, models as m


def test_seed_is_exact_and_idempotent(client, auth, database, monkeypatch):
    monkeypatch.setattr(seed, 'SessionLocal', database)
    seed.seed(auth['organization_id'])
    seed.seed(auth['organization_id'])
    assert client.get('/api/purchase-orders').json()['total'] == 1
    po = client.get('/api/purchase-orders').json()['items'][0]
    receipt = client.get('/api/receipts').json()['items'][0]
    invoice = client.get('/api/invoices').json()['items'][0]
    assert po['total'] == '5000.00'
    assert receipt['lines'][0]['quantity'] == '90.000'
    assert invoice['total'] == '5500.00'
    assert invoice['currency'] == 'SAR'
    with database() as db:
        assert len(db.scalars(select(m.AuditEvent).where(m.AuditEvent.action == 'seed')).all()) == 4


def test_migration_upgrade_downgrade(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2] / 'backend'
    url = 'sqlite:///' + (tmp_path / 'migration.db').as_posix()
    monkeypatch.setattr(settings, 'database_url', url)
    config = Config(str(root / 'alembic.ini'))
    config.set_main_option('script_location', str(root / 'migrations'))
    command.upgrade(config, 'head')
    engine = create_engine(url)
    tables = inspect(engine).get_table_names()
    assert {'organizations', 'memberships', 'documents', 'match_runs', 'match_findings', 'audit_events', 'supplier_invoices'}.issubset(tables)
    engine.dispose()
    command.downgrade(config, 'base')
    engine = create_engine(url)
    assert inspect(engine).get_table_names() == ['alembic_version']
    engine.dispose()
