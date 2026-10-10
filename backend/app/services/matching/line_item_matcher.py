import re
import unicodedata
from rapidfuzz import fuzz, process
from .reference_matcher import normalize_reference


def normalize_description(value):
    text = unicodedata.normalize('NFKC', value or '').casefold()
    text = re.sub(r'[^\w\u0600-\u06ff]+', ' ', text)
    return ' '.join(sorted(text.split()))


def match_lines(invoice_lines, po_lines, approved=None):
    approved = approved or {}
    po_by_id = {line['id']: line for line in po_lines}
    results = []
    for invoice in invoice_lines:
        explicit = invoice.get('purchase_order_line_id') or approved.get(invoice['id'])
        if explicit in po_by_id:
            results.append({'invoice_line': invoice, 'po_line': po_by_id[explicit], 'method': 'explicit', 'score': 100, 'review_required': False})
            continue
        sku = normalize_reference(invoice.get('sku'))
        sku_matches = [line for line in po_lines if sku and normalize_reference(line.get('sku')) == sku]
        if len(sku_matches) == 1:
            results.append({'invoice_line': invoice, 'po_line': sku_matches[0], 'method': 'exact_sku', 'score': 100, 'review_required': False})
            continue
        description = normalize_description(invoice.get('description'))
        exact = [line for line in po_lines if description and normalize_description(line.get('description')) == description]
        if len(exact) == 1:
            results.append({'invoice_line': invoice, 'po_line': exact[0], 'method': 'exact_description', 'score': 100, 'review_required': False})
            continue
        choices = {line['id']: normalize_description(line.get('description')) for line in po_lines}
        suggestions = process.extract(description, choices, scorer=fuzz.token_set_ratio, limit=2) if description else []
        if suggestions and suggestions[0][1] >= 70:
            best = po_by_id[suggestions[0][2]]
            ambiguous = len(suggestions) > 1 and suggestions[0][1] - suggestions[1][1] < 10
            results.append({'invoice_line': invoice, 'po_line': best, 'method': 'fuzzy_suggestion',
                            'score': suggestions[0][1], 'review_required': True,
                            'ambiguous': ambiguous, 'suggestions': [{'purchase_order_line_id': item[2], 'score': item[1]} for item in suggestions]})
        else:
            results.append({'invoice_line': invoice, 'po_line': None, 'method': 'unmatched', 'score': 0, 'review_required': True})
    return results

