"""CSV / XLSX export helpers."""
import csv
import io
from datetime import datetime

from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill


def export_response(rows: list[dict], columns: list[tuple[str, str]], fmt: str, basename: str) -> Response:
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    if fmt == "xlsx":
        wb = Workbook()
        ws = wb.active
        ws.title = basename[:31]
        ws.append([label for _, label in columns])
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F3A5F")
        for r in rows:
            ws.append([_fmt(r.get(k)) for k, _ in columns])
        for i, (_, label) in enumerate(columns, start=1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = max(12, min(40, len(label) + 6))
        ws.freeze_panes = "A2"
        buf = io.BytesIO()
        wb.save(buf)
        return Response(buf.getvalue(),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{basename}-{stamp}.xlsx"'})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([label for _, label in columns])
    for r in rows:
        w.writerow([_fmt(r.get(k)) for k, _ in columns])
    # UTF-8 BOM so Excel opens Arabic text correctly
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{basename}-{stamp}.csv"'})


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    return v
