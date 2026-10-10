from .tolerance_service import decimal


def finding(code, severity, explanation, *, expected=None, actual=None, difference=None, unit=None,
            po_line_id=None, invoice_line_id=None, receipt_line_id=None, evidence=None, tolerance=None,
            review_required=False, detail=None):
    def value(item):
        if item is None:
            return None
        return format(decimal(item), 'f') if not isinstance(item, str) or item.replace('.', '', 1).replace('-', '', 1).isdigit() else item
    return {'code': code, 'severity': severity, 'explanation': explanation,
            'purchase_order_line_id': po_line_id, 'invoice_line_id': invoice_line_id,
            'receipt_line_id': receipt_line_id, 'expected_value': value(expected), 'actual_value': value(actual),
            'difference': value(difference), 'unit': unit, 'evidence': evidence or {},
            'applicable_tolerance': tolerance or {}, 'review_required': review_required,
            'resolution_status': 'OPEN', 'detail': detail or {}}

