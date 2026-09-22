"""Grok (xAI) calls: build the topic taxonomy, file papers under it, stream digests."""
import json
import os
import re

from openai import OpenAI

from . import config, store

_client = None


def client() -> OpenAI:
    global _client
    if _client is None:
        key = os.environ.get("XAI_API_KEY")
        if not key:
            raise SystemExit(
                "XAI_API_KEY is not set. Put it in a .env file at the repo root "
                "(XAI_API_KEY=xai-...) or export it in your shell.")
        _client = OpenAI(api_key=key, base_url=config.XAI_BASE_URL)
    return _client


def models() -> list[str]:
    return sorted(m.id for m in client().models.list().data)


def _json_call(system: str, user: str, max_tokens: int = 1600,
               model: str | None = None) -> dict:
    resp = client().chat.completions.create(
        model=model or config.XAI_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
        temperature=0.2,
    )
    body = resp.choices[0].message.content or ""
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", body, re.S)       # model wrapped it in prose/fences
        if not m:
            raise
        return json.loads(m.group())


# --- taxonomy -------------------------------------------------------------

TAXONOMY_SYS = (
    "You organise research libraries. You reply with JSON only, no commentary.")

TAXONOMY_USER = """Below are {n} arXiv paper titles from one researcher's reading list.

Group them into 8-12 topic clusters that carve the list at its natural joints.
Clusters must be mutually exclusive, cover every title, and be named in the
researcher's own vocabulary (not generic words like "Mathematics" or "Other").

Return JSON: {{"clusters": [{{"label": "<2-5 words>", "scope": "<one line saying what belongs here>"}}]}}

TITLES
{titles}"""


def build_taxonomy() -> list[dict]:
    titles = [r["title"] for r in store.all_records()]
    data = _json_call(
        TAXONOMY_SYS,
        TAXONOMY_USER.format(n=len(titles),
                             titles="\n".join(f"- {t}" for t in titles)),
        max_tokens=4000, model=config.XAI_UTIL_MODEL)
    clusters = data["clusters"]
    config.TAXONOMY_FILE.write_text(json.dumps(clusters, indent=2, ensure_ascii=False))
    return clusters


def taxonomy() -> list[dict]:
    if config.TAXONOMY_FILE.exists():
        return json.loads(config.TAXONOMY_FILE.read_text())
    return config.CLUSTERS


def stream_parts(system: str, user: str, max_tokens: int = 1500):
    """Yield ("think", text) while the model reasons, then ("say", text) as it writes.

    A reasoning model is silent for most of a minute before its first answer token,
    so the reasoning stream is what the progress display is built on.
    """
    resp = client().chat.completions.create(
        model=config.XAI_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        max_tokens=max_tokens,
        temperature=0.3,
        stream=True,
    )
    for chunk in resp:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        thinking = getattr(delta, "reasoning_content", None)
        if thinking:
            yield "think", thinking
        if delta.content:
            yield "say", delta.content


TOPIC_SYS = "You sort papers into given clusters. JSON only, no commentary."


def assign_topics(only: list[int] | None = None) -> dict:
    """File titles under a cluster, so the grid is filterable before anything has
    been generated. `only` restricts it to newly added papers."""
    clusters = taxonomy()
    recs = list(store.all_records())
    if only is not None:
        keep = set(only)
        recs = [r for r in recs if r["num"] in keep]
    if not recs:
        return {"assigned": 0, "total": 0}
    labels = "\n".join(f'- {c["label"]}: {c["scope"]}' for c in clusters)

    got = {}
    for i in range(0, len(recs), 50):
        batch = recs[i:i + 50]
        listing = "\n".join(f'{r["num"]}. {r["title"]}' for r in batch)
        data = _json_call(
            TOPIC_SYS,
            f"""Assign every paper below to exactly one cluster.

CLUSTERS
{labels}

PAPERS
{listing}

When a paper spans two clusters, file it by its own contribution, not its subject
matter: a new learning method applied to plasma is AI, a plasma result that happens
to use a trained model is Fusion, and a numerical scheme for a plasma system is
Numerics. Market papers go to Finance unless the method is statistical physics.

Return JSON: {{"assignments": {{"<paper number>": "<cluster label, verbatim>"}}}}
Every paper number must appear exactly once.""",
            max_tokens=4000, model=config.XAI_UTIL_MODEL)
        got.update(data.get("assignments", {}))

    # the model tends to echo "label: scope", so match on the part before the colon
    valid = {c["label"].lower(): c["label"] for c in clusters}
    for rec in recs:
        raw = (got.get(str(rec["num"])) or "").split(":")[0].strip().lower()
        rec["topic"] = valid.get(raw, "Unclustered")
        store.save(rec)
    return {"assigned": sum(1 for r in recs if r.get("topic") != "Unclustered"),
            "total": len(recs)}
