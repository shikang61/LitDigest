"""Tests for the parts that are easy to break and awkward to notice: the title
matcher, the tagged-section parser, header detection, and the spreadsheet export.

No network and no model calls -- everything here runs offline.
"""
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from litdigest import arxiv, generate, ingest  # noqa: E402


# --- title matching -------------------------------------------------------

def test_normalise_strips_punctuation_and_case():
    assert arxiv.normalise("Grad--Shafranov: Shape Effects!") == "grad shafranov shape effects"


def test_exact_title_scores_one():
    t = "Entropy stable finite difference schemes"
    ratio, overlap = arxiv._score(arxiv.normalise(t), t)
    assert ratio == pytest.approx(1.0)
    assert overlap == pytest.approx(1.0)


def test_retitled_paper_is_caught_by_word_overlap():
    """arXiv v3 reordered the title; character similarity alone would miss it."""
    sheet = arxiv.normalise(
        "Analytical Grad-Shafranov equilibria for prescribed boundaries: shape effects")
    live = "Shape effects and Shafranov shift reversal in analytical Grad--Shafranov equilibria"
    ratio, overlap = arxiv._score(sheet, live)
    assert ratio < 0.72, "character similarity is not what rescues this"
    assert overlap >= 0.6


def test_unrelated_paper_does_not_match():
    sheet = arxiv.normalise("Entropy stable schemes for the Euler equations")
    ratio, overlap = arxiv._score(sheet, "Deep learning for protein folding")
    assert ratio < 0.72 and overlap < 0.75


def test_stopwords_excluded_from_overlap():
    assert "the" not in arxiv._content("the theory of the thing")
    assert "theory" in arxiv._content("the theory of the thing")


# --- the tagged-section format --------------------------------------------

GLANCE = """[CLAIM]
A claim in one line.
[SCORE]
2
[VERDICT]
Not worth it. Read section 3.
[TRICK]
The mechanism.
[HOLDS UP]
One caveat.
"""


def test_parse_splits_every_section():
    out = generate.parse(GLANCE)
    assert out["claim"] == "A claim in one line."
    assert out["score"] == 2
    assert out["holds_up"] == "One caveat."


def test_parse_handles_a_multi_word_tag():
    assert "holds_up" in generate.parse(GLANCE)


def test_parse_of_a_half_written_stream():
    """The panel renders while the model is still writing, so partial text must parse."""
    partial = GLANCE[:GLANCE.index("[TRICK]")]
    out = generate.parse(partial)
    assert out["claim"] and out["score"] == 2
    assert "trick" not in out


def test_parse_survives_a_missing_score():
    out = generate.parse("[CLAIM]\nx\n[SCORE]\n\n[VERDICT]\ny\n")
    assert out["score"] is None


def test_body_text_is_not_mistaken_for_a_tag():
    out = generate.parse("[CLAIM]\nSee [EQ] in the paper.\n[SCORE]\n3\n")
    assert "See [EQ] in the paper." == out["claim"]


# --- spreadsheet handling -------------------------------------------------

def _sheet(tmp_path, header_row=3):
    wb = Workbook()
    ws = wb.active
    ws.title = "LitFeed"
    for i, name in enumerate(("Num", "Title", "Notes"), start=2):
        ws.cell(header_row, i, name)
    ws.cell(header_row + 1, 2, 1)
    ws.cell(header_row + 1, 3, "A Paper About Things")
    ws.cell(header_row + 1, 4, "my note")
    path = tmp_path / "sheet.xlsx"
    wb.save(path)
    return path


def test_header_row_is_found_below_blank_rows(tmp_path):
    ws = load_workbook(_sheet(tmp_path))["LitFeed"]
    assert ingest.header_row(ws) == 3


def test_header_row_found_at_the_top(tmp_path):
    ws = load_workbook(_sheet(tmp_path, header_row=1))["LitFeed"]
    assert ingest.header_row(ws) == 1


def test_header_row_missing_returns_none(tmp_path):
    wb = Workbook(); wb.active["B2"] = "nothing useful"
    p = tmp_path / "bad.xlsx"; wb.save(p)
    assert ingest.header_row(load_workbook(p).active) is None


def test_ingest_reads_titles_and_notes(tmp_path, monkeypatch):
    from litdigest import config, store
    monkeypatch.setattr(config, "SOURCE_XLSX", _sheet(tmp_path))
    monkeypatch.setattr(config, "PAPER_DIR", tmp_path / "papers")
    (tmp_path / "papers").mkdir()
    assert ingest.run() == 1
    rec = store.load(1)
    assert rec["title"] == "A Paper About Things"
    assert rec["notes"] == "my note"


def test_changing_a_title_discards_its_cached_work(tmp_path, monkeypatch):
    from litdigest import config, store
    monkeypatch.setattr(config, "SOURCE_XLSX", _sheet(tmp_path))
    monkeypatch.setattr(config, "PAPER_DIR", tmp_path / "papers")
    (tmp_path / "papers").mkdir()
    ingest.run()
    rec = store.load(1)
    rec.update(arxiv={"id": "x"}, glance={"claim": "stale"})
    store.save(rec)

    wb = load_workbook(config.SOURCE_XLSX)
    wb["LitFeed"].cell(4, 3, "A Different Paper")
    wb.save(config.SOURCE_XLSX)
    ingest.run()

    after = store.load(1)
    assert after["title"] == "A Different Paper"
    assert "arxiv" not in after and "glance" not in after
