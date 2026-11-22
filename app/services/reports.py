"""Отчёт для руководства: PDF (reportlab) и Excel (openpyxl)."""

import io
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.db.models import Pair, Program, User
from app.services.dashboard import dashboard, diagnosis, periods_of

FONTS = Path(__file__).resolve().parent.parent / "web" / "static" / "fonts"
PARTS = {
    "sum": "Сводка и ключевые показатели",
    "pairs": "Карточки пар",
    "signals": "Сигналы и прогноз",
    "actions": "Действия и эффект",
}


def collect(db: Session, program: Program, user: User, period: str, dept: str | None) -> dict:
    """Данные отчёта: дашборд на последний месяц и карточки пар."""
    months = periods_of(db, program)
    d = dashboard(db, program, user, months[-1], dept)
    cards = []
    for p in d["pairs"]:
        pair = db.get(Pair, p["id"])
        cards.append(diagnosis(db, program, pair, user))
    hist = []
    if period == "all":
        for m in months:
            dm = dashboard(db, program, user, m, dept)
            hist.append(
                {
                    "month": dm["months"][months.index(m)]["full"],
                    "attn": len(dm["alerts"]),
                    "kpis": dm["kpis"],
                }
            )
    return {"d": d, "cards": cards, "hist": hist, "program": program.name}


def _fonts() -> tuple[str, str]:
    try:
        pdfmetrics.registerFont(TTFont("DejaVu", str(FONTS / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONTS / "DejaVuSans-Bold.ttf")))
        return "DejaVu", "DejaVu-Bold"
    except Exception:  # noqa: BLE001
        return "Helvetica", "Helvetica-Bold"


def pdf(data: dict, parts: set[str]) -> bytes:
    """Отчёт в PDF."""
    reg, bold = _fonts()
    st = {
        "h1": ParagraphStyle("h1", fontName=bold, fontSize=18, leading=22, spaceAfter=6),
        "h2": ParagraphStyle(
            "h2",
            fontName=bold,
            fontSize=13,
            leading=17,
            spaceBefore=10,
            spaceAfter=4,
            textColor=colors.HexColor("#0A7CD6"),
        ),
        "p": ParagraphStyle("p", fontName=reg, fontSize=9.5, leading=13),
        "s": ParagraphStyle("s", fontName=reg, fontSize=8, leading=11, textColor=colors.HexColor("#5B6478")),
    }
    d = data["d"]
    out: list = [
        Paragraph(f"Пульс адаптации · {data['program']}", st["h1"]),
        Paragraph(f"{d['tag'].capitalize()} · сформирован {date.today():%d.%m.%Y}", st["s"]),
        Spacer(1, 6),
    ]

    def table(rows: list[list], widths: list[float]) -> Table:
        t = Table([[Paragraph(str(c), st["p"]) for c in r] for r in rows], colWidths=widths, repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF1F6")),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E3E6EC")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return t

    if "sum" in parts:
        out += [
            Paragraph("Сводка", st["h2"]),
            Paragraph(f"<b>{d['headline']}.</b> {d['sub']}", st["p"]),
            Spacer(1, 4),
        ]
        out.append(
            table(
                [["Показатель", "Значение", "Пояснение"]]
                + [[k["label"], k["value"], k["note"]] for k in d["kpis"]],
                [60 * mm, 30 * mm, 85 * mm],
            )
        )
        if d["program"]["box"]:
            out += [
                Spacer(1, 4),
                Paragraph(f"<b>{d['program']['box']['title']}.</b> {d['program']['box']['text']}", st["p"]),
            ]
        if data["hist"]:
            out += [
                Spacer(1, 4),
                table(
                    [["Месяц", "Пар в зоне внимания"]]
                    + [[h["month"], h["kpis"][0]["value"]] for h in data["hist"]],
                    [60 * mm, 60 * mm],
                ),
            ]
    if "signals" in parts:
        out.append(Paragraph("Сигналы и прогноз", st["h2"]))
        rows = [["Пара", "Тип", "Что происходит"]] + [[a["pair"], a["type"], a["why"]] for a in d["alerts"]]
        out.append(
            table(rows, [18 * mm, 45 * mm, 112 * mm])
            if len(rows) > 1
            else Paragraph("Сигналов нет.", st["p"])
        )
    if "pairs" in parts:
        out.append(Paragraph("Карточки пар", st["h2"]))
        rows = [["Пара", "Подразделение", "Индекс", "Состояние", "Главные штрафы", "Прогноз |Δ|"]]
        for c in data["cards"]:
            if c.get("empty"):
                continue
            pen = ", ".join(f"{x['name'].lower()} −{x['v']}" for x in c["contrib"][:3]) or "нет"
            f = c["sig"]["forecast"]
            rows.append(
                [c["code"], c["dept"], c["health"], c["st"]["label"], pen, "—" if f is None else f"{f:.2f}"]
            )
        out.append(table(rows, [16 * mm, 32 * mm, 16 * mm, 32 * mm, 58 * mm, 21 * mm]))
    if "actions" in parts:
        out.append(Paragraph("Действия и эффект", st["h2"]))
        rows = [["Пара", "Действие", "Статус", "Эффект"]]
        for c in data["cards"]:
            for a in c.get("actions", []):
                rows.append([c["code"], a["title"], a["status_ru"], (a.get("effect") or {}).get("text", "—")])
        out.append(
            table(rows, [16 * mm, 60 * mm, 28 * mm, 71 * mm])
            if len(rows) > 1
            else Paragraph("Действий пока не назначено.", st["p"])
        )
    out += [
        Spacer(1, 10),
        Paragraph(
            "Система показывает, где нужен разговор, и не принимает решений о людях. В аналитике только ID участников.",
            st["s"],
        ),
    ]
    buf = io.BytesIO()
    SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="Пульс адаптации — отчёт",
    ).build(out)
    return buf.getvalue()


def xlsx(data: dict, parts: set[str]) -> bytes:
    """Отчёт в Excel: по листу на раздел."""
    wb = Workbook()
    head_fill, bold = PatternFill("solid", fgColor="EEF1F6"), Font(bold=True)

    def sheet(title: str, rows: list[list]) -> None:
        ws = wb.create_sheet(title[:31])
        for r in rows:
            ws.append(r)
        for c in ws[1]:
            c.font, c.fill = bold, head_fill
        for col in ws.columns:
            width = min(70, max(len(str(c.value or "")) for c in col) + 2)
            ws.column_dimensions[col[0].column_letter].width = width
            for c in col:
                c.alignment = Alignment(wrap_text=True, vertical="top")

    d = data["d"]
    if "sum" in parts:
        sheet(
            "Сводка",
            [["Показатель", "Значение", "Пояснение"], [d["headline"], "", d["sub"]]]
            + [[k["label"], k["value"], k["note"]] for k in d["kpis"]]
            + (
                [[h["month"], h["kpis"][0]["value"], "пар в зоне внимания"] for h in data["hist"]]
                if data["hist"]
                else []
            ),
        )
    if "signals" in parts:
        sheet(
            "Сигналы",
            [["Пара", "Тип", "Что происходит"]] + [[a["pair"], a["type"], a["why"]] for a in d["alerts"]],
        )
    if "pairs" in parts:
        rows = [
            ["Пара", "Стажёр", "Наставник", "Подразделение", "Индекс", "Состояние"]
            + [
                x["name"]
                for x in (
                    data["cards"][0]["decomp"] if data["cards"] and not data["cards"][0].get("empty") else []
                )
            ]
        ]
        for c in data["cards"]:
            if not c.get("empty"):
                rows.append(
                    [c["code"], c["intern"], c["mentor"], c["dept"], c["health"], c["st"]["label"]]
                    + [x["value"] for x in c["decomp"]]
                )
        sheet("Пары", rows)
    if "actions" in parts:
        rows = [["Пара", "Действие", "Статус", "Эффект"]]
        for c in data["cards"]:
            for a in c.get("actions", []):
                rows.append([c["code"], a["title"], a["status_ru"], (a.get("effect") or {}).get("text", "")])
        sheet("Действия", rows)
    del wb["Sheet"]
    if not wb.sheetnames:
        wb.create_sheet("Отчёт")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
