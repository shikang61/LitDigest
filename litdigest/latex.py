"""Pull real LaTeX equations out of a paper's arXiv source package.

pdftotext mangles maths, so an equation reconstructed from it is usually wrong.
The e-print tarball has the author's own LaTeX, which renders correctly.
"""
import io
import re
import tarfile

import requests

from . import config

EPRINT = "https://arxiv.org/e-print/{id}"
ENVS = r"(equation\*?|align\*?|gather\*?|multline\*?|eqnarray\*?)"
EQ_BLOCK = re.compile(r"\\begin\{" + ENVS + r"\}(.*?)\\end\{\1\}", re.S)
EQ_BRACKET = re.compile(r"\\\[(.*?)\\\]", re.S)
COMMENT = re.compile(r"(?<!\\)%.*$", re.M)
MAX_EQS = 40
MAX_EQ_CHARS = 420


def source_text(arxiv_id: str) -> str:
    """Concatenated .tex of the paper, or '' when arXiv has no source package."""
    cached = config.SRC_DIR / f"{arxiv_id}.tex"
    if cached.exists():
        return cached.read_text(errors="ignore")

    resp = requests.get(EPRINT.format(id=arxiv_id), timeout=90,
                        headers={"User-Agent": "LitDigest/1.0"})
    resp.raise_for_status()
    blob = resp.content

    texts = []
    try:
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            for m in tar.getmembers():
                if m.isfile() and m.name.endswith(".tex") and m.size < 4_000_000:
                    texts.append(tar.extractfile(m).read().decode("utf8", "ignore"))
    except tarfile.TarError:
        try:                                   # single uncompressed .tex is also served
            texts = [blob.decode("utf8", "ignore")]
        except Exception:
            texts = []

    text = "\n".join(t for t in texts if "\\" in t)
    if text:
        cached.write_text(text, errors="ignore")
    return text


def equations(arxiv_id: str) -> list[str]:
    try:
        text = COMMENT.sub("", source_text(arxiv_id))
    except Exception:
        return []
    found = [m.group(0) for m in EQ_BLOCK.finditer(text)]
    found += [m.group(0) for m in EQ_BRACKET.finditer(text)]
    out, seen = [], set()
    for eq in found:
        eq = re.sub(r"\s+", " ", eq).strip()
        if len(eq) > MAX_EQ_CHARS or eq in seen:
            continue
        seen.add(eq)
        out.append(eq)
        if len(out) >= MAX_EQS:
            break
    return out


NEWCMD = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand)\*?\s*\{?\s*(\\[A-Za-z@]+)\s*\}?"
    r"\s*(?:\[(\d)\])?\s*(?:\[[^\]]*\])?\s*\{", re.M)
DEF = re.compile(r"\\def\s*(\\[A-Za-z@]+)\s*\{", re.M)
DECLARE_OP = re.compile(r"\\DeclareMathOperator\*?\s*\{\s*(\\[A-Za-z@]+)\s*\}\s*\{([^}]*)\}")


def _balanced(text: str, start: int) -> str:
    """Body of the brace group that opens at text[start-1]."""
    depth, i = 1, start
    while i < len(text) and depth:
        if text[i] == "{" and text[i - 1] != "\\":
            depth += 1
        elif text[i] == "}" and text[i - 1] != "\\":
            depth -= 1
        i += 1
    return text[start:i - 1]


def macros(arxiv_id: str) -> dict:
    """Author-defined shorthands, in the form KaTeX's `macros` option expects."""
    try:
        text = COMMENT.sub("", source_text(arxiv_id))
    except Exception:
        return {}
    out = {}
    for pat in (NEWCMD, DEF):
        for m in pat.finditer(text):
            body = _balanced(text, m.end())
            if len(body) < 200:
                out[m.group(1)] = body
    for m in DECLARE_OP.finditer(text):
        out[m.group(1)] = r"\operatorname{%s}" % m.group(2)
    return out
