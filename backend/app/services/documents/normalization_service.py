import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
import pycountry

DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def normalize_text(value: str) -> str:
    # NFKC expands Arabic presentation forms; don't fold Arabic letters or strip name diacritics.
    value = unicodedata.normalize('NFKC', value).translate(DIGITS)
    value = value.replace('٫', '.').replace('٬', ',')
    value = re.sub(r'[\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', value)
    return re.sub(r'[ \t\u00a0]+', ' ', value).strip()


def decimal_value(value: str | None) -> str | None:
    if value is None:
        return None
    text = normalize_text(value).strip()
    text = re.sub(r'(?i)\b(?:SAR|USD|AED|EUR|GBP)\b|ر\.?\s?س\.?|﷼', '', text).strip()
    # Commas are accepted only as valid thousands groups, never guessed as decimal marks.
    if ',' in text:
        if not re.fullmatch(r'[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?', text):
            return None
        text = text.replace(',', '')
    if not re.fullmatch(r'[+-]?\d{1,18}(?:\.\d{1,6})?', text):
        return None
    try:
        number = Decimal(text)
        return format(number, 'f') if number.is_finite() else None
    except InvalidOperation:
        return None


def currency_value(value: str | None) -> str | None:
    if not value:
        return None
    text = normalize_text(value)
    aliases = {'SAR': ['ر.س', 'ر س', 'ريال سعودي', 'الريال السعودي', 'Saudi Riyal', 'Saudi Riyals', '﷼'],
               'AED': ['درهم إماراتي', 'UAE Dirham'], 'USD': ['US Dollar', 'دولار أمريكي'], 'EUR': ['€', 'Euro', 'يورو']}
    for code, names in aliases.items():
        if any(name.casefold() in text.casefold() for name in names):
            return code
    for code in re.findall(r'\b[A-Z]{3}\b', text.upper()):
        if pycountry.currencies.get(alpha_3=code):
            return code
    return None


def date_value(value: str | None, order='DMY') -> tuple[str | None, str | None]:
    if not value:
        return None, 'Missing date'
    text = normalize_text(value)
    if re.search(r'هجري|هـ|hijri', text, re.I):
        return None, 'Hijri date requires manual Gregorian confirmation'
    formats = ['%Y-%m-%d', '%Y/%m/%d', '%d %B %Y', '%d %b %Y']
    if order in ('DMY', 'MDY'):
        formats += ['%d/%m/%Y', '%d-%m-%Y'] if order == 'DMY' else ['%m/%d/%Y', '%m-%d-%Y']
    for fmt in formats:
        try:
            result = datetime.strptime(text, fmt).date()
            if not 1900 <= result.year <= 2200:
                return None, 'Unsupported calendar/year; review the raw date'
            ambiguous = '/' in text and not text.startswith(str(result.year)) and result.day <= 12 and result.month <= 12
            return result.isoformat(), f'Interpreted using configured {order} date order' if ambiguous else None
        except ValueError:
            pass
    return None, 'Unrecognized date format; review the raw date'


def languages(text):
    return [code for code, pattern in [('ar', r'[\u0600-\u06ff]'), ('en', r'[A-Za-z]')] if re.search(pattern, text)]
