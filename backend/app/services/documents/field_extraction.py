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
        'expected_delivery_date': ['Expected delivery date', 'Expected delivery', 'تاريخ التسليم المتوقع']},
    'supplier_invoice': {
        'invoice_number': ['Invoice number', 'Invoice no.', 'Invoice no', 'Invoice #', 'Invoice ID', 'Invoice Ref',
            'Bill Number', 'Tax Invoice Number', 'رقم الفاتورة', 'رقم فاتورة', 'فاتورة رقم', 'رقم الفاتورة الضريبية'],
        'invoice_date': ['Invoice date', 'Issue date', 'تاريخ الفاتورة', 'تاريخ الإصدار'],
        'due_date': ['Due date', 'Payment due', 'Payment due date', 'Due on', 'Pay by', 'Payment deadline',
            'تاريخ الاستحقاق', 'تاريخ استحقاق الدفع', 'موعد السداد', 'آخر موعد للدفع'],
        'payment_terms': ['Payment terms', 'Terms', 'شروط الدفع']},
    'goods_receipt': {'number': ['Delivery note number', 'Delivery note no', 'Receipt number', 'DN number', 'رقم إشعار التسليم', 'رقم سند التسليم', 'رقم الاستلام'],
        'date': ['Delivery date', 'Receipt date', 'تاريخ التسليم', 'تاريخ الاستلام']},
}
MONEY_FIELDS = {'subtotal', 'discount', 'vat_amount', 'grand_total', 'quantity', 'unit_price', 'line_total'}
DATE_FIELDS = {'date', 'invoice_date', 'due_date', 'expected_delivery_date'}


def field(value=None, token=None, page=None, name=None, method=None):
    normalized = normalize_text(value) if value is not None else None
    if normalized is not None:
        normalized = normalized.strip().strip(':：').strip()
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


def field_tokens(tokens):
    """Expose bilingual OCR alternatives to label extraction without duplicating table cells."""
    expanded = []
    for token in tokens:
        expanded.append(token)
        for alternative in token.get('alternatives', []):
            expanded.append({**alternative, 'uncertainty': token.get('uncertainty')})
    return expanded


def paired_value(row, label):
    """Pair exact labels with separate values on the same PDF text row."""
    expected = normalize_text(label).casefold()
    for index, token in enumerate(row):
        candidate = normalize_text(token['text']).strip().rstrip(':：#-–—').strip().casefold()
        if candidate != expected:
            continue
        values = [item for offset, item in enumerate(row)
                  if offset != index and normalize_text(item['text']).strip()]
        label_box = token.get('bbox')
        if not values or not label_box or any(not item.get('bbox') for item in values):
            continue
        if all(item['bbox'][0] >= label_box[2] - 0.003 for item in values):
            ordered = sorted(values, key=lambda item: item['bbox'][0])
        elif all(item['bbox'][2] <= label_box[0] + 0.003 for item in values):
            # A right-side Arabic label is followed visually by RTL value glyphs.
            ordered = sorted(values, key=lambda item: item['bbox'][0], reverse=True)
        elif all(max(abs(item['bbox'][offset] - label_box[offset]) for offset in range(4)) < 0.025
                 for item in values):
            # Two recognizers can return a label and its Latin/numeric value for the
            # same detected box. Prefer the evidence containing the most digits.
            ordered = [max(values, key=lambda item: (sum(char.isdigit() for char in item['text']),
                                                      len(normalize_text(item['text']))))]
        else:
            continue
        raw = ' '.join(item['text'] for item in ordered).strip()
        normalized = re.sub(r'\s*-\s*', '-', normalize_text(raw))
        if normalized:
            return raw, normalized, token, values
    return None


def extract_fields(pages, document_type):
    aliases = {**COMMON, **STRATEGIES[document_type]}
    if settings.supplier_aliases_path:
        custom = json.loads(Path(settings.supplier_aliases_path).read_text(encoding='utf-8'))
        for key, values in custom.items():
            if key in aliases and isinstance(values, list): aliases[key] = aliases[key] + values
    fields = {name: field(name=name) for name in aliases}
    for page in pages:
        for row in row_groups(field_tokens(page['tokens'])):
            # Both text directions are considered, while preserving each span verbatim.
            for ordered in (sorted(row, key=lambda t: t.get('reading_order', 0)), row, list(reversed(row))):
                raw_text = ' '.join(t['text'] for t in ordered)
                text = normalize_text(raw_text)
                text = re.sub(r'\s*-\s*', '-', text)
                for name, names in aliases.items():
                    if fields[name]['original_value'] is not None and (name not in MONEY_FIELDS | DATE_FIELDS | {'currency'}
                                                                       or fields[name]['normalized_value'] is not None):
                        continue
                    for label in sorted(names, key=len, reverse=True):
                        match = re.match(r'^\s*' + re.escape(label) + r'(?:\s*[:：#-]\s*|\s+|\S\s+)(.+?)\s*$', text, re.I)
                        if match:
                            token = dict(ordered[0])
                            boxes = [t['bbox'] for t in ordered if t.get('bbox')]
                            if boxes: token['bbox'] = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
                            fields[name] = field(match.group(1), token, page['number'], name)
                            fields[name]['source_text'] = raw_text
                            if ':' in raw_text:
                                fields[name]['original_value'] = raw_text.split(':', 1)[1].strip()
                            break
                        pair = paired_value(row, label)
                        if pair:
                            original, normalized, label_token, value_tokens = pair
                            token = dict(label_token)
                            boxes = [item['bbox'] for item in [label_token, *value_tokens]]
                            token['bbox'] = [min(box[0] for box in boxes), min(box[1] for box in boxes),
                                             max(box[2] for box in boxes), max(box[3] for box in boxes)]
                            fields[name] = field(normalized, token, page['number'], name,
                                                 token.get('method', 'label') + ':label_pair')
                            fields[name]['original_value'] = original
                            fields[name]['source_text'] = ' '.join(item['text'] for item in row)
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
