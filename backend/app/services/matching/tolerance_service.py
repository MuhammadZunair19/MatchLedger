from decimal import Decimal, ROUND_HALF_UP, localcontext


def decimal(value, default='0') -> Decimal:
    return Decimal(str(value if value is not None else default))


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def within_price(expected, actual, settings) -> bool:
    expected, actual = decimal(expected), decimal(actual)
    difference = abs(actual - expected)
    absolute = decimal(settings.get('price_tolerance_absolute'))
    percent_limit = decimal(settings.get('price_tolerance_percent'))
    with localcontext() as context:
        context.prec = 50
        percent = Decimal('0') if expected == 0 and actual == 0 else (Decimal('Infinity') if expected == 0 else difference / abs(expected) * 100)
    return difference <= absolute or percent <= percent_limit


def convert_quantity(quantity, source_unit, target_unit, conversions):
    value = decimal(quantity)
    source = (source_unit or '').strip().casefold()
    target = (target_unit or '').strip().casefold()
    if not source or not target or source == target:
        return value, source == target or not source or not target
    factor = conversions.get(f'{source}->{target}')
    if factor is None:
        return value, False
    with localcontext() as context:
        context.prec = 50
        return value * decimal(factor), True

