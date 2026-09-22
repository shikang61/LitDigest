#!/usr/bin/env python3
"""LitDigest app: reads the spreadsheet, serves the card grid, generates on click."""
import json
import time
import datetime as dt
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from litdigest import arxiv, config, extract, figures, generate, ingest, llm, sheet, store

WEB = Path(__file__).parent / "web"
app = FastAPI(title="LitDigest")
app.mount("/fig", StaticFiles(directory=config.FIG_DIR), name="fig")
# KaTeX ships with the app rather than off a CDN: the equations are the point of a
# deep read, and on a train they would otherwise degrade to raw LaTeX in silence.
app.mount("/vendor", StaticFiles(directory=WEB / "vendor"), name="vendor")


def _rec(num: int) -> dict:
    rec = store.load(num)
    if rec is None:
        raise HTTPException(404, f"no paper {num}")
    return rec


def _card(rec: dict) -> dict:
    arx = rec.get("arxiv", {})
    g = rec.get("glance", {})
    authors = arx.get("authors", [])
    return {
        "num": rec["num"],
        "title": arx.get("title") or rec["title"],
        "notes": rec.get("notes", ""),
        "topic": rec.get("topic", "Unclustered"),
        "starred": bool(rec.get("starred")),
        "year": arx.get("year", ""),
        "authors": (authors[0] + " et al." if len(authors) > 1
                    else (authors[0] if authors else "")),
        "arxiv_id": arx.get("id", ""),
        "abs_url": arx.get("abs_url", ""),
        "match": arx.get("match_status", ""),
        "claim": g.get("claim", ""),
        "score": g.get("score"),
        "has_glance": bool(g),
        "has_deep": bool(rec.get("deep")),
    }


def _events(make_parts, num: int, key: str, prep=None):
    """Relay one generation to the browser as SSE, then persist it.

    Three kinds of event reach the client: {"phase": ...} for the setup work,
    {"think": text} while the model reasons, {"t": text} as it writes the answer.
    """
    def gen():
        t0 = time.time()
        try:
            if prep is not None:
                yield f"data: {json.dumps({'phase': 'fetching the paper'})}\n\n"
                prep()
            rec = store.load(num)
            yield f"data: {json.dumps({'phase': 'reading', 'expected': generate.expected_seconds(key)})}\n\n"

            buf = []
            for kind, text in make_parts(rec):
                if kind == "think":
                    yield f"data: {json.dumps({'think': text})}\n\n"
                else:
                    buf.append(text)
                    yield f"data: {json.dumps({'t': text})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)[:300]})}\n\n"
            return

        raw = "".join(buf)
        parsed = generate.parse(raw)
        parsed.update(raw=raw, model=config.XAI_MODEL,
                      seconds=round(time.time() - t0, 1),
                      generated_at=dt.datetime.now().isoformat(timespec="seconds"))
        store.update(num, lambda r: r.update({key: parsed}))
        yield f"data: {json.dumps({'done': True, 'parsed': parsed})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


def _code_mtime() -> float:
    return max(p.stat().st_mtime
               for p in [Path(__file__), *Path(__file__).parent.glob("litdigest/*.py")])


# Python reads each module once, at start, so a server that has been up since
# before the code last changed is still running the old code -- a fix saved to
# disk does nothing until it restarts. The launcher asks, and restarts it.
STARTED_CODE = _code_mtime()


@app.get("/api/health")
def health():
    """Liveness, for the launcher waiting on the server to come up, and whether
    the code on disk has changed since this server started.

    It must stay cheap: /api/papers re-reads the spreadsheet and, on a fresh
    library, files every new paper under a cluster, which is a run of model calls.
    Polling that twice a second while the server starts is how you end up with
    several of those running at once.
    """
    return {"ok": True, "stale": _code_mtime() > STARTED_CODE}


@app.get("/api/papers")
def papers():
    """Always re-reads the spreadsheet, so rows added since last time show up."""
    ingest.run()
    recs = list(store.all_records())

    # a paper with no topic, or one filed under a category that no longer exists,
    # is refiled on open -- so editing the category list refiles the library
    labels = {c["label"] for c in llm.taxonomy()}
    fresh = [r["num"] for r in recs if r.get("topic") not in labels]
    if fresh:
        try:
            llm.assign_topics(only=fresh)
            recs = list(store.all_records())
        except Exception:
            pass          # they stay Unclustered; the app still opens
    return {"papers": [_card(r) for r in recs],
            "model": config.XAI_MODEL,
            "source": str(config.SOURCE_XLSX),
            "added": len(fresh)}


@app.post("/api/reload")
def reload_sheet():
    n = ingest.run()
    return {"ingested": n}


@app.get("/api/papers/{num}")
def paper(num: int):
    rec = _rec(num)
    return {"card": _card(rec),
            "abstract": rec.get("arxiv", {}).get("abstract", ""),
            "glance": rec.get("glance"),
            "deep": rec.get("deep"),
            "macros": rec.get("macros", {}),
            "figures": rec.get("figures", []),
            "chat": rec.get("chat", []),
            "ready": bool(rec.get("text")),
            "errors": rec.get("errors", [])}


@app.post("/api/papers/{num}/prepare")
def prepare(num: int):
    """Resolve on arXiv and pull the PDF text -- whatever is still missing."""
    rec = _rec(num)
    if rec.get("arxiv", {}).get("match_status") not in config.RESOLVED:
        found = arxiv.find(rec["title"])
        rec = store.update(num, lambda r: r.update(arxiv=found))
    if rec["arxiv"]["match_status"] == "none":
        raise HTTPException(422, "arXiv has no paper under this title")
    if not rec.get("text"):
        text = extract.sections(extract.pdf_text(rec))
        rec = store.update(num, lambda r: r.update(text=text))
    return {"ready": True, "chars": rec["text"]["chars"]}


@app.post("/api/papers/{num}/glance")
def glance(num: int):
    _rec(num)
    return _events(generate.stream_glance, num, "glance",
                   prep=lambda: prepare(num))


def _prep_deep(num: int) -> None:
    """The LaTeX source and the figures, both downloads, so merged in afterwards."""
    prepare(num)
    rec = generate.prepare_equations(store.load(num))
    if "figures" not in rec:
        rec["figures"] = figures.extract(rec["arxiv"]["id"])
    got = {k: rec[k] for k in ("equations", "macros", "figures") if k in rec}
    store.update(num, lambda r: r.update(got))


@app.post("/api/papers/{num}/deep")
def deep(num: int):
    _rec(num)
    return _events(generate.stream_deep, num, "deep", prep=lambda: _prep_deep(num))


@app.post("/api/papers/{num}/ask")
def ask(num: int, question: str = Body(..., embed=True)):
    rec = _rec(num)
    if not rec.get("text"):
        prepare(num)
        rec = _rec(num)
    history = rec.get("chat", [])
    buf = []

    def relay():
        for kind, piece in generate.stream_ask(rec, question, history):
            if kind == "think":
                yield f"data: {json.dumps({'think': piece})}\n\n"
                continue
            buf.append(piece)
            yield f"data: {json.dumps({'t': piece})}\n\n"
        turn = {"q": question, "a": "".join(buf)}
        store.update(num, lambda r: r.setdefault("chat", []).append(turn))
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(relay(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.post("/api/papers/{num}/note")
def note(num: int, text: str = Body(..., embed=True)):
    """Save a note and write it straight into the spreadsheet's Notes column."""
    _rec(num)
    if not sheet.set_note(num, text):
        raise HTTPException(422, "could not find this paper's row, or a Notes column, "
                                 "in the spreadsheet")
    store.update(num, lambda r: r.update(notes=text))
    return {"num": num, "notes": text}


@app.post("/api/papers/{num}/star")
def star(num: int, starred: bool = Body(..., embed=True)):
    """Star a paper, which fills its Title cell yellow in the spreadsheet."""
    _rec(num)
    if not sheet.set_star(num, starred):
        raise HTTPException(422, "could not find this paper's row in the spreadsheet")
    store.update(num, lambda r: r.update(starred=starred))
    return {"num": num, "starred": starred}


@app.post("/api/quit")
def quit_server():
    """Stop the server. The app detaches it, so there is no window to close."""
    import os
    import signal
    import threading

    threading.Timer(0.3, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    return {"stopping": True}


@app.get("/api/taxonomy")
def taxonomy():
    return {"clusters": llm.taxonomy()}
