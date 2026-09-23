"""Stage 2: resolve a bare title to an arXiv entry (id, authors, year, abstract)."""
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher

from . import config, store

API = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom"}
_last_call = 0.0

# words too common to narrow an arXiv title search
STOP = {"a", "an", "the", "of", "for", "and", "or", "in", "on", "to", "with",
        "via", "from", "by", "its", "using", "under", "new", "novel", "study"}


def normalise(title: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", title.lower()).split())


def _content(title: str) -> set:
    return {w for w in normalise(title).split() if w not in STOP and len(w) > 2}


def _score(clean: str, candidate: str) -> tuple[float, float]:
    """(character similarity, share of the sheet's words the candidate contains).

    Papers get retitled between arXiv versions -- words reordered, a subtitle
    promoted, a qualifier added -- so character similarity alone misses them.
    Word containment catches those without matching unrelated papers.
    """
    ratio = SequenceMatcher(None, clean, normalise(candidate)).ratio()
    mine = _content(clean)
    overlap = len(mine & _content(candidate)) / len(mine) if mine else 0.0
    return ratio, overlap


def _get(url: str) -> str:
    """The API's answer at url, raising on an HTTP error.

    Not requests: export.arxiv.org refuses its connections with 406 Not Acceptable,
    whatever headers they carry, while the standard library and curl get through.
    Only a response arXiv has cached slips past, so every new title search failed
    and each new paper was filed as not on arXiv.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "LitDigest/1.0"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8")


def _query(search: str, max_results: int = 8) -> list[dict]:
    global _last_call
    wait = config.ARXIV_DELAY - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    url = f"{API}?{urllib.parse.urlencode({'search_query': search, 'max_results': max_results})}"
    try:
        text = _get(url)
    finally:
        _last_call = time.time()
    root = ET.fromstring(text)

    out = []
    for e in root.findall("a:entry", NS):
        raw_id = e.findtext("a:id", "", NS)
        pdf = next((l.get("href") for l in e.findall("a:link", NS)
                    if l.get("title") == "pdf"), None)
        out.append({
            "id": raw_id.rsplit("/", 1)[-1],
            "title": " ".join(e.findtext("a:title", "", NS).split()),
            "abstract": " ".join(e.findtext("a:summary", "", NS).split()),
            "authors": [a.findtext("a:name", "", NS) for a in e.findall("a:author", NS)],
            "published": e.findtext("a:published", "", NS),
            "categories": [c.get("term") for c in e.findall("a:category", NS)],
            "pdf_url": pdf or raw_id.replace("/abs/", "/pdf/"),
            "abs_url": raw_id,
        })
    return out


def find(title: str) -> dict:
    """Return the best arXiv entry for a title, with a match_status of ok/fuzzy/none."""
    clean = normalise(title)
    words = clean.split()
    attempts = [f'ti:"{clean}"', f'all:"{clean}"']
    if len(words) > 9:                       # sheet titles are sometimes truncated
        attempts.append('ti:"%s"' % " ".join(words[:9]))
    # phrase search fails on titles carrying version numbers or odd punctuation,
    # so fall back to the distinctive words joined by AND
    content = [w for w in words if w not in STOP and len(w) > 2][:6]
    if content:
        attempts.append(" AND ".join(f"ti:{w}" for w in content))
        attempts.append(" AND ".join(f"all:{w}" for w in content))
    # last resort for a retitled paper: only its three rarest-looking words,
    # searched across title and abstract
    rare = sorted(set(w for w in words if w not in STOP and len(w) > 2),
                  key=len, reverse=True)[:3]
    if len(rare) == 3:
        attempts.append(" AND ".join(f"all:{w}" for w in rare))

    best, best_score, best_overlap = None, 0.0, 0.0
    answered, error = False, None
    for search in attempts:
        try:
            entries = _query(search)
        except Exception as exc:
            error = exc
            continue
        answered = True
        for e in entries:
            score, overlap = _score(clean, e["title"])
            # a truncated sheet title should still match its full arXiv title
            if normalise(e["title"]).startswith(clean[:60]):
                score = max(score, 0.93)
            if (score, overlap) > (best_score, best_overlap):
                best, best_score, best_overlap = e, score, overlap
        if best_score >= config.MATCH_STRONG:
            break

    if not answered:
        # arXiv never answered, which says nothing about whether it has the paper;
        # recording "none" would file it as not on arXiv
        raise error

    accepted = best_score >= config.MATCH_FUZZY or best_overlap >= config.MATCH_WORDS
    if best is None or not accepted:
        return {"match_status": "none", "match_score": round(best_score, 3),
                "word_overlap": round(best_overlap, 3),
                "candidate": best["title"] if best else None}
    best = dict(best)
    best["match_score"] = round(best_score, 3)
    best["word_overlap"] = round(best_overlap, 3)
    best["match_status"] = "ok" if best_score >= config.MATCH_STRONG else "fuzzy"
    best["year"] = best["published"][:4]
    return best


def fetch_by_id(arxiv_id: str) -> dict:
    """Take an arXiv id as given, for a paper whose title search cannot find it."""
    root = ET.fromstring(_get(f"{API}?id_list={urllib.parse.quote(arxiv_id)}"))
    entry = root.find("a:entry", NS)
    if entry is None:
        raise SystemExit(f"arXiv has no entry {arxiv_id}")
    raw_id = entry.findtext("a:id", "", NS)
    pdf = next((l.get("href") for l in entry.findall("a:link", NS)
                if l.get("title") == "pdf"), None)
    return {
        "id": raw_id.rsplit("/", 1)[-1],
        "title": " ".join(entry.findtext("a:title", "", NS).split()),
        "abstract": " ".join(entry.findtext("a:summary", "", NS).split()),
        "authors": [x.findtext("a:name", "", NS) for x in entry.findall("a:author", NS)],
        "published": entry.findtext("a:published", "", NS),
        "year": entry.findtext("a:published", "", NS)[:4],
        "categories": [c.get("term") for c in entry.findall("a:category", NS)],
        "pdf_url": pdf or raw_id.replace("/abs/", "/pdf/"),
        "abs_url": raw_id,
        "match_status": "pinned",
        "match_score": 1.0,
    }


def run(force: bool = False, limit: int | None = None) -> dict:
    counts = {"ok": 0, "fuzzy": 0, "none": 0, "skipped": 0}
    todo = [r for r in store.all_records()
            if force or not r.get("arxiv", {}).get("match_status")]
    if limit:
        todo = todo[:limit]
    for rec in todo:
        try:
            found = find(rec["title"])
        except Exception as exc:                       # network/parse failure
            store.update(rec["num"], lambda r: store.note_error(r, "match", exc))
            continue
        counts[found["match_status"]] += 1
        store.update(rec["num"], lambda r: r.update(arxiv=found))
        print(f"  [{rec['num']:>3}] {found['match_status']:<5} "
              f"{found.get('id','-'):<14} {rec['title'][:60]}", flush=True)
    counts["skipped"] = sum(1 for _ in store.all_records()) - len(todo)
    return counts
