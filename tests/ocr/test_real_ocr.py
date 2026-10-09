"""Explicit model-download integration suite: RUN_OCR_TESTS=1 pytest tests/ocr -v."""
import os
from pathlib import Path
import pytest
from app.services.documents.extraction_orchestrator import extract_document

pytestmark = pytest.mark.skipif(os.getenv('RUN_OCR_TESTS') != '1', reason='Set RUN_OCR_TESTS=1; real PaddleOCR model cache/download required')
ROOT=Path(__file__).resolve().parents[2]/'sample_data'/'documents'


@pytest.mark.parametrize('name,mime',[('invoice_scanned.png','image/png'),('invoice_scanned.pdf','application/pdf')])
def test_real_scanned_invoice(name,mime):
    result=extract_document(ROOT/name,mime,'supplier_invoice')
    assert result['data']['fields']['number']['normalized_value']=='INV-2026-001'
    assert any(line['fields']['quantity']['normalized_value']=='100' for line in result['data']['lines'])
    assert any(line['fields']['unit_price']['normalized_value']=='55.00' for line in result['data']['lines'])
    assert any(t['confidence'] is not None for p in result['pages'] for t in p['tokens'])


def test_low_quality_requires_review():
    result=extract_document(ROOT/'invoice_low_quality.jpg','image/jpeg','supplier_invoice')
    assert any('resolution' in warning or 'Blur' in warning or 'uncertainty' in warning for warning in result['warnings'])


def test_arabic_raster(tmp_path):
    import pymupdf
    with pymupdf.open(ROOT/'invoice_ar.pdf') as doc:
        doc[0].get_pixmap(matrix=pymupdf.Matrix(2,2)).save(tmp_path/'arabic.png')
    result=extract_document(tmp_path/'arabic.png','image/png','supplier_invoice')
    assert 'ar' in result['languages']
    assert any('paddleocr' in token['method'] for p in result['pages'] for token in p['tokens'])
    assert any('\u0600' <= c <= '\u06ff' for p in result['pages'] for c in p['text'])
