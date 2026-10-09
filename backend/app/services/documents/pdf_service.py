import pymupdf
import numpy as np
from ...config import settings
from .normalization_service import normalize_text, languages
from .image_preprocessing import load_image


def usable_text(text):
    letters = sum(c.isalnum() for c in text)
    return letters >= 30 and text.count('\ufffd') < max(1, len(text) // 50)


def extract_pages(path, mime):
    from .ocr_service import recognize
    pages = []
    if mime != 'application/pdf':
        pixels = load_image(path)
        tokens, warnings, attempts = recognize(pixels)
        pages.append(make_page(1, pixels.shape[1], pixels.shape[0], tokens, warnings, attempts))
        return pages
    with pymupdf.open(path) as doc:
        if len(doc) > settings.max_document_pages:
            raise ValueError('Page limit exceeded')
        for index, page in enumerate(doc):
            text = page.get_text('text', sort=True)
            tokens = []
            warnings = []
            attempts = []
            if usable_text(text):
                for block in page.get_text('dict', sort=True)['blocks']:
                    for line in block.get('lines', []):
                        for span in line.get('spans', []):
                            if not span['text'].strip():
                                continue
                            x0, y0, x1, y1 = span['bbox']
                            tokens.append({'text': span['text'], 'normalized': normalize_text(span['text']),
                                'bbox': [x0/page.rect.width, y0/page.rect.height, x1/page.rect.width, y1/page.rect.height],
                                'confidence': None, 'method': 'pdf_text'})
            else:
                scale = min(settings.ocr_dpi/72, (settings.max_image_pixels / max(1, page.rect.width*page.rect.height)) ** 0.5)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False, colorspace=pymupdf.csRGB, annots=False)
                pixels = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
                tokens, warnings, attempts = recognize(pixels)
            pages.append(make_page(index+1, page.rect.width, page.rect.height, tokens, warnings, attempts))
    return pages


def make_page(number, width, height, tokens, warnings, attempts):
    text = '\n'.join(t['text'] for t in tokens)
    return {'number': number, 'width': width, 'height': height, 'tokens': tokens, 'text': text,
            'normalized_text': normalize_text(text), 'languages': languages(text), 'warnings': warnings, 'ocr_attempts': attempts}
