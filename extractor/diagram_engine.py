"""
extractor/diagram_engine.py
────────────────────────────
Extracts genuine diagram images from a PDF page region.
Always opens the PDF fresh to avoid orphaned PyMuPDF page objects.
"""
import fitz
import uuid
import os
import numpy as np

DIAGRAM_DIR = "temp/diagrams"
os.makedirs(DIAGRAM_DIR, exist_ok=True)


def _is_likely_diagram(bbox: tuple, page_rect) -> bool:
    """Reject small, full-width, or header/footer images."""
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0

    if w < 80 or h < 80:
        return False
    # Full-width decorative strip
    if w > page_rect.width * 0.85 and h < 100:
        return False
    # Header / footer band
    if y0 < 40 or y1 > page_rect.height - 40:
        return False
    # Extreme aspect ratios (thin slivers)
    ar = w / h if h else 0
    return 0.2 < ar < 5.0


def _has_content(pix) -> bool:
    """Return True if the image is not nearly blank (var > threshold)."""
    raw = pix.tobytes("raw", "L")
    arr = np.frombuffer(raw, dtype=np.uint8)
    return float(np.var(arr)) > 80.0


def extract_diagrams(
    pdf_path: str,
    page_index_label: str,
    page_no: int,
    clip_rect_tuple: tuple | None = None,
) -> list[dict]:
    """
    Extract diagrams from one page (or clip region).

    Returns list of dicts:
    {
        "bbox":   (x0, y0, x1, y1),
        "path":   str,
        "width":  float,
        "height": float,
    }
    """
    diagrams = []
    doc      = fitz.open(pdf_path)

    try:
        page = doc[page_no]
        clip = fitz.Rect(clip_rect_tuple) if clip_rect_tuple else page.rect

        for block in page.get_text("dict")["blocks"]:
            if block["type"] != 1:   # 1 = image block
                continue

            bbox = block["bbox"]

            # Skip images outside the clip region
            if clip_rect_tuple:
                if bbox[0] < clip.x0 - 5 or bbox[2] > clip.x1 + 5:
                    continue

            if not _is_likely_diagram(bbox, page.rect):
                continue

            try:
                pix = page.get_pixmap(clip=fitz.Rect(bbox), dpi=150)

                if not _has_content(pix):
                    continue

                name = f"{page_index_label}_{uuid.uuid4().hex[:6]}.png"
                path = os.path.join(DIAGRAM_DIR, name)
                pix.save(path)

                diagrams.append({
                    "bbox":   bbox,
                    "path":   path,
                    "width":  bbox[2] - bbox[0],
                    "height": bbox[3] - bbox[1],
                })
            except Exception as e:
                print(f"  [diagram_engine] block error: {e}")

    finally:
        doc.close()

    return diagrams
