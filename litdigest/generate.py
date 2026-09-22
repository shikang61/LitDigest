"""Streaming Grok calls behind the app.

Everything streams as tagged sections ([CLAIM], [KEY POINTS], ...) rather than JSON so
the panel can fill in as the model writes, instead of waiting on a closing brace.
"""
import re

from . import config, extract, latex, llm

SECTION = re.compile(r"^\[([A-Z][A-Z ]+)\]\s*$", re.M)

GLANCE_SYS = """You are the friend in the lab who reads everything and explains it over coffee:
relaxed, direct, a bit playful, and always right about the science. Write so that a curious
person with no background in this field would follow it: informal, in layman's terms. The
reader will not read this paper in full. They should get the key ideas on the first read,
without having to untangle a single sentence.

Voice:
- Direct. Say the thing in the first few words. No warm-up, no "this paper explores",
  "the authors investigate", "sheds light on", "it is worth noting".
- Layman. Explain complex ideas the way you would to a smart friend outside science:
  everyday words, the intuition before the detail, a comparison to something familiar.
  Avoid jargon. Swap it for plain words wherever you can.
- Keep the key words. The handful of terms that really matter -- the method's name, the
  central concept, the thing someone would search for -- stay in, but each one comes
  with a plain explanation right beside it the first time: "**entropy stability** (the
  scheme can never create disorder out of nothing, so it cannot blow up)".
- Plain sentences. One idea per sentence; no stacked clauses, no nested parentheses, no
  chains of technical nouns. Two clear sentences beat one tangled one.
- Never stingy. Brevity is not the goal, understanding is. Use as many sentences as it
  takes for the point to land, and never cut an explanation short to save words -- but
  no padding either: every sentence has to teach the reader something.
- Fun, but earned. A quick analogy, a surprising number, or a light aside is welcome when
  it makes the idea click. Never a joke that costs accuracy.

Explaining well:
- Problem before solution. Say what goes wrong without this idea, or why the question is
  hard, before saying what the paper does about it. A fix means nothing until the reader
  can see what it fixes.
- Intuition, then mechanism, then precision. First the mental picture or the comparison to
  something familiar; then how it actually works, in plain words; then the exact version.
- Show the logic. Join the steps with "because", "so", "which means", "but" -- the reader
  should see why each thing follows, not receive a list of facts.
- Concrete over abstract. "Improves accuracy" explains nothing; "cuts the error from 8% to
  2% on the ITER-like test case" does. Use the paper's own example or number wherever it
  has one.
- Say why it matters: what it lets someone do, or understand, that they could not before.
- Active voice: "the new flux kills the spurious oscillations", not "spurious oscillations
  are suppressed".

Staying scientific:
- Every statement must be backed by the paper. Never invent a result, a number or a
  comparison. If the paper does not say, do not guess; if something is your inference,
  say "probably" or "looks like".
- Be concrete: name the actual method, model, estimator or theorem, and quote the paper's
  own numbers.
- Be honest: if the result is incremental or the evidence is thin, say so plainly.
  Chill does not mean hype.
- Use maths only where it is the clearest way to say something, and say in words what
  it means. Write every piece of mathematics as LaTeX between \\( and \\):
  \\(C(|h| + \\sigma)^{3/2}\\), \\(\\partial_t u\\), \\(O(h^4)\\). Use LaTeX commands,
  not unicode symbols, inside them. Never leave a bare exponent, subscript or Greek
  letter outside them. Never use dollar signs as maths delimiters -- a dollar sign means
  money. Where words are clearer than symbols, use words.
- Outside the maths, a dash is "-", never "--", and names are written plainly
  (Hamilton-Jacobi, not Hamilton--Jacobi).

Format:
- Give each section as bullet points, one per line, each starting with "- ".
- Open every bullet with the point itself, in its first sentence, so a reader can skim
  the openings and stop. Then explain it properly: why it holds, what it means, and where
  the paper shows it -- the figure (by number), the test case, the number. A simple point
  can stay short; a hard one can run to a short paragraph. Let the idea set the length.
- In each bullet mark the one to three words that carry the point by wrapping them in
  **double asterisks** -- the method's name, the number that settles it. Never a whole
  clause.
- The tagged sections below are the structure: the app lays them out itself, so use no
  headings, tables or other markdown beyond the bullets and the **marks** described above.
- Output ONLY the tagged sections below, in order, nothing before or after."""

GLANCE_FMT = """[CLAIM]
One sentence, 25 words or fewer: the specific thing this paper claims is true or possible.
A claim, not a topic.
[SCORE]
A single integer 1-5. 5 = drop everything and read it. 1 = skip, nothing here for you.
[KEY POINTS]
Three to six bullets: the key ideas the paper is trying to convey, drawn from
the whole paper, not just its abstract. Each one is a key finding, a novel method, a new
application, or an improvement on the existing way of doing something -- say which by how
you state it. One idea per bullet, the most important first. Explain each well enough that
someone outside the field would understand what it is, why it matters, and what evidence in
the paper backs it."""

DEEP_SYS = GLANCE_SYS.replace(
    "They should get the key ideas on the first read",
    "They asked how it actually works, so give the full detail -- every step someone would\n"
    "need to implement it -- but still in plain words, one step at a time, and they should\n"
    "still follow it on the first read")

DEEP_FMT = r"""[SETUP]
Two bullets: the standard approach this paper departs from, explained well enough that the
reader knows what it does, and what goes wrong with it here -- the specific failure, with
the paper's own example if it gives one.
[MECHANISM]
Four to eight bullets: how the method works, where the difficulty is, and how they get
past it, in order. Each bullet says what that step achieves and why it is needed -- what
would go wrong without it -- then the intuition, then the maths that does it with each
symbol said in words, then -- where the paper shows it -- the figure or test case, named by
number ("Figure 3") so the figure can be placed beside the bullet. Be specific about the
maths. A hard step deserves a short paragraph; split it into plain sentences rather than
cram it into one.
[EQUATION]
The single central equation, as LaTeX only -- no $ delimiters, no \begin{equation} wrapper,
no \label. If the source equations are supplied below, copy the relevant one verbatim,
preserving the author's macros. If none is supplied, write nothing after this tag.
[TERMS]
One symbol per line, formatted `\\(symbol\\) -- what it denotes`, with the symbol in the
same \\( \\) delimiters as everywhere else. Only symbols that appear in the equation above.
[LIMITS]
Two or three bullets: the assumptions doing the heavy lifting, and what went untested.
Each one names the limitation first, then why it matters, then where it would show --
the figure, the regime, the case they never ran. Name figures by number.
[USE]
Two or three bullets: how this researcher would apply or extend it, concretely, and the
next step for going further -- the follow-up question worth asking this paper, or the
paper, method or topic to read next."""


def _whole_paper(rec: dict) -> str:
    """Header, abstract and the full text up to the references."""
    arx = rec.get("arxiv", {})
    body = extract.main_text(extract.pdf_text(rec))
    if len(body) > config.FULLTEXT_CHARS:      # a thesis or a book: keep both ends
        keep = config.FULLTEXT_CHARS - config.EXCERPT_CHARS
        body = (body[:keep] + "\n\n[... the middle is left out for length ...]\n\n"
                + body[-config.EXCERPT_CHARS:])
    return f"""PAPER
Title: {arx.get('title') or rec['title']}
Authors: {', '.join(arx.get('authors', [])[:8]) or 'unknown'}
Year: {arx.get('year', 'unknown')}
arXiv categories: {', '.join(arx.get('categories', [])) or 'unknown'}

ABSTRACT
{arx.get('abstract', '(not available)')}

FULL TEXT
{body}"""


def stream_glance(rec: dict):
    user = f"{_whole_paper(rec)}\n\nRespond in exactly this format:\n\n{GLANCE_FMT}"
    yield from llm.stream_parts(GLANCE_SYS, user, max_tokens=4000)


def stream_deep(rec: dict):
    eqs = rec.get("equations") or []
    block = ""
    if eqs:
        block = ("\n\nLATEX EQUATIONS FROM THE PAPER'S OWN SOURCE "
                 "(copy the central one verbatim into [EQUATION]):\n"
                 + "\n".join(f"{i + 1}. {e}" for i, e in enumerate(eqs)))
    user = f"{_whole_paper(rec)}{block}\n\nRespond in exactly this format:\n\n{DEEP_FMT}"
    yield from llm.stream_parts(DEEP_SYS, user, max_tokens=6000)


ASK_SYS = """You are the friend in the lab who reads everything, answering questions about one
specific arXiv paper for the researcher reading it: relaxed, direct, a bit playful, and always
right about the science. Answer in the first sentence, informally and in layman's terms.
Plain sentences and everyday words; avoid jargon, but keep the key terms that matter, each
with a plain explanation beside it the first time. A quick analogy is welcome when it makes
the idea click. If the concept is advanced, explain it in steps: the problem first, then the
intuition, then how it works.
Answer from the supplied text. If the text does not settle it, say so in one clause and then
give your best technical read, flagged as inference. Stay on the question, but take the room
it needs to land: explain the why, not just the what, and use a concrete example or number
from the paper where one helps. No padding and no preamble. A short list with "- " is fine where it
organises the answer, but no headings or tables. Write mathematics as LaTeX between \\( and \\).
Where it would help, end with one follow-up question worth asking next."""


def stream_ask(rec: dict, question: str, history: list[dict] | None = None):
    prior = ""
    if history:
        prior = "\n\nEARLIER IN THIS CONVERSATION\n" + "\n".join(
            f"Q: {h['q']}\nA: {h['a']}" for h in history[-4:])
    user = f"{_whole_paper(rec)}{prior}\n\nQUESTION\n{question}"
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
