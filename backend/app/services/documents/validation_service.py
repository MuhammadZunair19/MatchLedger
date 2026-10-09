from decimal import Decimal, localcontext
from .normalization_service import decimal_value, date_value, currency_value


def validate_review(data, document_type):
    fields = data.get('fields', {})
    warnings = []
    for name in ['number', 'date', 'supplier_name']:
        if not fields.get(name): warnings.append(f'Missing required field: {name}')
    if fields.get('date') and date_value(fields['date'])[0] is None: warnings.append('Date needs correction')
    if document_type != 'goods_receipt' and not currency_value(fields.get('currency')): warnings.append('Currency is missing or unknown')
    values = {}
    with localcontext() as context:
        context.prec = 50
        for name in ('subtotal', 'discount', 'vat_amount', 'grand_total'):
            raw = fields.get(name)
            parsed = decimal_value(raw)
            if raw and (parsed is None or Decimal(parsed) < 0): warnings.append(f'Invalid nonnegative amount: {name}')
            if parsed is not None: values[name] = Decimal(parsed)
        if all(key in values for key in ('subtotal', 'vat_amount', 'grand_total')):
            expected = values['subtotal'] - values.get('discount', Decimal(0)) + values['vat_amount']
            difference = values['grand_total'] - expected
            if difference != 0: warnings.append(f'Total differs from subtotal - discount + VAT by {difference:.2f}. Review the source.')
        amounts = []
        for i, line in enumerate(data.get('lines', []), 1):
            if not line.get('description'): warnings.append(f'Line {i}: missing description')
            qty = decimal_value(line.get('quantity'))
            price = decimal_value(line.get('unit_price'))
            if qty is None or Decimal(qty) <= 0: warnings.append(f'Line {i}: quantity must be positive to save a business record')
            if document_type != 'goods_receipt' and (price is None or Decimal(price) < 0): warnings.append(f'Line {i}: invalid unit price')
            if qty is not None and price is not None:
                from ...schemas import line_total
                amount = line_total(Decimal(qty), Decimal(price)); amounts.append(amount)
                stated = decimal_value(line.get('line_total'))
                if stated is not None and Decimal(stated) != amount: warnings.append(f'Line {i}: stated amount differs from quantity × unit price')
        if amounts and len(amounts) == len(data.get('lines', [])) and 'subtotal' in values and sum(amounts, Decimal(0)) != values['subtotal']:
            warnings.append('Subtotal differs from the sum of line amounts')
    return warnings
