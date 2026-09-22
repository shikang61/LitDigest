"""One JSON file per paper in cache/papers/. Stages read it, add a key, write it back."""
import json
import os
import threading
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
    """Write through a temporary file and rename over the target.

    A truncating write that is interrupted -- the app quit, the machine slept --
    leaves half a JSON file behind, and one of those makes every later read of the
    library fail, so the grid never opens again. The rename is atomic, so a reader
    sees either the old record or the new one. The temporary name carries the
    process and thread in it because two stages can write the same paper at once.
    """
    dest = path_for(rec["num"])
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(rec, indent=2, ensure_ascii=False))
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def all_records() -> Iterator[dict]:
    for p in sorted(config.PAPER_DIR.glob("*.json")):
        yield json.loads(p.read_text())


def note_error(rec: dict, stage: str, msg: str) -> None:
    rec.setdefault("errors", [])
    rec["errors"] = [e for e in rec["errors"] if e["stage"] != stage]
    rec["errors"].append({"stage": stage, "msg": str(msg)[:500]})
