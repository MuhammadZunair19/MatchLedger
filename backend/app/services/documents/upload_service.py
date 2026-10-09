import json
import subprocess
import sys
from pathlib import Path
from ...config import settings


def bounded_parse(path, mode='inspect', page=1):
    command = [sys.executable, str(Path(__file__).with_name('parse_child.py')), mode, str(path),
               str(settings.max_document_pages if mode == 'inspect' else page), str(settings.max_image_pixels)]
    try:
        result = subprocess.run(command, capture_output=True, timeout=settings.document_parse_timeout, check=False)
    except subprocess.TimeoutExpired:
        raise ValueError('Document parsing exceeded the time limit') from None
    if result.returncode:
        raise ValueError('File is corrupted, unsupported, encrypted, or exceeds page/image limits')
    return json.loads(result.stdout) if mode == 'inspect' else result.stdout


def safe_filename(filename):
    return Path((filename or 'document').replace('\\', '/')).name[:255]


def validate_extension(filename, mime):
    allowed = {'application/pdf': {'.pdf'}, 'image/jpeg': {'.jpg', '.jpeg'}, 'image/png': {'.png'}}
    if Path(filename).suffix.lower() not in allowed.get(mime, set()):
        raise ValueError('Filename extension does not match the document content')
