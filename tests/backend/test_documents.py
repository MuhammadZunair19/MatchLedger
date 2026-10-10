from datetime import timedelta
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.config import settings
from app import models as m
from app.services.documents import jobs
from app.services.documents.storage_service import LocalStorage
from app.services.documents.normalization_service import normalize_text, decimal_value, currency_value, date_value
from app.services.documents.ocr_service import normalize_output
from app.services.documents.extraction_orchestrator import extract_document, review_from_extraction
from app.services.documents.validation_service import validate_review
from app.services.documents.ollama_service import assist
from conftest import register

FIXTURES = Path(__file__).resolve().parents[2] / 'sample_data' / 'documents'


@pytest.fixture
def documents(database, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'document_storage_path', str(tmp_path / 'private'))
    monkeypatch.setattr(jobs, 'SessionLocal', database)
    pending = []
    # Only transport is replaced in isolated API tests. Parsing/extraction/persistence are real.
    monkeypatch.setattr(jobs, 'enqueue', lambda run: pending.append((run.organization_id, run.document_id, run.id)))
    return pending


def upload(client, name='purchase_order_en.pdf', kind='purchase_order'):
    response = client.post('/api/documents/upload', data={'document_type': kind}, files={'file': (name, (FIXTURES/name).read_bytes())})
    assert response.status_code == 201, response.text
    return response.json()


def process(client, pending, doc):
    response = client.post(f'/api/documents/{doc["id"]}/extract')
    assert response.status_code == 202, response.text
    jobs.process_document(*pending.pop())
    result = client.get(f'/api/documents/{doc["id"]}/extraction').json()
    assert result['latest']['status'] == 'REVIEW_REQUIRED', result
    return result


@pytest.mark.parametrize('raw,expected', [('١٠٠','100'),('۵۵٫۵۰','55.50'),('١٬٢٣٤٫٥٠','1,234.50'),(' شركة النور ','شركة النور')])
def test_normalize(raw, expected):
    assert normalize_text(raw) == expected


@pytest.mark.parametrize('raw,expected', [('٥٥٫٥٠','55.50'),('1,234.56','1234.56'),('12,34',None),('nan',None),('1e8',None),('55.00 SAR','55.00')])
def test_decimal_parser(raw, expected): assert decimal_value(raw) == expected


@pytest.mark.parametrize('raw,expected', [('ر.س','SAR'),('ريال سعودي','SAR'),('USD','USD'),('EUR','EUR'),('AED','AED'),('XYZ',None)])
def test_currency(raw, expected): assert currency_value(raw) == expected


def test_dates():
    assert date_value('٢٠٢٦-١٠-٠٩')[0] == '2026-10-09'
    assert date_value('10/09/2026','DMY') == ('2026-09-10','Interpreted using configured DMY date order')
    assert date_value('10/09/2026','MDY')[0] == '2026-10-09'
    assert date_value('10/09/2026','UNKNOWN')[0] is None
    assert date_value('1448/01/01 هـ')[0] is None
    assert date_value('31/02/2026')[0] is None


def test_ocr_adapter_does_not_invent_confidence():
    output = normalize_output({'rec_texts':['١٠٠'], 'rec_boxes':[[10,20,30,40]]},100,100,'ar')
    assert output[0]['text'] == '١٠٠'
    assert output[0]['normalized'] == '100'
    assert output[0]['confidence'] is None
    assert output[0]['bbox'] == [0.1,0.2,0.3,0.4]


@pytest.mark.parametrize('name,kind,quantity,price', [
    ('purchase_order_en.pdf','purchase_order','100','50.00'), ('purchase_order_ar.pdf','purchase_order','100','50.00'),
    ('invoice_en.pdf','supplier_invoice','100','55.00'), ('invoice_ar.pdf','supplier_invoice','100','55.00'),
    ('invoice_bilingual.pdf','supplier_invoice','100','55.00'), ('delivery_note_en.pdf','goods_receipt','90',None), ('delivery_note_ar.pdf','goods_receipt','90',None)])
def test_native_pdf_extraction(name,kind,quantity,price):
    result = extract_document(FIXTURES/name,'application/pdf',kind)
    fields = result['data']['fields']
    assert fields['number']['normalized_value']
    assert fields['date']['normalized_value'] == '2026-10-09'
    assert fields['supplier_name']['normalized_value']
    assert fields['number']['confidence'] is None
    assert fields['number']['bounding_box']
    assert len(result['data']['lines']) == 1
    line = result['data']['lines'][0]['fields']
    assert line['quantity']['normalized_value'] == quantity
    assert line['unit_price']['normalized_value'] == price


def test_multipage_and_arithmetic():
    result = extract_document(FIXTURES/'invoice_multipage.pdf','application/pdf','supplier_invoice')
    assert len(result['data']['lines']) == 2
    assert {line['fields']['description']['page_number'] for line in result['data']['lines']} == {1,2}
    data = review_from_extraction(result['data'],'id')
    data['fields'].update(subtotal='5000', vat_amount='750', grand_total='5800')
    assert any('50.00' in warning for warning in validate_review(data,'supplier_invoice'))


@pytest.mark.parametrize('name',['purchase_order_en.pdf','invoice_scanned.png','invoice_scanned.jpg'])
def test_upload_download_preview(client,auth,documents,name):
    doc = upload(client,name)
    assert 'storage_key' not in doc
    assert doc['page_count'] == 1
    assert client.get('/api/documents').json()['total'] == 1
    assert client.get(f'/api/documents/{doc["id"]}/file').content == (FIXTURES/name).read_bytes()
    assert client.get(f'/api/documents/{doc["id"]}/pages/1').headers['content-type'] == 'image/png'
    assert client.get(f'/api/documents/{doc["id"]}/pages/2').status_code == 404
    assert client.delete(f'/api/documents/{doc["id"]}').status_code == 204
    assert client.get(f'/api/documents/{doc["id"]}/file').status_code == 404


def test_invalid_uploads(client,auth,documents,monkeypatch):
    for filename, content in [('bad.pdf',b'not a pdf'),('bad.pdf',b'%PDF-1.7\ncorrupt'),('wrong.jpg',(FIXTURES/'invoice_en.pdf').read_bytes()),('script.svg',b'<svg></svg>')]:
        response=client.post('/api/documents/upload',data={'document_type':'supplier_invoice'},files={'file':(filename,content)})
        assert response.status_code == 422,response.text
    monkeypatch.setattr(settings,'max_upload_size_mb',1)
    response=client.post('/api/documents/upload',data={'document_type':'supplier_invoice'},files={'file':('large.pdf',b'x'*(2*1024*1024))})
    assert response.status_code == 413
    assert client.get('/api/documents').json()['total'] == 0
    monkeypatch.setattr(settings,'max_document_pages',1)
    response=client.post('/api/documents/upload',data={'document_type':'supplier_invoice'},files={'file':('multi.pdf',(FIXTURES/'invoice_multipage.pdf').read_bytes())})
    assert response.status_code == 422


def test_tenant_isolation(client,auth,documents):
    doc=upload(client); result=process(client,documents,doc)
    with TestClient(app) as other:
        assert other.get(f'/api/documents/{doc["id"]}/file').status_code == 401
        register(other,'other@example.com')
        assert other.get('/api/documents').json()['total'] == 0
        for suffix in ['', '/file','/pages/1','/extraction','/status','/corrections']:
            assert other.get(f'/api/documents/{doc["id"]}{suffix}').status_code == 404
        assert other.post(f'/api/documents/{doc["id"]}/extract').status_code == 404
        assert other.put(f'/api/documents/{doc["id"]}/review',json={'revision':0,'data':result['review_data']}).status_code == 404
        assert other.post(f'/api/documents/{doc["id"]}/verify',json={'revision':0}).status_code == 404
        assert other.delete(f'/api/documents/{doc["id"]}').status_code == 404


def test_storage_traversal(tmp_path):
    storage=LocalStorage(tmp_path)
    for org,key in [('../bad','a'*48),('a'*36,'../secret'),('a'*36,'C:/secret')]:
        with pytest.raises(ValueError): storage.path(org,key)


def test_review_confirm_and_reextract(client,auth,documents,database):
    doc=upload(client); result=process(client,documents,doc); data=result['review_data']
    data['fields']['number']='PO-VERIFIED'; data['fields']['notes']='Human correction'
    response=client.put(f'/api/documents/{doc["id"]}/review',json={'revision':0,'data':data})
    assert response.status_code == 200,response.text
    assert response.json()['review_revision'] == 1
    assert client.put(f'/api/documents/{doc["id"]}/review',json={'revision':0,'data':data}).status_code == 409
    result=process(client,documents,doc)
    assert len(result['history']) == 2
    assert result['review_data']['fields']['notes'] == 'Human correction'
    assert result['latest']['extracted_data']['fields']['number']['normalized_value'] == 'PO-2026-001'
    response=client.post(f'/api/documents/{doc["id"]}/verify',json={'revision':1,'create_supplier':True,'acknowledge_warnings':True})
    assert response.status_code == 200,response.text
    assert client.get('/api/purchase-orders').json()['items'][0]['number'] == 'PO-VERIFIED'
    assert client.get('/api/purchase-orders').json()['items'][0]['total'] == '5000.00'
    assert client.get(f'/api/documents/{doc["id"]}').json()['status'] == 'VERIFIED'
    assert client.post(f'/api/documents/{doc["id"]}/verify',json={'revision':1}).status_code == 409
    changes=client.get(f'/api/documents/{doc["id"]}/corrections').json()
    assert any(c['field_path']=='fields.number' and c['created_by']==auth['user']['id'] for c in changes)
    assert client.delete(f'/api/documents/{doc["id"]}').status_code == 204
    assert client.get('/api/purchase-orders').json()['total'] == 1


@pytest.mark.parametrize('name,kind,resource',[('invoice_en.pdf','supplier_invoice','invoices'),('delivery_note_en.pdf','goods_receipt','receipts')])
def test_confirm_linked_records(client,records,documents,name,kind,resource):
    supplier,po=records; doc=upload(client,name,kind); result=process(client,documents,doc); data=result['review_data']
    data['supplier_id']=supplier['id']; data['purchase_order_id']=po['id']
    data['lines'][0]['purchase_order_line_id']=po['lines'][0]['id']
    assert client.put(f'/api/documents/{doc["id"]}/review',json={'revision':0,'data':data}).status_code == 200
    response=client.post(f'/api/documents/{doc["id"]}/verify',json={'revision':1,'acknowledge_warnings':True})
    assert response.status_code == 200,response.text
    assert client.get('/api/'+resource).json()['total'] == 1


def test_worker_failure_recovery_and_duplicate_protection(client,auth,documents,database,monkeypatch):
    doc=upload(client)
    response=client.post(f'/api/documents/{doc["id"]}/extract'); assert response.status_code == 202
    assert client.post(f'/api/documents/{doc["id"]}/extract').status_code == 409
    assert client.delete(f'/api/documents/{doc["id"]}').status_code == 409
    old=documents.pop()
    with database() as db:
        run=db.get(m.DocumentExtraction,response.json()['id']); run.created_at=m.now()-timedelta(hours=2); db.commit()
    assert client.get(f'/api/documents/{doc["id"]}/status').json()['status']=='FAILED'
    jobs.process_document(*old)
    assert client.get(f'/api/documents/{doc["id"]}/status').json()['status']=='FAILED'
    result=process(client,documents,doc)
    assert result['latest']['version']==2
    monkeypatch.setattr(settings,'max_extraction_attempts',2)
    assert client.post(f'/api/documents/{doc["id"]}/extract').status_code == 409


def test_unavailable_queue_is_truthful(client,auth,documents,monkeypatch):
    from redis.exceptions import ConnectionError
    def unavailable(run): raise ConnectionError()
    monkeypatch.setattr(jobs,'enqueue',unavailable)
    doc=upload(client)
    assert client.post(f'/api/documents/{doc["id"]}/extract').status_code == 503
    assert client.get(f'/api/documents/{doc["id"]}/status').json()['status']=='FAILED'


def test_ollama_external_host_rejected(monkeypatch):
    monkeypatch.setattr(settings,'ollama_enabled',True)
    monkeypatch.setattr(settings,'ollama_base_url','https://external.example.com')
    assert 'local/private' in assist([], {})[0]
