"""Stage 3: download the PDF and pull out the introduction and conclusion."""
import re
import shutil
import subprocess

import requests

from . import config, store

# A double-clicked .app runs with a bare PATH that has no Homebrew in it, so the
# binary is located rather than assumed.
PDFTOTEXT_FALLBACKS = ("/opt/homebrew/bin/pdftotext", "/usr/local/bin/pdftotext",
                       "/opt/local/bin/pdftotext")

HEAD_INTRO = re.compile(
    r"^[ \t]*(?:[IVX0-9]+[.)]?[ \t]*)?introduction[ \t]*$", re.I | re.M)
HEAD_CONC = re.compile(
    r"^[ \t]*(?:[IVX0-9]+[.)]?[ \t]*)?(?:conclusions?|concluding remarks|"
    r"(?:summary|discussion) and conclusions?|summary and outlook)[ \t]*$", re.I | re.M)
HEAD_REFS = re.compile(r"^[ \t]*(?:references|bibliography)[ \t]*$", re.I | re.M)
HEAD_NEXT = re.compile(r"^[ \t]*(?:[0-9]+\.[0-9.]*|[IVX]+\.)[ \t]+[A-Z][^\n]{2,80}$", re.M)


def pdftotext_bin() -> str:
    found = shutil.which("pdftotext")
    if found:
        return found
    for path in PDFTOTEXT_FALLBACKS:
        if shutil.which(path):
            return path
    raise RuntimeError(
        "pdftotext not found. Install poppler:  brew install poppler")


def pdf_text(rec: dict) -> str:
    arx = rec["arxiv"]
    dest = config.PDF_DIR / f"{arx['id']}.pdf"
    if not dest.exists() or dest.stat().st_size < 1000:
        resp = requests.get(arx["pdf_url"], timeout=120,
                            headers={"User-Agent": "LitDigest/1.0"})
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    raw = subprocess.run([pdftotext_bin(), "-q", str(dest), "-"],
                         capture_output=True, text=True, timeout=180).stdout
    return raw.replace("\r", "")


def _section(text: str, head: re.Pattern, last: bool = False) -> str:
    hits = list(head.finditer(text))
    if not hits:
        return ""
    m = hits[-1] if last else hits[0]
    body = text[m.end(): m.end() + config.EXCERPT_CHARS]
    nxt = HEAD_NEXT.search(body, 200)          # stop at the following numbered section
    return (m.group().strip() + "\n" + (body[:nxt.start()] if nxt else body)).strip()


def main_text(text: str) -> str:
    """The paper up to its reference list."""
    cut = list(HEAD_REFS.finditer(text))
    return text[:cut[-1].start()] if cut else text


def sections(text: str) -> dict:
    body = main_text(text)
    intro = _section(body, HEAD_INTRO)
    conc = _section(body, HEAD_CONC, last=True)
    if not intro:                               # unparsed layout: fall back to position
        intro = body[:config.EXCERPT_CHARS]
    if not conc:
        conc = body[-config.EXCERPT_CHARS:]
    return {"intro": intro, "conclusion": conc,
            "chars": len(intro) + len(conc), "pages_chars": len(text)}


def run(force: bool = False, limit: int | None = None) -> dict:
    counts = {"ok": 0, "failed": 0, "no_match": 0}
    todo = [r for r in store.all_records()
            if r.get("arxiv", {}).get("match_status") in config.RESOLVED
            and (force or not r.get("text"))]
    if limit:
        todo = todo[:limit]
    for rec in todo:
        try:
            text = sections(pdf_text(rec))
            store.update(rec["num"], lambda r: r.update(text=text))
            counts["ok"] += 1
            print(f"  [{rec['num']:>3}] {text['chars']:>6} chars  "
                  f"{rec['title'][:60]}", flush=True)
        except Exception as exc:
            store.update(rec["num"], lambda r: store.note_error(r, "fetch", exc))
            counts["failed"] += 1
            print(f"  [{rec['num']:>3}] FAIL {exc}", flush=True)
    counts["no_match"] = sum(1 for r in store.all_records()
                             if r.get("arxiv", {}).get("match_status") == "none")
    return counts
