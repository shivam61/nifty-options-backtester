from __future__ import annotations

import io
import zipfile
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path

from lxml import etree


XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def excel_serial_to_date(value: str) -> datetime.date:
    base = datetime(1899, 12, 30)
    return (base + timedelta(days=float(value))).date()


def cell_column(cell_ref: str) -> str:
    chars: list[str] = []
    for ch in cell_ref:
        if ch.isalpha():
            chars.append(ch)
        else:
            break
    return "".join(chars)


def iter_xlsx_rows(xlsx_bytes: bytes, sheet_path: str = "xl/worksheets/sheet1.xml") -> Iterable[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as archive:
        with archive.open(sheet_path) as sheet_file:
            context = etree.iterparse(sheet_file, events=("end",), tag=f"{XLSX_NS}row")
            for _, row in context:
                values: dict[str, str] = {}
                for cell in row:
                    ref = cell_column(cell.get("r", ""))
                    value_node = cell.find(f"{XLSX_NS}v")
                    inline_node = cell.find(f"{XLSX_NS}is")
                    if inline_node is not None:
                        text = "".join(inline_node.itertext())
                    elif value_node is not None:
                        text = value_node.text or ""
                    else:
                        text = ""
                    values[ref] = text
                row.clear()
                yield values


def read_embedded_xlsx_from_zip(path: str | Path) -> bytes:
    with zipfile.ZipFile(path) as archive:
        return archive.read(archive.namelist()[0])
