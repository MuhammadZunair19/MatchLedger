import re
import unicodedata
from ...services.documents.normalization_service import normalize_text


def normalize_reference(value):
    if not value:
        return None
    value = unicodedata.normalize('NFKC', normalize_text(str(value))).upper()
    return re.sub(r'[^A-Z0-9\u0600-\u06ff]', '', value) or None


def reference_matches(left, right):
    a, b = normalize_reference(left), normalize_reference(right)
    return bool(a and b and a == b)

