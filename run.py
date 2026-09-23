#!/usr/bin/env python3
"""LitDigest: turn a spreadsheet of arXiv titles into a searchable digest.

Stages run in order and are resumable -- each skips papers it already finished:

    ./run.py ingest      spreadsheet   -> cache/papers/*.json
    ./run.py match       title         -> arXiv id, abstract, authors  (~3s/paper)
    ./run.py fetch       arXiv id      -> PDF intro + conclusion (optional; the app
                                       does this per paper on first click)
    ./run.py taxonomy    all titles    -> asks the model for its own clusters and
                                       writes cache/taxonomy.json, replacing the
                                       curated CLUSTERS in config.py  (1 Grok call)
    ./run.py topics      all titles    -> files every paper under a cluster (1 Grok call)
    ./run.py all         ingest + match + taxonomy + topics
    ./run.py warm        pre-generate glances so the grid is already full (optional)
    ./run.py pin N ID    force paper N to an arXiv id, when its title was changed
    ./run.py serve       the app, on http://127.0.0.1:8000
    ./run.py status      what is done, what failed, what is unmatched
"""
import argparse
import sys

from litdigest import arxiv, config, extract, generate, ingest, llm, sheet, store


def cmd_status(_args) -> None:
    recs = list(store.all_records())
    m = [r.get("arxiv", {}).get("match_status") for r in recs]
    print(f"source    {config.SOURCE_XLSX}")
    print(f"model     {config.XAI_MODEL} @ {config.XAI_BASE_URL}")
    print(f"papers    {len(recs)}")
    print(f"matched   {m.count('ok')} exact, {m.count('fuzzy')} fuzzy, "
          f"{m.count('pinned')} pinned by hand, {m.count('none')} unmatched, "
          f"{m.count(None)} not tried")
    print(f"text      {sum(1 for r in recs if r.get('text'))} papers with PDF text pulled")
    print(f"glances   {sum(1 for r in recs if r.get('glance'))}")
    print(f"deep      {sum(1 for r in recs if r.get('deep'))}")
    if config.TAXONOMY_FILE.exists():
        print("clusters  " + ", ".join(c["label"] for c in llm.taxonomy()))
    bad = [r for r in recs if r.get("errors")]
    if bad:
        print(f"\nerrors ({len(bad)}):")
        for r in bad[:20]:
            for e in r["errors"]:
                print(f"  [{r['num']:>3}] {e['stage']}: {e['msg'][:90]}")
    miss = [r for r in recs if r.get("arxiv", {}).get("match_status") == "none"]
    if miss:
        print(f"\nunmatched titles ({len(miss)}) -- check for typos or non-arXiv sources:")
        for r in miss:
            print(f"  [{r['num']:>3}] {r['title'][:88]}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("ingest", "match", "fetch", "taxonomy", "topics", "warm", "pin", "serve", "all",
                 "status", "models"):
        s = sub.add_parser(name)
        if name == "pin":
            s.add_argument("num", type=int)
            s.add_argument("arxiv_id")
        if name == "serve":
            s.add_argument("--port", type=int, default=8000)
        if name in ("match", "fetch", "warm", "all"):
            s.add_argument("--force", action="store_true",
                           help="redo papers that already have this stage")
            s.add_argument("--limit", type=int,
                           help="only process the first N outstanding papers")
    a = p.parse_args()
    force = getattr(a, "force", False)
    limit = getattr(a, "limit", None)

    if a.cmd == "status":
        return cmd_status(a)
    if a.cmd == "models":
        return print("\n".join(llm.models()))
    if a.cmd == "ingest":
        return print(f"ingested {ingest.run()} papers")
    if a.cmd == "match":
        print(arxiv.run(force, limit))
        return print(f"{sheet.sync_links()} arXiv links written to the spreadsheet")
    if a.cmd == "fetch":
        return print(extract.run(force, limit))
    if a.cmd == "taxonomy":
        return print("\n".join(f'{c["label"]}: {c["scope"]}' for c in llm.build_taxonomy()))
    if a.cmd == "topics":
        return print(llm.assign_topics())
    if a.cmd == "pin":
        if store.load(a.num) is None:
            return print(f"no paper {a.num}")
        found = arxiv.fetch_by_id(a.arxiv_id)

        def pin(rec):
            rec["arxiv"] = found
            rec.pop("text", None)
        store.update(a.num, pin)
        sheet.sync_links()
        return print(f"[{a.num}] pinned to {a.arxiv_id}: {found['title'][:70]}")
    if a.cmd == "warm":
        return print(generate.warm(limit, force))
    if a.cmd == "serve":
        import uvicorn
        print(f"LitDigest on http://127.0.0.1:{a.port}  (model: {config.XAI_MODEL})")
        return uvicorn.run("server:app", host="127.0.0.1", port=a.port, reload=False)
    if a.cmd == "all":
        print("== ingest");   print(f"ingested {ingest.run()} papers")
        print("== match");    print(arxiv.run(force, limit))
        print(f"{sheet.sync_links()} arXiv links written to the spreadsheet")
        print("== taxonomy"); llm.taxonomy()
        print("== topics");   print(llm.assign_topics())
        print("\nReady. Start the app with:  ./run.py serve")


if __name__ == "__main__":
    sys.exit(main())
