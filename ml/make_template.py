"""Шаблон для ручного приведения данных: `python -m ml.make_template` → docs/template.xlsx."""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from ml.synth import INTERN_QUESTIONS, MENTOR_QUESTIONS

OUT = Path(__file__).resolve().parent.parent / "docs" / "template.xlsx"


def main() -> None:
    wb = Workbook()
    ins = wb.active
    ins.title = "Инструкция"
    for row in [
        ["Шаблон загрузки «Пульс адаптации»"],
        [
            "Если загрузчик не понял исходные файлы, перенесите данные сюда и загрузите этот файл вместе с Word."
        ],
        ["Лист «Стажёры» и «Наставники»: одна строка — одна анкета за месяц."],
        [
            "ID — как в данных кейса (С-101, Н-201). В колонке «ID другой стороны» — ID пары: наставник для стажёра и наоборот."
        ],
        ["Месяц — номер месяца программы (1–6) или дата заполнения."],
        [
            "Оценки — числа шкалы анкеты (например, 1–5). Заголовки колонок можно заменить точными формулировками вопросов из Word."
        ],
        ["Комментарий — свободный текст, можно оставить пустым."],
    ]:
        ins.append(row)
    ins["A1"].font = Font(bold=True, size=14)
    ins.column_dimensions["A"].width = 120
    head = PatternFill("solid", fgColor="EEF1F6")
    for title, own, other, qs in (
        ("Стажёры", "ID стажёра", "ID наставника", INTERN_QUESTIONS),
        ("Наставники", "ID наставника", "ID стажёра", MENTOR_QUESTIONS),
    ):
        ws = wb.create_sheet(title)
        ws.append([own, other, "Месяц", "Подразделение"] + [q for q, _ in qs] + ["Комментарий"])
        ws.append(
            [
                "С-101" if title == "Стажёры" else "Н-201",
                "Н-201" if title == "Стажёры" else "С-101",
                1,
                "Сеть ШПД",
            ]
            + [4] * len(qs)
            + ["Пример комментария"]
        )
        for c in ws[1]:
            c.font, c.fill = Font(bold=True), head
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = max(14, min(40, len(str(col[0].value)) + 2))
    wb.save(OUT)
    print(f"Шаблон: {OUT}")


if __name__ == "__main__":
    main()
