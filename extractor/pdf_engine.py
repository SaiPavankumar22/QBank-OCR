"""
extractor/pdf_engine.py
───────────────────────
Converts PDF pages to images, detecting layout per-page.

Layout types
────────────
  single      – single-column or inline-answer style (coaching PDFs, books)
  two_column  – classic two-column exam paper (UPSC / APSC / SSC)
  answer_key  – page is a Q.NO → ANS table
"""
import fitz  # PyMuPDF
import os

TEMP_IMG_DIR = "temp/page_images"
os.makedirs(TEMP_IMG_DIR, exist_ok=True)


# ── Layout detection ──────────────────────────────────────────────────────────

def _full_text(page) -> str:
    """Extract all text from a page as a single lowercase string."""
    return page.get_text("text").lower()


def _text_blocks(page):
    return [b for b in page.get_text("dict")["blocks"] if b.get("type") == 0]


def detect_layout(page) -> str:
    """
    Returns 'two_column' | 'answer_key' | 'single'.
    """
    txt = _full_text(page)

    # ── Answer key heuristics ─────────────────────────────────────────────────
    answer_key_signals = [
        "ans_key", "answer key", "provisional answer",
        "q. no.", "q.no.", "ans key",
    ]
    signal_count = sum(1 for s in answer_key_signals if s in txt)
    if signal_count >= 2:
        return "answer_key"

    # ── Two-column heuristic ──────────────────────────────────────────────────
    blocks   = _text_blocks(page)
    if len(blocks) < 4:
        return "single"

    mid_x    = page.rect.width / 2
    x_coords = [b["bbox"][0] for b in blocks]
    left     = sum(1 for x in x_coords if x < mid_x - 60)
    right    = sum(1 for x in x_coords if x > mid_x + 60)

    # Need substantial content on both sides
    if left >= 3 and right >= 3 and min(left, right) / max(left, right) > 0.35:
        return "two_column"

    return "single"


# ── Rendering ─────────────────────────────────────────────────────────────────

def _render(page, clip_rect=None, dpi=200) -> str:
    """
    Render page (or a clip region) to PNG.
    Returns the saved file path.
    """
    i = page.number
    if clip_rect:
        side = "L" if clip_rect[0] == 0 else "R"
        path = f"{TEMP_IMG_DIR}/page_{i}_{side}.png"
        pix  = page.get_pixmap(clip=fitz.Rect(clip_rect), dpi=dpi)
    else:
        path = f"{TEMP_IMG_DIR}/page_{i}.png"
        pix  = page.get_pixmap(dpi=dpi)

    pix.save(path)
    return path


def pdf_to_images(pdf_path: str, dpi: int = 200) -> list[dict]:
    """
    Convert every PDF page to one or more images.

    Returns a list of dicts:
    {
        "index":      str           – unique label, e.g. "0", "1_L", "1_R"
        "image_path": str           – path to saved PNG
        "page_no":    int           – 0-based page index
        "clip":       tuple | None  – (x0, y0, x1, y1) or None
        "layout":     str           – 'single' | 'two_column' | 'answer_key'
    }
    """
    doc     = fitz.open(pdf_path)
    results = []

    for i, page in enumerate(doc):
        layout = detect_layout(page)

        if layout == "two_column":
            mid_x = page.rect.width / 2
            h, w  = page.rect.height, page.rect.width

            results.append({
                "index":      f"{i}_L",
                "image_path": _render(page, (0, 0, mid_x, h), dpi),
                "page_no":    i,
                "clip":       (0, 0, mid_x, h),
                "layout":     layout,
            })
            results.append({
                "index":      f"{i}_R",
                "image_path": _render(page, (mid_x, 0, w, h), dpi),
                "page_no":    i,
                "clip":       (mid_x, 0, w, h),
                "layout":     layout,
            })
        else:
            # single column OR answer_key → full page
            results.append({
                "index":      str(i),
                "image_path": _render(page, None, dpi),
                "page_no":    i,
                "clip":       None,
                "layout":     layout,
            })

    doc.close()
    return results
