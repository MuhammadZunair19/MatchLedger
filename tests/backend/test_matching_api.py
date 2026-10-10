def test_matching_settings_run_findings_and_rerun(client, auth, records):
    supplier, order = records
    receipt = client.post('/api/receipts', json={'supplier_id': supplier['id'], 'purchase_order_id': order['id'],
        'number': 'GR-MATCH-001', 'date': '2026-10-02', 'lines': [{'description': 'Cable rolls', 'quantity': '90',
        'purchase_order_line_id': order['lines'][0]['id']}]}).json()
    invoice_response = client.post('/api/invoices', json={'supplier_id': supplier['id'], 'purchase_order_id': order['id'],
        'number': 'INV-MATCH-001', 'date': '2026-10-01', 'due_date': '2026-10-31', 'currency': 'SAR',
        'subtotal': '5500', 'discount': '0', 'vat_amount': '0', 'grand_total': '5500',
        'lines': [{'description': 'Cable rolls', 'quantity': '100', 'unit_price': '55',
        'purchase_order_line_id': order['lines'][0]['id']}]})
    assert invoice_response.status_code == 201, invoice_response.text
    invoice = invoice_response.json()
    assert invoice['invoice_number'] == 'INV-MATCH-001'
    assert invoice['invoice_date'] == '2026-10-01'
    assert invoice['due_date'] == '2026-10-31'
    settings = client.put('/api/matching/settings', json={'price_tolerance_percent': '0',
        'price_tolerance_absolute': '0', 'quantity_tolerance': '0', 'total_tolerance_absolute': '0.01',
        'unit_conversions': {}})
    assert settings.status_code == 200, settings.text
    candidates = client.get(f'/api/matching/invoices/{invoice["id"]}/candidates')
    assert candidates.status_code == 200
    assert candidates.json()['purchase_orders'][0]['id'] == order['id']
    response = client.post('/api/matching/runs', json={'invoice_id': invoice['id'], 'purchase_order_id': order['id'],
        'matching_mode': 'THREE_WAY', 'receipt_ids': [receipt['id']]})
    assert response.status_code == 201, response.text
    run = response.json()
    assert run['status'] == 'EXCEPTION'
    assert run['result_summary']['difference_against_supported'] == '1000.00'
    findings = client.get(f'/api/matching/runs/{run["id"]}/findings')
    assert findings.status_code == 200
    assert {'PRICE_MISMATCH', 'QUANTITY_MISMATCH'} <= {item['code'] for item in findings.json()['items']}
    rerun = client.post(f'/api/matching/runs/{run["id"]}/rerun')
    assert rerun.status_code == 201
    assert rerun.json()['id'] != run['id']
    history = client.get('/api/matching/runs').json()
    assert history['total'] == 2
