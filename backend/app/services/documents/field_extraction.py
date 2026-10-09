"""Evidence-based label recognition; missing fields are explicit nulls."""
import json
import re
from pathlib import Path
from ...config import settings
from .normalization_service import normalize_text, decimal_value, currency_value, date_value

COMMON = {
    'supplier_name': ['Supplier', 'Vendor', 'اسم المورد', 'المورد'],
    'supplier_identifier': ['Supplier ID', 'Vendor ID', 'رقم المورد'],
    'supplier_tax_id': ['Supplier VAT', 'Supplier tax ID', 'VAT number', 'الرقم الضريبي للمورد'],
    'buyer_name': ['Buyer', 'Customer', 'Recipient', 'اسم المشتري', 'المشتري', 'المستلم'],
    'buyer_tax_id': ['Buyer VAT', 'Customer VAT', 'الرقم الضريبي للمشتري'],
    'purchase_order_reference': ['PO reference', 'PO ref', 'Purchase order reference', 'مرجع أمر الشراء', 'مرجع امر الشراء'],
    'currency': ['Currency', 'العملة'], 'subtotal': ['Subtotal', 'Sub total', 'المجموع الفرعي'],
    'discount': ['Discount', 'الخصم'], 'vat_amount': ['VAT amount', 'VAT', 'Tax amount', 'ضريبة القيمة المضافة', 'الضريبة'],
    'grand_total': ['Grand total', 'Total due', 'الإجمالي', 'المجموع الكلي'],
    'notes': ['Notes', 'ملاحظات'],
}
STRATEGIES = {
    'purchase_order': {'number': ['Purchase order number', 'PO number', 'PO no', 'رقم أمر الشراء', 'رقم امر الشراء'],
        'date': ['Order date', 'PO date', 'تاريخ الطلب', 'تاريخ أمر الشراء'],
        'expected_delivery_date': ['Expected delivery date', 'تاريخ التسليم المتوقع']},
    'supplier_invoice': {'number': ['Invoice number', 'Invoice no', 'Invoice #', 'رقم الفاتورة'],
        'date': ['Invoice date', 'تاريخ الفاتورة'], 'due_date': ['Due date', 'تاريخ الاستحقاق']},
    'goods_receipt': {'number': ['Delivery note number', 'Delivery note no', 'Receipt number', 'DN number', 'رقم إشعار التسليم', 'رقم سند التسليم', 'رقم الاستلام'],
        'date': ['Delivery date', 'Receipt date', 'تاريخ التسليم', 'تاريخ الاستلام']},
}
MONEY_FIELDS = {'subtotal', 'discount', 'vat_amount', 'grand_total', 'quantity', 'unit_price', 'line_total'}
DATE_FIELDS = {'date', 'due_date', 'expected_delivery_date'}


def field(value=None, token=None, page=None, name=None, method=None):
    normalized = normalize_text(value) if value is not None else None
    uncertainty = token.get('uncertainty') if token else None
    if name in MONEY_FIELDS:
        normalized = decimal_value(value)
        if value is not None and normalized is None:
            uncertainty = 'Unrecognized decimal format'
    elif name in DATE_FIELDS:
        normalized, uncertainty = date_value(value, settings.date_order)
    elif name == 'currency':
        normalized = currency_value(value)
        if value is not None and normalized is None:
            uncertainty = 'Unrecognized currency'
    return {'original_value': value, 'normalized_value': normalized, 'page_number': page,
            'bounding_box': token.get('bbox') if token else None,
            'confidence': token.get('confidence') if token else None,
            'extraction_method': method or (token.get('method', 'label') + ':label' if token else 'missing'),
            'uncertainty': uncertainty or ('Missing value' if value is None else None), 'verification_status': 'unreviewed'}


def row_groups(tokens):
    rows = []
    for token in sorted(tokens, key=lambda t: ((t.get('bbox') or [0, 0])[1], (t.get('bbox') or [0])[0])):
        box = token.get('bbox')
        if not box:
            rows.append([token]); continue
        center = (box[1] + box[3])/2
        match = next((r for r in reversed(rows[-5:]) if r[0].get('bbox') and abs((r[0]['bbox'][1]+r[0]['bbox'][3])/2-center) < max(0.006, (box[3]-box[1])*0.45)), None)
        if match is not None: match.append(token)
        else: rows.append([token])
    return [sorted(r, key=lambda t: (t.get('bbox') or [0])[0]) for r in rows]


def extract_fields(pages, document_type):
    aliases = {**COMMON, **STRATEGIES[document_type]}
    if settings.supplier_aliases_path:
        custom = json.loads(Path(settings.supplier_aliases_path).read_text(encoding='utf-8'))
        for key, values in custom.items():
            if key in aliases and isinstance(values, list): aliases[key] = aliases[key] + values
    fields = {name: field(name=name) for name in aliases}
    for page in pages:
        for row in row_groups(page['tokens']):
            # Both text directions are considered, while preserving each span verbatim.
            for ordered in (row, list(reversed(row))):
                text = ' '.join(t['text'] for t in ordered)
                for name, names in aliases.items():
                    if fields[name]['original_value'] is not None: continue
                    for label in sorted(names, key=len, reverse=True):
                        match = re.match(r'^\s*' + re.escape(label) + r'\s*[:：#]\s*(.+?)\s*$', text, re.I)
                        if match:
                            token = dict(ordered[0])
                            boxes = [t['bbox'] for t in ordered if t.get('bbox')]
                            if boxes: token['bbox'] = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
                            fields[name] = field(match.group(1), token, page['number'], name)
                            break
    # Currency may appear beside an amount rather than under a label. No default is invented.
    if fields['currency']['normalized_value'] is None:
        for page in pages:
            for token in page['tokens']:
                code = currency_value(token['text'])
                if code:
                    fields['currency'] = field(token['text'], token, page['number'], 'currency', 'currency_token')
                    break
            if fields['currency']['normalized_value']: break
    return fields
