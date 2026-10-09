import cv2
import numpy as np
from PIL import Image, ImageOps


def load_image(path):
    with Image.open(path) as image:
        return np.array(ImageOps.exif_transpose(image).convert('RGB'))


def candidates(image):
    """Retain the original; try contrast enhancement only for measured low contrast."""
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    warnings = []
    result = [('original', image)]
    if min(image.shape[:2]) < 600:
        warnings.append('Low-resolution image: inspect every recognized value.')
    if cv2.Laplacian(gray, cv2.CV_64F).var() < 45:
        warnings.append('Blur detected: OCR may omit or confuse characters.')
    if float(gray.std()) < 35:
        enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        result.append(('contrast', cv2.cvtColor(enhanced, cv2.COLOR_GRAY2RGB)))
        warnings.append('Low contrast: original and enhanced OCR results compared.')
    return result, warnings
