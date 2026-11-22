"""Генератор тестовых файлов загрузчика: `python -m ml.make_fixtures`.

Создаёт в tests/fixtures/ingest/ шесть вариантов «Excel стажёров + Excel наставников + Word»
и эталон `expected.json` для каждого (см. docs/SPEC.md, раздел 5.2).
"""

import json
import shutil
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from docx import Document
from openpyxl import Workbook

from ml.synth import (
    COMMENT_INTERN,
    COMMENT_MENTOR,
    INTERN_QUESTIONS,
    MENTOR_QUESTIONS,
    MONTHS_RU,
    PAIRS,
    to_scale,
)

ROOT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "ingest"
VERBAL = ["совсем нет", "скорее нет", "отчасти", "скорее да", "полностью"]
QS = {"intern": INTERN_QUESTIONS, "mentor": MENTOR_QUESTIONS}
COMMENT_Q = {"intern": COMMENT_INTERN, "mentor": COMMENT_MENTOR}
MONTHS = range(6)


def ids(side: str, p, latin: bool = False) -> tuple[str, str]:
    """(свой ID, ID другой стороны)."""
    own, other = (p.intern_id, p.mentor_id) if side == "intern" else (p.mentor_id, p.intern_id)
    if latin:
        tr = str.maketrans({"С": "S", "Н": "M"})
        return own.translate(tr), other.translate(tr)
    return own, other


def comment(side: str, p, m: int) -> str:
    return p.comments.get(side, {}).get(m, "")


# ---------- Word ----------


def word_paragraphs(path: Path, blocks: list[tuple[str, str, int, int]]) -> None:
    """Анкеты списком абзацев. blocks: (заголовок, сторона, мин, макс)."""
    doc = Document()
    for title, side, lo, hi in blocks:
        doc.add_heading(title, level=1)
        doc.add_paragraph("Ответьте, пожалуйста, на вопросы о прошедшем месяце.")
        for i, (q, _) in enumerate(QS[side], 1):
            doc.add_paragraph(f"{i}. {q}")
            doc.add_paragraph(f"Шкала от {lo} до {hi}: {lo} — совсем нет, {hi} — полностью.")
        doc.add_paragraph(f"{len(QS[side]) + 1}. {COMMENT_Q[side]}")
        doc.add_paragraph("Свободный ответ.")
    doc.save(path)


def word_table(path: Path, title: str, side: str, answer_type: str, codes: bool = False) -> None:
    """Анкета таблицей: № | Вопрос | Тип ответа."""
    doc = Document()
    doc.add_heading(title, level=1)
    t = doc.add_table(rows=1, cols=3)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text, t.rows[0].cells[2].text = "№", "Вопрос", "Тип ответа"
    for i, (q, _) in enumerate(QS[side], 1):
        row = t.add_row().cells
        row[0].text = f"Q{i}" if codes else str(i)
        row[1].text = q
        row[2].text = answer_type
    row = t.add_row().cells
    row[0].text = f"Q{len(QS[side]) + 1}" if codes else str(len(QS[side]) + 1)
    row[1].text = COMMENT_Q[side]
    row[2].text = "текст"
    doc.save(path)


# ---------- данные ----------


def wide_rows(
    side: str, value: Callable[[int, int, float], object], period: Callable[[int], object]
) -> list[dict]:
    rows = []
    for p in PAIRS:
        own, other = ids(side, p)
        for m in MONTHS:
            r = {"own": own, "other": other, "period": period(m)}
            for qi, (_, topic) in enumerate(QS[side]):
                r[f"q{qi}"] = value(qi, m, p.value(side, topic, m))
            r["comment"] = comment(side, p, m)
            rows.append(r)
    return rows


def expected_sample(side: str, lo: int, hi: int, verbal: bool = False) -> list[dict]:
    """Несколько контрольных значений после нормализации."""
    out = []
    for p in PAIRS[:3]:
        own = p.intern_id if side == "intern" else p.mentor_id
        for m in (0, 5):
            topic = QS[side][1][1]
            v = p.value(side, topic, m)
            if verbal:
                norm = to_scale(v, 0, 4) / 4
            else:
                norm = (to_scale(v, lo, hi) - lo) / (hi - lo)
            out.append({"side": side, "id": own, "period": m + 1, "topic": topic, "norm": round(norm, 3)})
    return out


def base_expected(files: dict[str, str]) -> dict:
    return {
        "files": files,
        "pairs": sorted([p.intern_id, p.mentor_id] for p in PAIRS),
        "responses": {"intern": 30, "mentor": 30},
        "questions": {"intern": 7, "mentor": 7},
        "sample": [],
        "quality": [],
        "asks": 0,
    }


def save_xlsx(path: Path, df: pd.DataFrame, sheet: str = "Ответы") -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        df.to_excel(w, sheet_name=sheet, index=False)


def v1(d: Path) -> dict:
    """Широкий формат, заголовки = формулировки, шкала 1–5, номер месяца."""
    for side, fname, own_h, other_h in [
        ("intern", "стажёры.xlsx", "ID стажёра", "ID наставника"),
        ("mentor", "наставники.xlsx", "ID наставника", "ID стажёра"),
    ]:
        rows = wide_rows(side, lambda qi, m, v: to_scale(v, 1, 5), lambda m: m + 1)
        df = pd.DataFrame(
            [
                {own_h: r["own"], other_h: r["other"], "Месяц": r["period"]}
                | {q: r[f"q{i}"] for i, (q, _) in enumerate(QS[side])}
                | {"Комментарий": r["comment"]}
                for r in rows
            ]
        )
        save_xlsx(d / fname, df)
    word_paragraphs(d / "анкета_стажёра.docx", [("Анкета стажёра", "intern", 1, 5)])
    word_paragraphs(d / "анкета_наставника.docx", [("Анкета наставника", "mentor", 1, 5)])
    e = base_expected({"стажёры.xlsx": "intern", "наставники.xlsx": "mentor"})
    e["sample"] = expected_sample("intern", 1, 5) + expected_sample("mentor", 1, 5)
    return e


def v2(d: Path) -> dict:
    """Длинный формат, коды Q1…Q7, латинские ID, пары по шаблону ID."""
    for side, fname in [("intern", "intern_answers.csv"), ("mentor", "mentor_answers.csv")]:
        recs = []
        for p in PAIRS:
            own, _ = ids(side, p, latin=True)
            for m in MONTHS:
                for qi, (_, topic) in enumerate(QS[side]):
                    recs.append(
                        {
                            "participant_id": own,
                            "month": m + 1,
                            "question": f"Q{qi + 1}",
                            "answer": to_scale(p.value(side, topic, m), 1, 5),
                        }
                    )
                c = comment(side, p, m)
                if c:
                    recs.append(
                        {
                            "participant_id": own,
                            "month": m + 1,
                            "question": f"Q{len(QS[side]) + 1}",
                            "answer": c,
                        }
                    )
        pd.DataFrame(recs).to_csv(d / fname, index=False)
    word_table(d / "intern_form.docx", "Анкета стажёра", "intern", "шкала 1–5", codes=True)
    word_table(d / "mentor_form.docx", "Анкета наставника", "mentor", "шкала 1–5", codes=True)
    e = base_expected({"intern_answers.csv": "intern", "mentor_answers.csv": "mentor"})
    tr = str.maketrans({"С": "S", "Н": "M"})
    e["pairs"] = sorted([p.intern_id.translate(tr), p.mentor_id.translate(tr)] for p in PAIRS)
    e["sample"] = [
        s | {"id": s["id"].translate(tr)}
        for s in expected_sample("intern", 1, 5) + expected_sample("mentor", 1, 5)
    ]
    return e


def v3(d: Path) -> dict:
    """Шкала 1–10 у наставников и 1–5 у стажёров, даты вместо месяцев, нейтральные имена файлов."""
    start = date(2026, 6, 24)
    paraphrase = {
        "intern": [
            "Понятны ли задачи, которые вы получаете",
            "Можете ли выполнять задачи без помощи наставника",
            "Хватает ли времени и внимания наставника",
            "Комфортен ли объём задач",
            "Получаете ли обратную связь по работе",
            "Понятны ли ваши перспективы после стажировки",
        ],
        "mentor": [
            "Понимает ли стажёр, что от него ожидают",
            "Насколько стажёр самостоятелен",
            "Хватает ли вам времени на наставничество",
            "Как стажёр справляется с объёмом",
            "Как стажёр воспринимает обратную связь",
            "Видите ли стажёра в штате после программы",
        ],
    }
    for side, fname, lo, hi, link in [
        ("intern", "export_A.xlsx", 1, 5, "Наставник"),
        ("mentor", "export_B.xlsx", 1, 10, "Стажёр"),
    ]:
        rows = wide_rows(
            side,
            lambda qi, m, v, lo=lo, hi=hi: to_scale(v, lo, hi),
            lambda m: start + timedelta(days=30 * m + (m % 3)),
        )
        df = pd.DataFrame(
            [
                {"Код участника": r["own"], link: r["other"], "Дата заполнения": pd.Timestamp(r["period"])}
                | {paraphrase[side][i]: r[f"q{i}"] for i in range(6)}
                | {"Комментарий": r["comment"]}
                for r in rows
            ]
        )
        save_xlsx(d / fname, df, "Sheet1")
    word_paragraphs(d / "анкета_стажёра.docx", [("Анкета стажёра", "intern", 1, 5)])
    word_paragraphs(d / "анкета_наставника.docx", [("Анкета наставника", "mentor", 1, 10)])
    e = base_expected({"export_A.xlsx": "intern", "export_B.xlsx": "mentor"})
    e["sample"] = expected_sample("intern", 1, 5) + expected_sample("mentor", 1, 10)
    return e


def v4(d: Path) -> dict:
    """Словесная шкала, названия месяцев, комментарии в двух колонках."""
    for side, fname, own_h, other_h in [
        ("intern", "ответы_стажеров.xlsx", "Стажёр", "Наставник"),
        ("mentor", "ответы_наставников.xlsx", "Наставник", "Стажёр"),
    ]:
        rows = wide_rows(side, lambda qi, m, v: VERBAL[to_scale(v, 0, 4)], lambda m: MONTHS_RU[m])
        df = pd.DataFrame(
            [
                {own_h: r["own"], other_h: r["other"], "Месяц анкеты": r["period"]}
                | {q: r[f"q{i}"] for i, (q, _) in enumerate(QS[side])}
                | {
                    "Что получается": r["comment"] if "не" not in r["comment"] else "",
                    "Что мешает": r["comment"] if "не" in r["comment"] else "",
                }
                for r in rows
            ]
        )
        save_xlsx(d / fname, df)
    opts = "совсем нет / скорее нет / отчасти / скорее да / полностью"
    word_table(d / "анкета_стажёра.docx", "Анкета стажёра", "intern", opts)
    word_table(d / "анкета_наставника.docx", "Анкета наставника", "mentor", opts)
    e = base_expected({"ответы_стажеров.xlsx": "intern", "ответы_наставников.xlsx": "mentor"})
    e["sample"] = expected_sample("intern", 0, 4, verbal=True) + expected_sample("mentor", 0, 4, verbal=True)
    return e


def v5(d: Path) -> dict:
    """Лишний лист «Инструкция», объединённые ячейки, двухстрочная шапка."""
    for side, fname, own_h, other_h in [
        ("intern", "Анкета стажёра (выгрузка).xlsx", "ID", "Наставник"),
        ("mentor", "Анкета наставника (выгрузка).xlsx", "ID", "Стажёр"),
    ]:
        wb = Workbook()
        ins = wb.active
        ins.title = "Инструкция"
        ins["A1"] = "Как заполнять выгрузку"
        ins["A2"] = "Не меняйте названия колонок. Один ряд — одна анкета."
        ws = wb.create_sheet("Данные")
        ncols = 3 + 6 + 1
        ws.cell(1, 1, "Выгрузка ответов за июнь–ноябрь 2026")
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
        ws.cell(2, 1, "Участник")
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=3)
        ws.cell(2, 4, "Оценки")
        ws.merge_cells(start_row=2, start_column=4, end_row=2, end_column=9)
        ws.cell(2, 10, "Текст")
        heads = [own_h, other_h, "Месяц"] + [q for q, _ in QS[side]] + ["Комментарий"]
        for j, h in enumerate(heads, 1):
            ws.cell(3, j, h)
        rows = wide_rows(side, lambda qi, m, v: to_scale(v, 1, 5), lambda m: m + 1)
        for i, r in enumerate(rows, 4):
            vals = (
                [r["own"], r["other"], r["period"]] + [r[f"q{k}"] for k in range(6)] + [r["comment"] or None]
            )
            for j, v in enumerate(vals, 1):
                ws.cell(i, j, v)
        wb.save(d / fname)
    word_paragraphs(d / "анкета_стажёра.docx", [("Анкета стажёра", "intern", 1, 5)])
    word_paragraphs(d / "анкета_наставника.docx", [("Анкета наставника", "mentor", 1, 5)])
    e = base_expected(
        {"Анкета стажёра (выгрузка).xlsx": "intern", "Анкета наставника (выгрузка).xlsx": "mentor"}
    )
    e["sample"] = expected_sample("intern", 1, 5) + expected_sample("mentor", 1, 5)
    return e


def v6(d: Path) -> dict:
    """Опечатка в ID, один дубль, три пропуска, обе анкеты в одном Word."""
    for side, fname in [("intern", "data1.xlsx"), ("mentor", "data2.xlsx")]:
        rows = wide_rows(side, lambda qi, m, v: to_scale(v, 1, 5), lambda m: m + 1)
        df = pd.DataFrame(
            [
                {"Участник": r["own"], "Пара": r["other"], "Месяц": r["period"]}
                | {q: r[f"q{i}"] for i, (q, _) in enumerate(QS[side])}
                | {"Комментарий": r["comment"]}
                for r in rows
            ]
        )
        if side == "intern":
            df.loc[(df["Участник"] == "С-104") & (df["Месяц"] == 3), "Участник"] = "С-1О4"
            dup = df[(df["Участник"] == "С-102") & (df["Месяц"] == 4)].copy()
            df = pd.concat([df, dup], ignore_index=True)
        else:
            mask = (df["Участник"] == "Н-204") & (df["Месяц"] == 5)
            for i in (1, 3, 4):
                df.loc[mask, QS["mentor"][i][0]] = None
        save_xlsx(d / fname, df)
    word_paragraphs(
        d / "анкеты.docx", [("Анкета для стажёра", "intern", 1, 5), ("Анкета для наставника", "mentor", 1, 5)]
    )
    e = base_expected({"data1.xlsx": "intern", "data2.xlsx": "mentor"})
    e["sample"] = expected_sample("intern", 1, 5) + expected_sample("mentor", 1, 5)
    e["quality"] = ["id_typo", "duplicate", "missing"]
    e["asks"] = 0
    return e


VARIANTS = [v1, v2, v3, v4, v5, v6]


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    for i, fn in enumerate(VARIANTS, 1):
        d = ROOT / f"v{i}"
        d.mkdir(parents=True)
        exp = fn(d)
        (d / "expected.json").write_text(json.dumps(exp, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"v{i}: {sorted(p.name for p in d.iterdir())}")


if __name__ == "__main__":
    main()
