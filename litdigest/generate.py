"""Streaming Grok calls behind the app.

Everything streams as tagged sections ([CLAIM], [KEY POINTS], ...) rather than JSON so
the panel can fill in as the model writes, instead of waiting on a closing brace.
"""
import re

from . import config, extract, latex, llm

SECTION = re.compile(r"^\[([A-Z][A-Z ]+)\]\s*$", re.M)

GLANCE_SYS = """You write the note a well-read colleague passes along about a paper the reader has
no time for, as if explaining it to a smart friend from outside the field: plain words,
your own phrasing, only what matters.
They want the gist in under a minute, so say what matters and stop.

Write the way a person talks when they know the subject. Let sentences lean on each other
with "so", "but" or "which is why", and vary their length; a run of short one-fact
sentences sounds mechanical, and so does one sentence carrying four clauses. The reader is
smart but outside this subfield, so prefer plain words to jargon. Keep the few terms that
matter, like the method's name or the thing someone would search for, and let the sentence
carry what they mean instead of stopping to define each one. Give the one number that
settles a point and leave the rest of the table alone. Leave detail out rather than squeeze
it in: one point made plainly beats three in shorthand. If the result is modest or the
evidence thin, say so plainly.

Some habits give machine-written text away. Stay clear of them:
- bullets that all open the same way, above all a bolded term followed by "is"
- contrasts built as "X, not Y", "not X but Y" or "it's not just X, it's Y"
- warm-ups and wrap-ups: "this paper explores", "the key insight", "the real move",
  "in short", "the takeaway", "overall"
- crucial, key, novel, robust, leverage, delve, landscape, notably, pivotal, seamless,
  underscores, sheds light, paves the way
- coined nicknames, forced jokes, and analogies that need explaining themselves
- a colon or dash where a sentence belongs, and lists of three for the rhythm

You are not limited to the paper. Use what you know about the field, and any web search
notes that come with it, wherever they help: how the work compares with what people already
use, how it was received, whether later papers backed it up. When something comes from
elsewhere, say where the way a person would ("a 2023 follow-up by Chen found...") and leave
out how you found it. Never credit the paper with a number it does not report, and do not
guess. No links or citation markers.

Maths:
- Use maths only where it is the clearest way to say something, and say in words what
  it means. Write every piece of mathematics as LaTeX between \\( and \\):
  \\(C(|h| + \\sigma)^{3/2}\\), \\(\\partial_t u\\), \\(O(h^4)\\). Use LaTeX commands,
  not unicode symbols, inside them. Never leave a bare exponent, subscript or Greek
  letter outside them. Never use dollar signs as maths delimiters -- a dollar sign means
  money. Where words are clearer than symbols, use words.
- Outside the maths, a dash is "-", never "--", and names are written plainly
  (Hamilton-Jacobi, not Hamilton--Jacobi).

Format:
- Sections that ask for bullets get one per line, each starting with "- ". The others are
  plain lines.
- Put the point of a bullet in its first sentence so the reader can skim, but open each
  bullet in its own way.
- If one phrase in a bullet is what the eye should land on, usually a result or a number,
  you may wrap it in **double asterisks**. At most one per bullet, often none, and never
  the opening words.
- The tagged sections below are the structure: the app lays them out itself, so use no
  headings, tables or other markdown beyond the bullets and the **marks** described above.
- Output ONLY the tagged sections below, in order, nothing before or after."""

GLANCE_FMT = """[CLAIM]
One sentence of 20 words or fewer: what the paper shows or makes possible. State the claim
itself rather than its topic.
[SCORE]
A single integer 1-5. 5 = drop everything and read it. 1 = skip, nothing here for you.
[KEY POINTS]
Three or four bullets of one or two sentences each, under 40 words per bullet, most
important first. Between them the reader should learn what is new and whether the evidence
holds up, plus where the work sits in its field if you know."""

DEEP_SYS = GLANCE_SYS.replace(
    "They want the gist in under a minute, so say what matters and stop.",
    "They asked how it actually works, so take them through the method one step at a time,\n"
    "still plainly and without padding, and keep every bullet under 60 words.")

DEEP_FMT = r"""[SETUP]
One or two bullets: the usual way of doing this, and what goes wrong with it here, with the
paper's own example if it gives one.
[MECHANISM]
Three to five bullets, one step of the method each, in order. Two or three sentences per
bullet, under 60 words: what the step does and why it is needed, then the maths that does
it, with each symbol said in words. If a figure shows the step, mention it by number
("Figure 3") so the app can place it beside the bullet.
[EQUATION]
The single central equation, as LaTeX only -- no $ delimiters, no \begin{equation} wrapper,
no \label. If the source equations are supplied below, copy the relevant one verbatim,
preserving the author's macros. If none is supplied, write nothing after this tag.
[TERMS]
One symbol per line, formatted `\\(symbol\\) -- what it denotes`, with the symbol in the
same \\( \\) delimiters as everywhere else. Only symbols that appear in the equation above.
[LIMITS]
Two bullets: the assumption doing the most work, and what went untested, each with where
it would show.
[USE]
Two bullets: how the reader could apply or extend this, and what to read or ask next. Name
the actual paper, method or code, from what you know or the web notes."""

SEARCH_SYS = """You look things up for a researcher about to read the paper below. Search the web
two or three times at most, then write plain notes of no more than 150 words on what you
found, naming papers, authors and years. Report only what the searches turned up. No links."""

SEARCH_PAPER = ("Look for what the paper cannot say about itself: how it has been received, "
                "later work that built on it or challenged it, and how it compares with the "
                "methods people actually use.")


def _about(rec: dict) -> str:
    """Title, authors and abstract: enough to search on."""
    arx = rec.get("arxiv", {})
    return f"""PAPER
Title: {arx.get('title') or rec['title']}
Authors: {', '.join(arx.get('authors', [])[:8]) or 'unknown'}
Year: {arx.get('year', 'unknown')}
arXiv categories: {', '.join(arx.get('categories', [])) or 'unknown'}

ABSTRACT
{arx.get('abstract', '(not available)')}"""


def _whole_paper(rec: dict) -> str:
    """Header, abstract and the full text up to the references."""
    body = extract.main_text(extract.pdf_text(rec))
    if len(body) > config.FULLTEXT_CHARS:      # a thesis or a book: keep both ends
        keep = config.FULLTEXT_CHARS - config.EXCERPT_CHARS
        body = (body[:keep] + "\n\n[... the middle is left out for length ...]\n\n"
                + body[-config.EXCERPT_CHARS:])
    return f"{_about(rec)}\n\nFULL TEXT\n{body}"


def _web_notes(rec: dict, look_for: str):
    """Search the web first, on the abstract alone, and hand the reading what turned up.
    Yields each search as ("think", ...) for the progress display."""
    try:
        notes = yield from llm.web_search(SEARCH_SYS, f"{_about(rec)}\n\n{look_for}")
    except Exception as exc:                   # the paper alone still makes a digest
        yield "think", f" The web search failed ({str(exc)[:80]}), so reading the paper alone. "
        return ""
    notes = notes.strip()
    return f"\n\nWEB SEARCH NOTES (from outside the paper)\n{notes}" if notes else ""


def stream_glance(rec: dict):
    notes = yield from _web_notes(rec, SEARCH_PAPER)
    user = f"{_whole_paper(rec)}{notes}\n\nRespond in exactly this format:\n\n{GLANCE_FMT}"
    yield from llm.stream_parts(GLANCE_SYS, user, max_tokens=4000)


def stream_deep(rec: dict):
    notes = yield from _web_notes(rec, SEARCH_PAPER)
    eqs = rec.get("equations") or []
    block = ""
    if eqs:
        block = ("\n\nLATEX EQUATIONS FROM THE PAPER'S OWN SOURCE "
                 "(copy the central one verbatim into [EQUATION]):\n"
                 + "\n".join(f"{i + 1}. {e}" for i, e in enumerate(eqs)))
    user = f"{_whole_paper(rec)}{notes}{block}\n\nRespond in exactly this format:\n\n{DEEP_FMT}"
    yield from llm.stream_parts(DEEP_SYS, user, max_tokens=6000)


ASK_SYS = """You have read this paper closely and are answering a colleague's questions about it.
Answer in the first sentence, then add only what they need to trust or use the answer, in
under 100 words unless the question needs steps. Plain words, keeping the terms that matter.
The paper comes first, but you are not limited to it. Use what you know about the field and
any web search notes that come with the paper, and say where something comes from the way a
person would ("a 2023 follow-up by Chen found..."). Do not guess.
Write like a person: no preamble or wrap-up, no "not X but Y" contrasts, none of crucial,
key, novel, robust or delve, and no closing offer or question. No headings, tables, links or
citation markers; a short list with "- " is fine where the answer really is a list. Write
mathematics as LaTeX between \\( and \\)."""


def stream_ask(rec: dict, question: str, history: list[dict] | None = None):
    look_for = (f"Their question: {question}\n"
                "Search only if answering it needs something from outside the paper.")
    notes = yield from _web_notes(rec, look_for)
    prior = ""
    if history:
        prior = "\n\nEARLIER IN THIS CONVERSATION\n" + "\n".join(
            f"Q: {h['q']}\nA: {h['a']}" for h in history[-4:])
    user = f"{_whole_paper(rec)}{notes}{prior}\n\nQUESTION\n{question}"
    yield from llm.stream_parts(ASK_SYS, user, max_tokens=2500)


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

    from . import extract, store

    todo = [r for r in store.all_records()
            if (force or not r.get("glance"))
            and r.get("arxiv", {}).get("match_status") in config.RESOLVED]
    if limit:
        todo = todo[:limit]

    def one(rec):
        if not rec.get("text"):
            text = extract.sections(extract.pdf_text(rec))
            rec = store.update(rec["num"], lambda r: r.update(text=text))
        raw = "".join(x for k, x in stream_glance(rec) if k == "say")
        parsed = parse(raw)
        parsed["raw"] = raw
        parsed["model"] = config.XAI_MODEL
        store.update(rec["num"], lambda r: r.update(glance=parsed))
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
                store.update(rec["num"], lambda r: store.note_error(r, "glance", exc))
                counts["failed"] += 1
                print(f"  [{rec['num']:>3}] FAIL {str(exc)[:80]}", flush=True)
    return counts
