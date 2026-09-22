"""Streaming Grok calls behind the app.

Everything streams as tagged sections ([CLAIM], [TRICK], ...) rather than JSON so
the panel can fill in as the model writes, instead of waiting on a closing brace.
"""
import re

from . import config, latex, llm

SECTION = re.compile(r"^\[([A-Z][A-Z ]+)\]\s*$", re.M)

GLANCE_SYS = """You triage arXiv papers for a PhD researcher who will not read them in full.
You are the colleague who already read it and tells them straight whether it is worth an evening.

Rules:
- Be concrete and technical. Name the actual scheme, estimator, model or theorem.
- Quote the paper's own numbers.
- Never write filler like "this paper explores", "the authors investigate", "sheds light on".
- Never pad a weak paper. If it is incremental, say so.
- Be short. No sentence over 25 words. Cut every clause that is not load-bearing.
  One idea per sentence. No subordinate clauses stacked on qualifiers.
- Stay inside the length given for each section. Shorter is better than longer.
- Output ONLY the tagged sections below, in order, nothing before or after. No markdown."""

GLANCE_FMT = """[CLAIM]
One sentence, 25 words or fewer: the specific thing this paper claims is true or possible.
A claim, not a topic.
[SCORE]
A single integer 1-5. 5 = drop everything and read it. 1 = skip, nothing here for you.
[VERDICT]
Two sentences. First: read it or not, and why. Second: what to read (name the section,
theorem or figure) if they give it ten minutes.
[TRICK]
Two or three sentences, 60 words or fewer: the mechanism that makes it work. The idea needed
to re-derive the result. Not a restatement of the abstract.
[HOLDS UP]
One sentence: the weakest assumption or the thing left untested."""

DEEP_SYS = GLANCE_SYS.replace(
    "tells them straight whether it is worth an evening",
    "explains how it actually works, at the level of someone who will implement it")

DEEP_FMT = r"""[SETUP]
Two sentences: the standard result this paper departs from.
[MECHANISM]
Four to six sentences: how the method works, step by step. Where the difficulty is and how
they get past it. Specific about the mathematics, still short.
[EQUATION]
The single central equation, as LaTeX only -- no $ delimiters, no \begin{equation} wrapper,
no \label. If the source equations are supplied below, copy the relevant one verbatim,
preserving the author's macros. If none is supplied, write nothing after this tag.
[TERMS]
One symbol per line, formatted `symbol -- what it denotes`. Only symbols in the equation above.
[LIMITS]
Two or three sentences: the assumptions doing heavy lifting, and what was not tested.
[USE]
Two sentences: how this researcher would apply or extend it, concretely."""


def _context(rec: dict, *, full: bool) -> str:
    arx = rec.get("arxiv", {})
    text = rec.get("text", {})
    intro = text.get("intro", "")
    conc = text.get("conclusion", "")
    if not full:
        intro, conc = intro[:4500], conc[:3000]
    return f"""PAPER
Title: {arx.get('title') or rec['title']}
Authors: {', '.join(arx.get('authors', [])[:8]) or 'unknown'}
Year: {arx.get('year', 'unknown')}
arXiv categories: {', '.join(arx.get('categories', [])) or 'unknown'}

ABSTRACT
{arx.get('abstract', '(not available)')}

INTRODUCTION
{intro or '(not available)'}

CONCLUSION
{conc or '(not available)'}"""


def stream_glance(rec: dict):
    user = f"{_context(rec, full=False)}\n\nRespond in exactly this format:\n\n{GLANCE_FMT}"
    yield from llm.stream_parts(GLANCE_SYS, user, max_tokens=1100)


def stream_deep(rec: dict):
    eqs = rec.get("equations") or []
    block = ""
    if eqs:
        block = ("\n\nLATEX EQUATIONS FROM THE PAPER'S OWN SOURCE "
                 "(copy the central one verbatim into [EQUATION]):\n"
                 + "\n".join(f"{i + 1}. {e}" for i, e in enumerate(eqs)))
    user = f"{_context(rec, full=True)}{block}\n\nRespond in exactly this format:\n\n{DEEP_FMT}"
    yield from llm.stream_parts(DEEP_SYS, user, max_tokens=3000)


ASK_SYS = """You answer questions about one specific arXiv paper, for the researcher reading it.
Answer from the supplied text. If the text does not settle it, say so in one clause and then
give your best technical read, flagged as inference. Be short and concrete. No preamble."""


def stream_ask(rec: dict, question: str, history: list[dict] | None = None):
    prior = ""
    if history:
        prior = "\n\nEARLIER IN THIS CONVERSATION\n" + "\n".join(
            f"Q: {h['q']}\nA: {h['a']}" for h in history[-4:])
    user = f"{_context(rec, full=True)}{prior}\n\nQUESTION\n{question}"
    yield from llm.stream_parts(ASK_SYS, user, max_tokens=1200)


def expected_seconds(kind: str = "glance", default: float = 60.0) -> float:
    """Median time the last runs took, so the UI can size its progress bar."""
    from statistics import median

    from . import store
    seen = [r[kind]["seconds"] for r in store.all_records()
            if r.get(kind, {}).get("seconds")]
    return round(median(seen), 1) if seen else default


def parse(raw: str) -> dict:
    """Tagged text -> {'claim': ..., 'score': ..., ...}."""
    parts, keys = SECTION.split(raw), {}
    for i in range(1, len(parts), 2):
        keys[parts[i].strip().lower().replace(" ", "_")] = parts[i + 1].strip()
    if "score" in keys:
        m = re.search(r"\d", keys["score"])
        keys["score"] = int(m.group()) if m else None
    return keys


def prepare_equations(rec: dict) -> dict:
    """Fetch the arXiv source once, for verbatim equations and author macros."""
    aid = rec.get("arxiv", {}).get("id")
    if not aid or "equations" in rec:
        return rec
    rec["equations"] = latex.equations(aid)
    rec["macros"] = latex.macros(aid)
    return rec


def warm(limit: int | None = None, force: bool = False) -> dict:
    """Pre-generate glances in the background so the grid is populated before you browse.

    Optional: the app generates on click anyway. Worth running overnight on a big list.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from . import arxiv, extract, store

    todo = [r for r in store.all_records()
            if (force or not r.get("glance"))
            and r.get("arxiv", {}).get("match_status") in config.RESOLVED]
    if limit:
        todo = todo[:limit]

    def one(rec):
        if not rec.get("text"):
            rec["text"] = extract.sections(extract.pdf_text(rec))
            store.save(rec)
        raw = "".join(x for k, x in stream_glance(rec) if k == "say")
        parsed = parse(raw)
        parsed["raw"] = raw
        parsed["model"] = config.XAI_MODEL
        fresh = store.load(rec["num"])
        fresh["glance"] = parsed
        store.save(fresh)
        return parsed

    counts = {"ok": 0, "failed": 0}
    with ThreadPoolExecutor(max_workers=config.WORKERS) as pool:
        futures = {pool.submit(one, r): r for r in todo}
        for fut in as_completed(futures):
            rec = futures[fut]
            try:
                p = fut.result()
                counts["ok"] += 1
                print(f"  [{rec['num']:>3}] {p.get('score','?')}/5  "
                      f"{(p.get('claim') or '')[:70]}", flush=True)
            except Exception as exc:
                store.note_error(rec, "glance", exc)
                store.save(rec)
                counts["failed"] += 1
                print(f"  [{rec['num']:>3}] FAIL {str(exc)[:80]}", flush=True)
    return counts
