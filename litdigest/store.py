"""One JSON file per paper in cache/papers/. Stages read it, add a key, write it back."""
import json
from typing import Iterator

from . import config


def path_for(num: int):
    return config.PAPER_DIR / f"{num:04d}.json"


def load(num: int) -> dict | None:
    p = path_for(num)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def save(rec: dict) -> None:
    path_for(rec["num"]).write_text(json.dumps(rec, indent=2, ensure_ascii=False))


def all_records() -> Iterator[dict]:
    for p in sorted(config.PAPER_DIR.glob("*.json")):
        yield json.loads(p.read_text())


def note_error(rec: dict, stage: str, msg: str) -> None:
    rec.setdefault("errors", [])
    rec["errors"] = [e for e in rec["errors"] if e["stage"] != stage]
    rec["errors"].append({"stage": stage, "msg": str(msg)[:500]})
