from datetime import date
from decimal import Decimal, localcontext
from .finding_builder import finding
from .line_item_matcher import match_lines
from .reference_matcher import reference_matches
from .tolerance_service import convert_quantity, decimal, money, within_price


ENGINE_VERSION = 'deterministic-v1'


def run_match(snapshot, settings, mode, approved=None):
    po, invoice, receipts = snapshot['purchase_order'], snapshot['invoice'], snapshot.get('receipts', [])
    findings, comparisons = [], []
    missing_receipts = mode == 'THREE_WAY' and not receipts
    if missing_receipts:
        findings.append(finding('INSUFFICIENT_DATA', 'WARNING',
            'Three-way matching needs at least one verified receipt. Quantity support was not evaluated.',
            review_required=True, evidence={'required_record': 'goods_receipt'}))
    currency = invoice.get('currency')
    if po.get('supplier_id') != invoice.get('supplier_id'):
        findings.append(finding('SUPPLIER_MISMATCH', 'BLOCKING', 'The verified invoice and purchase order belong to different suppliers.',
            expected=po.get('supplier_id'), actual=invoice.get('supplier_id'), review_required=True,
            evidence={'purchase_order_id': po['id'], 'invoice_id': invoice['id']}))
    if po.get('currency') != currency:
        findings.append(finding('CURRENCY_MISMATCH', 'BLOCKING', f"The purchase order is {po.get('currency')} but the invoice is {currency}; no exchange rate was applied.",
            expected=po.get('currency'), actual=currency, review_required=True))
    po_reference = invoice.get('po_reference')
    if not po_reference:
        findings.append(finding('MISSING_PO_REFERENCE', 'WARNING', 'The verified invoice has no source PO reference; the selected association requires review.', review_required=True))
    elif not reference_matches(po_reference, po.get('number')):
        findings.append(finding('MISSING_PO_REFERENCE', 'BLOCKING', f"Invoice PO reference {po_reference} does not match selected order {po.get('number')}.",
            expected=po.get('number'), actual=po_reference, review_required=True))
    for duplicate in snapshot.get('duplicates', []):
        findings.append(finding('DUPLICATE_INVOICE', 'BLOCKING',
            f"Invoice number {invoice.get('number')} already exists for this supplier as record {duplicate['id']}.",
            expected=invoice.get('number'), actual=duplicate.get('number'), review_required=True,
            evidence={'duplicate_invoice_id': duplicate['id']}))
    previous = {key: decimal(value) for key, value in snapshot.get('previous_invoiced', {}).items()}
    received = {}
    po_line_ids = {line['id'] for line in po.get('lines', [])}
    for receipt in receipts:
        for line in receipt.get('lines', []):
            key = line.get('purchase_order_line_id')
            if key not in po_line_ids:
                findings.append(finding('UNEXPECTED_RECEIPT_ITEM', 'BLOCKING',
                    f"Receipt item '{line.get('description')}' does not belong to the selected purchase order.",
                    receipt_line_id=line.get('id'), review_required=True))
                continue
            received[key] = received.get(key, Decimal('0')) + decimal(line.get('quantity'))
    matches = match_lines(invoice.get('lines', []), po.get('lines', []), approved)
    matched_po_ids = set()
    invoice_value = Decimal('0'); supported_value = Decimal('0'); price_variance = Decimal('0'); quantity_variance = Decimal('0')
    for match in matches:
        inv, order = match['invoice_line'], match['po_line']
        if not order:
            findings.append(finding('UNEXPECTED_INVOICE_ITEM', 'BLOCKING',
                f"Invoice item '{inv.get('description')}' has no supported purchase-order line.",
                invoice_line_id=inv['id'], review_required=True, evidence={'match_method': match['method']}))
            continue
        matched_po_ids.add(order['id'])
        if match.get('review_required'):
            findings.append(finding('UNCONFIRMED_ITEM_MATCH', 'WARNING',
                f"Invoice item '{inv.get('description')}' is only a suggested match for '{order.get('description')}'.",
                po_line_id=order['id'], invoice_line_id=inv['id'], expected=100, actual=match['score'], unit='similarity score',
                review_required=True, evidence={'method': match['method'], 'suggestions': match.get('suggestions', [])}))
        inv_qty, conversion_ok = convert_quantity(inv.get('quantity'), inv.get('unit_of_measure'), order.get('unit_of_measure'), settings.get('unit_conversions', {}))
        if not conversion_ok:
            findings.append(finding('UNCONFIRMED_ITEM_MATCH', 'BLOCKING',
                f"No verified conversion exists from {inv.get('unit_of_measure')} to {order.get('unit_of_measure')} for '{inv.get('description')}'.",
                po_line_id=order['id'], invoice_line_id=inv['id'], review_required=True))
            continue
        po_qty, po_price, inv_price = decimal(order['quantity']), decimal(order['unit_price']), decimal(inv['unit_price'])
        prior = previous.get(order['id'], Decimal('0'))
        po_remaining = max(Decimal('0'), po_qty - prior)
        received_total = received.get(order['id'], Decimal('0'))
        receipt_remaining = max(Decimal('0'), received_total - prior)
        supported_qty = min(inv_qty, po_remaining if mode == 'TWO_WAY' else min(po_remaining, receipt_remaining))
        invoice_line_value = money(inv_qty * inv_price); supported_line_value = money(supported_qty * po_price)
        invoice_value += invoice_line_value; supported_value += supported_line_value
        line_price_variance = money(inv_qty * (inv_price - po_price)); price_variance += line_price_variance
        quantity_excess = max(Decimal('0'), inv_qty - (po_remaining if mode == 'TWO_WAY' else min(po_remaining, receipt_remaining)))
        line_quantity_variance = money(quantity_excess * po_price); quantity_variance += line_quantity_variance
        price_difference = money(inv_price - po_price)
        if not within_price(po_price, inv_price, settings):
            percent = Decimal('0') if po_price == 0 else (abs(inv_price-po_price) / po_price * 100).quantize(Decimal('0.01'))
            findings.append(finding('PRICE_MISMATCH', 'BLOCKING',
                f"Invoice lists {inv_qty} {inv.get('unit_of_measure') or 'units'} at {inv_price} {currency}; the purchase order specifies {po_price} {currency}. Price variance is {line_price_variance} {currency} ({percent}%).",
                expected=po_price, actual=inv_price, difference=price_difference, unit=f'{currency} per unit',
                po_line_id=order['id'], invoice_line_id=inv['id'],
                tolerance={'absolute': str(settings['price_tolerance_absolute']), 'percent': str(settings['price_tolerance_percent'])},
                evidence={'invoice_quantity': str(inv_qty), 'price_variance': str(line_price_variance)}))
        qty_tolerance = decimal(settings.get('quantity_tolerance'))
        allowable = po_remaining if mode == 'TWO_WAY' else min(po_remaining, receipt_remaining)
        if not missing_receipts and inv_qty > allowable + qty_tolerance:
            basis = 'remaining ordered quantity' if mode == 'TWO_WAY' else 'currently received quantity not consumed by previous invoices'
            findings.append(finding('QUANTITY_MISMATCH', 'BLOCKING',
                f"Invoice quantity {inv_qty} exceeds the {basis} of {allowable} by {inv_qty-allowable} {order.get('unit_of_measure') or 'units'}.",
                expected=allowable, actual=inv_qty, difference=inv_qty-allowable, unit=order.get('unit_of_measure') or 'units',
                po_line_id=order['id'], invoice_line_id=inv['id'],
                tolerance={'quantity': str(settings['quantity_tolerance'])}, evidence={'ordered': str(po_qty), 'received': str(received_total), 'previously_invoiced': str(prior)}))
        if mode == 'THREE_WAY' and not missing_receipts and received_total < po_qty:
            findings.append(finding('PARTIAL_DELIVERY', 'INFO',
                f"{received_total} of {po_qty} {order.get('unit_of_measure') or 'units'} are currently received; the open balance is not treated as cancelled.",
                expected=po_qty, actual=received_total, difference=po_qty-received_total, unit=order.get('unit_of_measure') or 'units',
                po_line_id=order['id']))
        comparisons.append({'purchase_order_line_id': order['id'], 'invoice_line_id': inv['id'], 'product': inv.get('description'),
            'sku': inv.get('sku') or order.get('sku'), 'po_quantity': str(po_qty), 'received_quantity': str(received_total),
            'previously_invoiced_quantity': str(prior), 'invoice_quantity': str(inv_qty), 'po_unit_price': str(po_price),
            'invoice_unit_price': str(inv_price), 'supported_quantity': str(supported_qty),
            'line_difference': str(money(invoice_line_value-supported_line_value)), 'currency': currency,
            'match_method': match['method'], 'match_score': match['score']})
    for line in po.get('lines', []):
        if line['id'] not in matched_po_ids:
            findings.append(finding('MISSING_PO_ITEM', 'INFO',
                f"Purchase-order item '{line.get('description')}' is not present on this invoice; it may remain open for later invoicing.",
                po_line_id=line['id'], review_required=False))
    explicit_subtotal = invoice.get('subtotal')
    total_tolerance = decimal(settings.get('total_tolerance_absolute'), '0.01')
    if explicit_subtotal is not None and abs(decimal(explicit_subtotal)-invoice_value) > total_tolerance:
        findings.append(finding('TOTAL_MISMATCH', 'BLOCKING',
            f"Invoice subtotal {explicit_subtotal} differs from calculated line total {money(invoice_value)} by {money(decimal(explicit_subtotal)-invoice_value)} {currency}.",
            expected=invoice_value, actual=explicit_subtotal, difference=decimal(explicit_subtotal)-invoice_value, unit=currency,
            tolerance={'absolute': str(total_tolerance)}))
    if all(invoice.get(key) is not None for key in ('subtotal', 'vat_amount', 'grand_total')):
        expected_total = decimal(invoice['subtotal']) - decimal(invoice.get('discount')) + decimal(invoice['vat_amount'])
        if abs(decimal(invoice['grand_total'])-expected_total) > total_tolerance:
            findings.append(finding('TAX_MISMATCH', 'BLOCKING',
                f"Grand total {invoice['grand_total']} does not equal subtotal minus discount plus tax ({money(expected_total)} {currency}).",
                expected=expected_total, actual=invoice['grand_total'], difference=decimal(invoice['grand_total'])-expected_total,
                unit=currency, tolerance={'absolute': str(total_tolerance)}))
    if not invoice.get('due_date'):
        findings.append(finding('MISSING_DUE_DATE', 'WARNING',
            'The verified invoice has no due date. Review the source before approval scheduling.', review_required=True))
    elif invoice.get('date') and date.fromisoformat(invoice['due_date']) < date.fromisoformat(invoice['date']):
        findings.append(finding('DUE_DATE_WARNING', 'WARNING', 'The due date precedes the invoice date; verify both source dates.',
            expected=invoice['date'], actual=invoice['due_date'], review_required=True))
    blocking = any(item['severity'] == 'BLOCKING' for item in findings)
    review = any(item['review_required'] for item in findings)
    warnings = any(item['severity'] in ('WARNING', 'INFO') for item in findings)
    status = 'EXCEPTION' if blocking else 'REVIEW_REQUIRED' if review else 'MATCHED_WITH_WARNINGS' if warnings else 'MATCHED'
    with localcontext() as context:
        context.prec = 50
        summary = {'mode': mode, 'currency': currency, 'invoice_number': invoice.get('number'),
            'invoice_date': invoice.get('date'), 'due_date': invoice.get('due_date'), 'purchase_order_number': po.get('number'),
            'invoice_value': str(money(invoice_value)), 'agreed_order_value': str(money(sum(decimal(x['quantity'])*decimal(x['unit_price']) for x in po['lines']))),
            'supported_value': str(money(supported_value)), 'difference_against_supported': str(money(invoice_value-supported_value)),
            'price_variance': str(money(price_variance)), 'quantity_variance': str(money(quantity_variance)),
            'finding_count': len(findings), 'comparisons': comparisons}
    return {'status': status, 'summary': summary, 'findings': findings}
