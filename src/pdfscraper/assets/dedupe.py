"""dedupe.py - Visual deduplication of extracted assets."""

import imagehash
from PIL import Image


def compute_phash(img: Image.Image) -> str:
    """Compute perceptual hash of a Pillow image."""
    return str(imagehash.phash(img))
