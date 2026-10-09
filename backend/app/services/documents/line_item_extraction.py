import re
from .field_extraction import field, row_groups
from .normalization_service import normalize_text, decimal_value

ALIASES = {
    'sku': ['sku', 'code', 'product code', 'رمز', 'رمز المنتج'],
    'description': ['description', 'item', 'product', 'الوصف', 'الصنف', 'البيان'],
    'quantity': ['quantity', 'qty', 'delivered', 'الكمية', 'كمية'],
    'unit_of_measure': ['unit', 'uom', 'الوحدة'],
    'unit_price': ['unit price', 'price', 'سعر الوحدة', 'السعر'],
    'line_total': ['line total', 'amount', 'total', 'الإجمالي', 'المبلغ'],
}


def header_key(text):
    text = normalize_text(text).lower().strip(':')
    return next((key for key, names in ALIASES.items() if text in names), None)


def extract_lines(pages):
    lines, warnings = [], []
    for page in pages:
        columns = None
        previous_bottom = None
        for row_index, row in enumerate(row_groups(page['tokens'])):
            recognized = [(header_key(t['text']), t) for t in row if header_key(t['text'])]
            if len(recognized) >= 2 and any(key == 'description' for key, _ in recognized):
                columns = sorted([(key, t['bbox'][0]) for key, t in recognized if t.get('bbox')], key=lambda c: c[1])
                previous_bottom = max(t['bbox'][3] for t in row if t.get('bbox'))
                continue
            if not columns: continue
            text = normalize_text(' '.join(t['text'] for t in row))
            top = min(t['bbox'][1] for t in row if t.get('bbox'))
            if previous_bottom is not None and top - previous_bottom > 0.03:
                columns = None; continue
            if re.search(r'(?i)subtotal|grand total|vat\s*:|discount\s*:|notes\s*:|المجموع|الضريبة|ملاحظات|الخصم', text):
                columns = None; continue
            cells = {key: [] for key, _ in columns}
            for token in row:
                if token.get('bbox'):
                    left = token['bbox'][0]
                    key = next((key for key, start in reversed(columns) if left >= start - 0.012), columns[0][0])
                    cells[key].append(token)
            values = {key: ' '.join(t['text'] for t in tokens).strip() for key, tokens in cells.items()}
            split_quantity = False
            # OCR sometimes emits a description and adjacent quantity as one region.
            # Split only with both geometric support and an explicit numeric suffix.
            quantity_start = next((x for key, x in columns if key == 'quantity'), None)
            if not values.get('quantity') and quantity_start is not None and cells.get('description'):
                token = cells['description'][-1]
                match = re.match(r'^(.*?)\s+(\d+(?:[.,٫]\d+)?)$', normalize_text(token['text']))
                if match and token['bbox'][2] > quantity_start:
                    values['description'] = ' '.join(t['text'] for t in cells['description'][:-1]) + ' ' + match.group(1)
                    values['description'] = values['description'].strip()
                    values['quantity'] = match.group(2)
                    cells['quantity'] = [token]
                    split_quantity = True
            if not any(values.values()): continue
            previous_bottom = max(t['bbox'][3] for t in row if t.get('bbox'))
            # Keep standalone wrapped text as an uncertain row; never silently merge it.
            quantity = decimal_value(values.get('quantity'))
            if not values.get('description') and quantity is None: continue
            uncertain = quantity is None or not values.get('description')
            row_fields = {}
            for key in ALIASES:
                tokens = cells.get(key, [])
                token = dict(tokens[0]) if tokens else None
                if token:
                    boxes = [t['bbox'] for t in tokens]
                    token['bbox'] = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
                row_fields[key] = field(values.get(key) or None, token, page['number'], key, 'layout_table' if token else 'missing')
                if split_quantity and key in ('description', 'quantity'):
                    row_fields[key]['uncertainty'] = 'OCR region spans columns; numeric suffix separated using table layout. Verify this split.'
            lines.append({'id': f"p{page['number']}-r{row_index}", 'fields': row_fields,
                          'uncertainty': 'Incomplete or wrapped row; correct or merge explicitly' if uncertain else None})
            if uncertain: warnings.append(f"Page {page['number']}: uncertain table row retained for review.")
    if not lines: warnings.append('No reliable table layout found. Enter line items manually.')
    return lines, warnings
