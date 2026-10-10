import asyncio
import io
from contextlib import asynccontextmanager

import httpx
import pymupdf
from app.db import get_db
from app.main import app
from openpyxl import load_workbook


@asynccontextmanager
async def client_for(database):
    def override():
        with database() as db:
            yield db
    app.dependency_overrides[get_db]=override
    transport=httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,base_url='http://testserver') as client:
        response=await client.post('/api/auth/register',json={'email':'m4-owner@example.com','password':'test-only-password-123',
            'name':'M4 Owner','organization_name':'M4 Test Organization'})
        assert response.status_code==201,response.text
        auth=response.json();client.headers['X-CSRF-Token']=auth['csrf_token']
        try:
            yield client,auth
        finally:
            app.dependency_overrides.clear()


async def create_exception(client):
    supplier=(await client.post('/api/suppliers',json={'name':'M4 Cable Supplier'})).json()
    order=(await client.post('/api/purchase-orders',json={'supplier_id':supplier['id'],'number':'PO-M4-001','date':'2026-10-01',
        'currency':'SAR','lines':[{'description':'Cable rolls','quantity':'100','unit_price':'50'}]})).json()
    receipt=(await client.post('/api/receipts',json={'supplier_id':supplier['id'],'purchase_order_id':order['id'],
        'number':'GR-M4-001','date':'2026-10-02','lines':[{'description':'Cable rolls','quantity':'90',
        'purchase_order_line_id':order['lines'][0]['id']}]})).json()
    invoice=(await client.post('/api/invoices',json={'supplier_id':supplier['id'],'purchase_order_id':order['id'],
        'number':'INV-M4-001','date':'2026-10-01','due_date':'2026-10-31','currency':'SAR','subtotal':'5500',
        'discount':'0','vat_amount':'0','grand_total':'5500','lines':[{'description':'Cable rolls','quantity':'100',
        'unit_price':'55','purchase_order_line_id':order['lines'][0]['id']}]})).json()
    response=await client.post('/api/matching/runs',json={'invoice_id':invoice['id'],'purchase_order_id':order['id'],
        'matching_mode':'THREE_WAY','receipt_ids':[receipt['id']]})
    assert response.status_code==201,response.text
    return invoice,response.json()


async def approval_scenario(database):
  async with client_for(database) as (client,auth):
    invoice,run=await create_exception(client)
    page=(await client.get('/api/exceptions')).json()
    assert page['metrics']['flagged_invoice_value']=='5500.00'
    blockers=[row for row in page['items'] if row['severity']=='BLOCKING']
    for row in blockers:
        assigned=await client.post(f"/api/exceptions/{row['id']}/assign",json={'version':row['version'],'user_id':auth['user']['id']})
        assert assigned.status_code==200,assigned.text
        note=await client.post('/api/reviews/comments',json={'entity_type':'exception','entity_id':row['id'],'body':'Reviewed against the signed delivery record.'})
        assert note.status_code==201,note.text
        resolved=await client.post(f"/api/exceptions/{row['id']}/resolve",json={'version':assigned.json()['version'],
            'reason':'Supplier evidence reviewed and discrepancy disposition recorded'})
        assert resolved.status_code==200,resolved.text
    draft=(await client.get(f"/api/approvals/{invoice['id']}")).json()
    review=await client.post(f"/api/approvals/{invoice['id']}/submit",json={'version':draft['approval_version'],'reason':'Ready for procurement review'})
    approval=await client.post(f"/api/approvals/{invoice['id']}/submit",json={'version':review.json()['approval_version'],'reason':'Procurement review complete'})
    decided=await client.post(f"/api/approvals/{invoice['id']}/approve",json={'version':approval.json()['approval_version'],'reason':'Matching evidence and resolutions accepted'})
    assert decided.status_code==200,decided.text
    assert decided.json()['approval_status']=='APPROVED'
    stale=await client.post(f"/api/approvals/{invoice['id']}/reject",json={'version':approval.json()['approval_version'],'reason':'Conflicting decision'})
    assert stale.status_code==409
    pdf_meta=await client.post(f"/api/reports/matching/{run['id']}/pdf")
    assert pdf_meta.status_code==201,pdf_meta.text
    pdf=await client.get(f"/api/reports/exports/{pdf_meta.json()['id']}/download")
    document=pymupdf.open(stream=pdf.content,filetype='pdf')
    assert 'INV-M4-001' in ''.join(page.get_text() for page in document)
    excel_meta=(await client.post(f"/api/reports/matching/{run['id']}/excel")).json()
    excel=await client.get(f"/api/reports/exports/{excel_meta['id']}/download")
    workbook=load_workbook(io.BytesIO(excel.content),data_only=False)
    assert workbook['Summary']['B1'].value=='INV-M4-001'
    assert (await client.get('/api/audit/events?q=approved')).json()['total']>=1


def test_exception_review_approval_and_real_exports(database):
    asyncio.run(approval_scenario(database))


async def scoping_scenario(database):
  async with client_for(database) as (client,_):
    _,run=await create_exception(client)
    finding=(await client.get('/api/exceptions')).json()['items'][0]
    export=(await client.post(f"/api/reports/matching/{run['id']}/pdf")).json()
    assert (await client.get('/api/exceptions/00000000-0000-0000-0000-000000000000')).status_code==404
    assert (await client.get('/api/reports/exports/00000000-0000-0000-0000-000000000000/download')).status_code==404
    assert (await client.get(f"/api/exceptions/{finding['id']}")).status_code==200
    assert (await client.get(f"/api/reports/exports/{export['id']}/download")).status_code==200


def test_report_download_and_exception_ids_are_scoped(database):
    asyncio.run(scoping_scenario(database))
