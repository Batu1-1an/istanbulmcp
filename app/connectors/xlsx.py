"""Small, dependency-free XLSX table reader for bounded official snapshots."""
from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree

CELL_REF_RE = re.compile(r"([A-Z]+)([0-9]+)")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _column_number(reference: str) -> int:
    match = CELL_REF_RE.fullmatch(reference.upper())
    if not match:
        return 0
    value = 0
    for char in match.group(1):
        value = value * 26 + (ord(char) - 64)
    return value - 1


def _cell_text(cell: ElementTree.Element, shared: list[str]) -> str:
    kind = cell.attrib.get("t", "")
    value = next((child for child in cell if _local_name(child.tag) == "v"), None)
    if kind == "inlineStr":
        inline = next((child for child in cell if _local_name(child.tag) == "is"), None)
        return "" if inline is None else "".join(inline.itertext()).strip()
    if value is None:
        return ""
    raw = "".join(value.itertext()).strip()
    if kind == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return ""
    if kind == "b":
        return "1" if raw == "1" else "0"
    return raw


def read_first_sheet_rows(content: bytes, *, max_rows: int = 1000, max_cells: int = 20000) -> list[list[str]]:
    """Read the first worksheet as rectangular-ish rows, without formulas or macros.

    The caller still has to validate headers and values. Only cell values are
    returned; formulas, styles, hyperlinks and external relationships are ignored.
    """
    if not content or len(content) > 8 * 1024 * 1024:
        raise ValueError("XLSX payload is empty or too large")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
            if "xl/workbook.xml" not in names:
                raise ValueError("XLSX has no workbook")
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                for item in root:
                    if _local_name(item.tag) == "si":
                        shared.append("".join(item.itertext()).strip())
            sheets = sorted(
                name for name in names
                if name.startswith("xl/worksheets/") and name.endswith(".xml")
            )
            if not sheets:
                raise ValueError("XLSX has no worksheet")
            root = ElementTree.fromstring(archive.read(sheets[0]))
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError) as exc:
        raise ValueError("Malformed XLSX payload") from exc

    rows: list[list[str]] = []
    cells = 0
    for row_node in root.iter():
        if _local_name(row_node.tag) != "row":
            continue
        if len(rows) >= max_rows:
            raise ValueError("XLSX row limit exceeded")
        values: dict[int, str] = {}
        for cell in list(row_node):
            if _local_name(cell.tag) != "c":
                continue
            cells += 1
            if cells > max_cells:
                raise ValueError("XLSX cell limit exceeded")
            column = _column_number(cell.attrib.get("r", ""))
            if column < 0 or column > 100:
                raise ValueError("XLSX column is outside the supported range")
            values[column] = _cell_text(cell, shared)
        if values:
            width = max(values) + 1
            rows.append([values.get(index, "") for index in range(width)])
    if not rows:
        raise ValueError("XLSX worksheet has no rows")
    return rows
