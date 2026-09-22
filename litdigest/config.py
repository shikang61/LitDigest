"""Paths, model and tuning knobs. Override via env or a .env file at repo root."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip("'\""))


_load_dotenv()

CACHE = ROOT / "cache"
PAPER_DIR = CACHE / "papers"
PDF_DIR = CACHE / "pdf"
SRC_DIR = CACHE / "src"
BACKUP_DIR = CACHE / "backup"
FIG_DIR = CACHE / "fig"
TAXONOMY_FILE = CACHE / "taxonomy.json"

# The buckets papers are filed under. Edit cache/taxonomy.json to change them for
# an existing library, or edit this list and delete that file to start over.
CLUSTERS = [
    {"label": "Fusion",
     "scope": "Tokamaks, stellarators, MHD, gyrokinetics, pedestal and exhaust, "
              "plasma control, disruptions, equilibria, and fusion device codes."},
    {"label": "Numerics",
     "scope": "Discretisations and solvers: entropy-stable and structure-preserving "
              "schemes, DG and finite volume, time integrators, Krylov methods, "
              "preconditioners, and numerical analysis of PDEs."},
    {"label": "AI",
     "scope": "Papers whose contribution is the learning method itself: neural "
              "networks, PINNs, neural operators, transformers, surrogates, and "
              "machine learning theory."},
    {"label": "Finance",
     "scope": "Pricing, portfolio optimisation, volatility modelling, execution, "
              "market microstructure, risk, and trading strategies."},
    {"label": "Econophysics",
     "scope": "Markets treated with the tools of statistical physics: scaling laws, "
              "long memory, entropy and information measures, agent-based and "
              "network models of markets."},
]

SOURCE_XLSX = Path(os.environ.get(
    "LITDIGEST_XLSX", Path.home() / "Desktop" / "LitFeed Literature.xlsx"))

XAI_BASE_URL = os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1")
XAI_MODEL = os.environ.get("GROK_MODEL", "grok-4.7")
# Bulk classification wants speed, not reasoning: a reasoning model spends its
# whole budget thinking about 182 titles and never reaches the JSON.
XAI_UTIL_MODEL = os.environ.get("GROK_UTIL_MODEL", "grok-4.20-0309-non-reasoning")

ARXIV_DELAY = 3.0       # arXiv asks for >=3s between API calls
MATCH_STRONG = 0.90     # title similarity accepted outright
MATCH_FUZZY = 0.72      # below this, character similarity alone is not enough
MATCH_WORDS = 0.75      # ...but containing this share of the title's words is
RESOLVED = ("ok", "fuzzy", "pinned")   # match states a paper can be read from
EXCERPT_CHARS = 9000    # per section (intro, conclusion) sent to the model
WORKERS = 6             # parallel Grok calls

for _d in (PAPER_DIR, PDF_DIR, SRC_DIR, FIG_DIR):
    _d.mkdir(parents=True, exist_ok=True)
