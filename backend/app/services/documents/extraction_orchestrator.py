from .pdf_service import extract_pages
from .field_extraction import extract_fields
from .line_item_extraction import extract_lines
from .ollama_service import assist
from .validation_service import validate_review


def review_from_extraction(data, extraction_id):
    return {'extraction_id': extraction_id, 'fields': {k: v['normalized_value'] for k, v in data['fields'].items()},
            'lines': [{'id': line['id'], **{k: v['normalized_value'] for k, v in line['fields'].items()}} for line in data['lines']],
            'supplier_id': None, 'purchase_order_id': None}


def extract_document(path, mime, document_type):
    pages = extract_pages(path, mime)
    fields = extract_fields(pages, document_type)
    lines, warnings = extract_lines(pages)
    for page in pages: warnings.extend(page['warnings'])
    warnings.extend(assist(pages, fields))
    data = {'fields': fields, 'lines': lines}
    warnings.extend(validate_review(review_from_extraction(data, ''), document_type))
    warnings.extend(f'{key}: {value["uncertainty"]}' for key, value in fields.items() if value['original_value'] and value['uncertainty'])
    return {'pages': pages, 'data': data, 'warnings': list(dict.fromkeys(warnings)),
            'languages': sorted({lang for p in pages for lang in p['languages']})}
