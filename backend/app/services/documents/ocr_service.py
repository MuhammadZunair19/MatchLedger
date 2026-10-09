"""PaddleOCR 3.x adapter. Confidence comes only from the recognizer."""
import re
from functools import lru_cache
from ...config import settings
from .normalization_service import normalize_text
from .image_preprocessing import candidates


@lru_cache(maxsize=2)
def engine(language):
    from paddleocr import PaddleOCR
    return PaddleOCR(
        text_detection_model_name='PP-OCRv5_mobile_det',
        text_recognition_model_name='arabic_PP-OCRv5_mobile_rec' if language == 'ar' else 'en_PP-OCRv5_mobile_rec',
        use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=True,
        device=settings.ocr_device, enable_mkldnn=False,
    )


def normalize_output(result, width, height, language):
    texts = result.get('rec_texts', [])
    scores = result.get('rec_scores', [])
    boxes = result.get('rec_boxes', [])
    output = []
    for i, text in enumerate(texts):
        if not str(text).strip():
            continue
        box = [float(v) for v in boxes[i]] if i < len(boxes) else None
        output.append({'text': str(text), 'normalized': normalize_text(str(text)),
            'bbox': [box[0]/width, box[1]/height, box[2]/width, box[3]/height] if box else None,
            'confidence': float(scores[i]) if i < len(scores) else None,
            'method': f'paddleocr:{language}'})
    return output


def overlap(a, b):
    if not a or not b:
        return 0
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    return intersection / max(0.000001, min((a[2]-a[0])*(a[3]-a[1]), (b[2]-b[0])*(b[3]-b[1])))


def recognize(image):
    variants, warnings = candidates(image)
    attempts = []
    for variant, pixels in variants:
        tokens = []
        for language in settings.ocr_languages.split(','):
            language = language.strip()
            if language not in ('ar', 'en'):
                raise ValueError('OCR_LANGUAGES supports en,ar')
            for result in engine(language).predict(pixels[:, :, ::-1]):
                tokens.extend(normalize_output(result, pixels.shape[1], pixels.shape[0], language))
        # Select overlapping bilingual hypotheses; retain all candidates as evidence.
        selected = []
        for token in sorted(tokens, key=lambda t: t['confidence'] or 0, reverse=True):
            existing = next((t for t in selected if overlap(t['bbox'], token['bbox']) > 0.7), None)
            if existing is None:
                selected.append(dict(token))
            else:
                existing.setdefault('alternatives', []).append(token)
                if normalize_text(token['text']) != normalize_text(existing['text']) and (token['confidence'] or 0) > 0.7:
                    existing['uncertainty'] = 'Bilingual recognizers disagree; inspect the source'
        quality = sum(t['confidence'] or 0 for t in selected) / max(1, len(selected))
        attempts.append({'variant': variant, 'tokens': selected, 'quality': quality})
    best = max(attempts, key=lambda a: a['quality'])
    tokens = sorted(best['tokens'], key=lambda t: (t['bbox'][1] if t['bbox'] else 0, t['bbox'][0] if t['bbox'] else 0))
    if best['quality'] < 0.85 or any(t.get('uncertainty') for t in tokens):
        warnings.append('OCR uncertainty: verify recognized text against the original.')
    if not tokens:
        warnings.append('No readable text found; manual entry is required.')
    return tokens, warnings, attempts
