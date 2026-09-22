"""Crop each figure out of a PDF.

Locating the caption is easy; finding where the figure starts is not, because the
axis labels inside a vector plot are themselves text blocks. So the figure region
is taken from the drawing and image objects that sit above the caption, not from
the gap between text blocks.
"""
import re

import fitz

from . import config

CAPTION = re.compile(r"^\s*fig(?:ure)?\.?\s*\d+[.:)]?\s", re.I)
MAX_FIGS = 8
MIN_HEIGHT = 60      # pt
MIN_WIDTH = 80
PAD = 4
ZOOM = 2.0


def _graphics(page) -> list[fitz.Rect]:
    rects = [fitz.Rect(d["rect"]) for d in page.get_drawings()]
    for im in page.get_images(full=True):
        try:
            rects.append(fitz.Rect(page.get_image_bbox(im)))
        except (ValueError, RuntimeError):      # image placed via an unusual xref
            pass
    return [r for r in rects if r.is_valid and not r.is_empty]


def extract(arxiv_id: str) -> list[dict]:
    pdf = config.PDF_DIR / f"{arxiv_id}.pdf"
    if not pdf.exists():
        return []

    out = []
    with fitz.open(pdf) as doc:
        for pno, page in enumerate(doc):
            blocks = sorted((b for b in page.get_text("blocks") if b[6] == 0),
                            key=lambda b: b[1])
            caps = [b for b in blocks if CAPTION.match(" ".join(b[4].split()))]
            if not caps:
                continue
            gfx = _graphics(page)
            floor = page.rect.y0                # nothing above the previous caption
            for cap in caps:
                cap_top = cap[1]
                band = [r for r in gfx if r.y1 <= cap_top + 2 and r.y0 >= floor - 2]
                floor = cap[3]
                if not band:
                    continue
                region = band[0]
                for r in band[1:]:
                    region |= r
                # axis labels and tick text belong to the figure too
                for b in blocks:
                    tb = fitz.Rect(b[:4])
                    if tb.y1 <= cap_top + 2 and tb.y0 >= region.y0 - 12 \
                            and tb.x0 >= region.x0 - 40 and tb.x1 <= region.x1 + 40:
                        region |= tb
                region = region + (-PAD, -PAD, PAD, PAD)
                region &= page.rect
                if region.height < MIN_HEIGHT or region.width < MIN_WIDTH:
                    continue
                name = f"{arxiv_id}_p{pno + 1}_{len(out)}.png"
                page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), clip=region).save(
                    config.FIG_DIR / name)
                out.append({"file": name, "page": pno + 1,
                            "caption": " ".join(cap[4].split())[:400]})
                if len(out) >= MAX_FIGS:
                    return out
    return out
