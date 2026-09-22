"""The two-way bits: notes typed in the app, and the yellow star on a title cell.

The spreadsheet stays the source of truth. Nothing else is ever written to it.
"""
import datetime as dt
import shutil
import threading

from openpyxl import load_workbook
from openpyxl.styles import PatternFill

from . import config

STAR_RGB = "FFFFFF00"                                   # the yellow already in the sheet
STAR_FILL = PatternFill(start_color=STAR_RGB, end_color=STAR_RGB, fill_type="solid")
CLEAR_FILL = PatternFill(fill_type=None)

_lock = threading.Lock()                                # writes are serialised
_backed_up = False


def is_starred(cell) -> bool:
    fill = cell.fill
    if not fill or fill.fill_type != "solid":
        return False
    try:
        return str(fill.start_color.rgb).upper().endswith("FFFF00")
    except (AttributeError, TypeError):
        return False


def columns(ws) -> dict:
    """{'Num': 2, 'Title': 3, ...} plus the header row index, or None if not a sheet we know."""
    from .ingest import header_row
    head = header_row(ws)
    if head is None:
        return {}
    cols = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(head, c).value
        if v is not None and str(v).strip():
            cols[str(v).strip().lower()] = c
    cols["_header"] = head
    return cols


def _row_for(ws, cols: dict, num: int) -> int | None:
    num_col = cols.get("num")
    if not num_col:
        return None
    for row in range(cols["_header"] + 1, ws.max_row + 1):
        try:
            if int(ws.cell(row, num_col).value) == num:
                return row
        except (TypeError, ValueError):
            continue
    return None


def _backup_once() -> None:
    """One copy of the untouched spreadsheet, the first time this run writes to it."""
    global _backed_up
    if _backed_up:
        return
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    src = config.SOURCE_XLSX
    shutil.copy2(src, config.BACKUP_DIR / f"{src.stem}-{stamp}{src.suffix}")
    _backed_up = True


def _write(num: int, column: str, apply) -> bool:
    """False, and nothing written, if the paper's row or the column is missing."""
    with _lock:
        wb = load_workbook(config.SOURCE_XLSX)
        ws = wb[wb.sheetnames[0]]
        cols = columns(ws)
        row = _row_for(ws, cols, num)
        if row is None or column not in cols:
            return False
        _backup_once()
        apply(ws, cols, row)
        wb.save(config.SOURCE_XLSX)
        return True


def set_note(num: int, text: str) -> bool:
    def apply(ws, cols, row):
        # not ws.cell(row, col, None): openpyxl ignores a None value there, so a
        # deleted note would stay in the spreadsheet
        ws.cell(row, cols["notes"]).value = text or None
    return _write(num, "notes", apply)


def set_star(num: int, starred: bool) -> bool:
    def apply(ws, cols, row):
        ws.cell(row, cols["title"]).fill = STAR_FILL if starred else CLEAR_FILL
    return _write(num, "title", apply)
