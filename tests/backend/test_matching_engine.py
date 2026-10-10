from decimal import Decimal

from app.services.matching.line_item_matcher import match_lines
from app.services.matching.matching_orchestrator import run_match
from app.services.matching.reference_matcher import (
    normalize_reference,
    reference_matches,
)
from app.services.matching.tolerance_service import within_price

SETTINGS = {'price_tolerance_percent': '0', 'price_tolerance_absolute': '0',
            'quantity_tolerance': '0', 'total_tolerance_absolute': '0.01', 'unit_conversions': {}}


def scenario(receipts=True):
    po_line = {'id': 'pol-1', 'description': 'Cable roll', 'sku': 'CAB-50', 'unit_of_measure': 'roll', 'quantity': '100', 'unit_price': '50.00'}
    invoice_line = {'id': 'invl-1', 'description': 'Cable rolls', 'sku': 'CAB-50', 'unit_of_measure': 'roll', 'quantity': '100', 'unit_price': '55.00', 'purchase_order_line_id': 'pol-1'}
    return {'purchase_order': {'id': 'po-1', 'supplier_id': 'supplier-1', 'number': 'PO-001', 'currency': 'SAR', 'lines': [po_line]},
            'invoice': {'id': 'inv-1', 'supplier_id': 'supplier-1', 'number': 'INV-001', 'date': '2026-10-01', 'due_date': '2026-10-31',
                'currency': 'SAR', 'po_reference': 'PO 001', 'subtotal': '5500.00', 'discount': '0', 'vat_amount': '0', 'grand_total': '5500.00', 'lines': [invoice_line]},
            'receipts': [{'id': 'gr-1', 'lines': [{'id': 'grl-1', 'purchase_order_line_id': 'pol-1', 'description': 'Cable roll', 'quantity': '90'}]}] if receipts else [],
            'previous_invoiced': {}, 'duplicates': []}


def codes(result):
    return {item['code'] for item in result['findings']}


def test_reference_scenario_uses_decimal_and_explains_variance():
    result = run_match(scenario(), SETTINGS, 'THREE_WAY')
    assert result['status'] == 'EXCEPTION'
    assert {'PRICE_MISMATCH', 'QUANTITY_MISMATCH', 'PARTIAL_DELIVERY'} <= codes(result)
    assert result['summary']['invoice_value'] == '5500.00'
    assert result['summary']['supported_value'] == '4500.00'
    assert result['summary']['price_variance'] == '500.00'
    assert result['summary']['quantity_variance'] == '500.00'
    assert result['summary']['difference_against_supported'] == '1000.00'


def test_two_way_ignores_receipt_quantity_but_checks_price():
    result = run_match(scenario(False), SETTINGS, 'TWO_WAY')
    assert 'QUANTITY_MISMATCH' not in codes(result)
    assert 'PRICE_MISMATCH' in codes(result)


def test_three_way_without_receipts_requires_review_without_false_quantity_claim():
    data = scenario(False)
    data['invoice']['lines'][0]['unit_price'] = '50.00'
    data['invoice']['subtotal'] = data['invoice']['grand_total'] = '5000.00'
    result = run_match(data, SETTINGS, 'THREE_WAY')
    assert result['status'] == 'REVIEW_REQUIRED'
    assert 'INSUFFICIENT_DATA' in codes(result)
    assert 'QUANTITY_MISMATCH' not in codes(result)


def test_supplier_currency_duplicate_and_due_date_findings():
    data = scenario(); data['invoice']['supplier_id'] = 'supplier-2'; data['invoice']['currency'] = 'USD'
    data['invoice']['due_date'] = '2026-09-01'; data['duplicates'] = [{'id': 'old', 'number': 'INV/001'}]
    result = run_match(data, SETTINGS, 'THREE_WAY')
    assert {'SUPPLIER_MISMATCH', 'CURRENCY_MISMATCH', 'DUPLICATE_INVOICE', 'DUE_DATE_WARNING'} <= codes(result)


def test_tolerance_boundary_and_zero_expected_price():
    configured = {**SETTINGS, 'price_tolerance_percent': '10', 'price_tolerance_absolute': '0.01'}
    assert within_price(Decimal(50), Decimal(55), configured)
    assert not within_price(Decimal(0), Decimal(1), configured)


def test_normalization_preserves_leading_zero_semantics_and_matches_punctuation():
    assert normalize_reference(' INV-0007 ') == normalize_reference('inv/0007')
    assert normalize_reference('INV-0007') != normalize_reference('INV-7')
    assert reference_matches('PO 001', 'PO-001')


def test_multiple_invoice_lines_can_map_to_one_po_line():
    po = [{'id': 'po-line', 'description': 'Cable', 'sku': 'C1'}]
    invoice = [{'id': 'a', 'description': 'Cable', 'sku': 'C1'}, {'id': 'b', 'description': 'Cable', 'sku': 'C1'}]
    matches = match_lines(invoice, po, {'a': 'po-line', 'b': 'po-line'})
    assert [item['po_line']['id'] for item in matches] == ['po-line', 'po-line']


def test_fuzzy_matches_remain_review_required():
    result = match_lines([{'id': 'i', 'description': 'Industrial copper cable roll', 'sku': None}],
                         [{'id': 'p', 'description': 'Copper industrial cable rolls', 'sku': None}])
    assert result[0]['method'] == 'fuzzy_suggestion'
    assert result[0]['review_required'] is True


def test_exact_sku_match_and_explicit_unit_conversion():
    data = scenario()
    line = data['invoice']['lines'][0]
    line['purchase_order_line_id'] = None; line['description'] = 'Different wording'; line['quantity'] = '10'; line['unit_of_measure'] = 'box'
    configured = {**SETTINGS, 'unit_conversions': {'box->roll': '10'}}
    result = run_match(data, configured, 'TWO_WAY')
    assert result['summary']['comparisons'][0]['match_method'] == 'exact_sku'
    assert 'UNCONFIRMED_ITEM_MATCH' not in codes(result)


def test_different_units_without_conversion_are_blocking():
    data = scenario(); data['invoice']['lines'][0]['unit_of_measure'] = 'box'
    assert 'UNCONFIRMED_ITEM_MATCH' in codes(run_match(data, SETTINGS, 'THREE_WAY'))


def test_multiple_receipts_are_aggregated():
    data = scenario(); data['invoice']['lines'][0]['quantity'] = '100'; data['invoice']['lines'][0]['unit_price'] = '50'
    data['invoice']['subtotal'] = data['invoice']['grand_total'] = '5000'
    data['receipts'] = [{'id': 'one', 'lines': [{'id': 'r1', 'purchase_order_line_id': 'pol-1', 'description': 'Cable', 'quantity': '40'}]},
                        {'id': 'two', 'lines': [{'id': 'r2', 'purchase_order_line_id': 'pol-1', 'description': 'Cable', 'quantity': '60'}]}]
    result = run_match(data, SETTINGS, 'THREE_WAY')
    assert result['status'] == 'MATCHED'
    assert result['summary']['supported_value'] == '5000.00'


def test_previous_invoice_reduces_remaining_quantity_without_rerun_allocation():
    data = scenario(False); data['previous_invoiced'] = {'pol-1': '40'}
    result = run_match(data, SETTINGS, 'TWO_WAY')
    quantity = next(item for item in result['findings'] if item['code'] == 'QUANTITY_MISMATCH')
    assert quantity['expected_value'] == '60'


def test_missing_and_unexpected_items_are_distinct():
    data = scenario(); data['invoice']['lines'][0]['purchase_order_line_id'] = None
    data['invoice']['lines'][0]['sku'] = None; data['invoice']['lines'][0]['description'] = 'Unrelated service fee'
    result = run_match(data, SETTINGS, 'TWO_WAY')
    assert {'UNEXPECTED_INVOICE_ITEM', 'MISSING_PO_ITEM'} <= codes(result)


def test_total_and_tax_arithmetic_findings():
    data = scenario(); data['invoice']['subtotal'] = '5000'; data['invoice']['vat_amount'] = '750'; data['invoice']['grand_total'] = '5800'
    result = run_match(data, SETTINGS, 'THREE_WAY')
    assert {'TOTAL_MISMATCH', 'TAX_MISMATCH'} <= codes(result)
