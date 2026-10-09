"""Untrusted file parsing in a time/memory-bounded process. Never executes PDF actions."""
import io
import json
import sys
import warnings
import pymupdf
from PIL import Image, ImageOps


def limits():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
    except ImportError:
        pass  # Windows: wall-clock and pixel/byte limits still apply; Docker enforces memory.


def inspect_file(path, max_pages, max_pixels):
    with open(path, 'rb') as stream:
        magic = stream.read(16)
    if magic.startswith(b'%PDF-'):
        with pymupdf.open(path) as doc:
            if doc.needs_pass or doc.is_repaired or not 1 <= len(doc) <= max_pages:
                raise ValueError('Encrypted, damaged or over-limit PDF')
            for page in doc:
                if page.rect.width <= 0 or page.rect.height <= 0 or page.rect.width * page.rect.height > max_pixels:
                    raise ValueError('PDF page dimensions exceed limits')
                # Force content parsing; scripts/actions and attachments are never invoked.
                page.get_text('text')
            return {'content_type': 'application/pdf', 'page_count': len(doc)}
    Image.MAX_IMAGE_PIXELS = max_pixels
    warnings.simplefilter('error', Image.DecompressionBombWarning)
    with Image.open(path) as image:
        if image.format not in ('JPEG', 'PNG') or image.width * image.height > max_pixels or getattr(image, 'n_frames', 1) != 1:
            raise ValueError('Unsupported image or image dimensions exceed limits')
        mime = Image.MIME[image.format]
        image.verify()
    with Image.open(path) as image:
        image.load()
    return {'content_type': mime, 'page_count': 1}


def render(path, page_number, max_pixels):
    with open(path, 'rb') as stream:
        is_pdf = stream.read(5) == b'%PDF-'
    if is_pdf:
        with pymupdf.open(path) as doc:
            page = doc[page_number - 1]
            scale = min(1.5, (max_pixels / (page.rect.width * page.rect.height)) ** 0.5)
            return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False, annots=False).tobytes('png')
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert('RGB')
        image.thumbnail((1800, 2400))
        output = io.BytesIO(); image.save(output, format='PNG'); return output.getvalue()


if __name__ == '__main__':
    limits()
    try:
        mode, path, arg1, arg2 = sys.argv[1:]
        if mode == 'inspect':
            sys.stdout.write(json.dumps(inspect_file(path, int(arg1), int(arg2))))
        else:
            sys.stdout.buffer.write(render(path, int(arg1), int(arg2)))
    except Exception:
        sys.stderr.write('File is corrupted, unsupported, encrypted, or exceeds parser limits.')
        sys.exit(2)
