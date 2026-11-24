"""Сводка метрик аудита: python responsive-audit/summarize.py before"""

import json
import sys
from collections import defaultdict
from pathlib import Path

folder = Path(__file__).parent / (sys.argv[1] if len(sys.argv) > 1 else "before")
d = [r for f in sorted(folder.glob("metrics*.json")) for r in json.loads(f.read_text())]
pages = [r for r in d if "hscroll" in r]
modals = [r for r in d if r["page"].startswith("modal")]

print("== Горизонтальный скролл")
for r in pages:
    if r["hscroll"]:
        print(f"  {r['page']} @{r['w']}x{r['h']}: ширина документа {r['hscroll']}")
print("== Элементы за правым краем (первые)")
seen = defaultdict(list)
for r in pages:
    for o in r["offscreen"]:
        seen[(r["page"], o.split(" →")[0])].append(r["w"])
for (p, el), ws in sorted(seen.items()):
    print(f"  {p}: {el} на ширинах {sorted(set(ws))}")
print("== Обрезанный текст")
for r in pages:
    if r["clipped"]:
        print(f"  {r['page']} @{r['w']}: {r['clipped'][:3]}")
print("== Поля ввода < 16px (зум на iOS), только телефоны")
inp = defaultdict(set)
for r in pages:
    if r["w"] < 768:
        for i in r["small_inputs"]:
            inp[r["page"]].add(i)
for p, v in inp.items():
    print(f"  {p}: {sorted(v)[:6]}")
print("== Тач-цели < 44px на 390 (кол-во, примеры)")
for r in pages:
    if r["w"] == 390:
        print(f"  {r['page']}: {r['small_taps_n']} · {r['small_taps'][:6]}")
print("== Мелкий текст <12px на 390 (кол-во элементов)")
print("  " + ", ".join(f"{r['page']} {r['small_text']}" for r in pages if r["w"] == 390))
print("== Модалки и всплывающие окна")
for r in modals:
    m = r.get("modal")
    if r.get("error"):
        print(f"  {r['page']} @{r['w']}x{r['h']}: ошибка {r['error'][:80]}")
    elif m and (m["bottom"] > m["vh"] + 1 or m["right"] > m["vw"] + 1 or m["top"] < 0):
        print(f"  {r['page']} @{r['w']}x{r['h']}: выходит за экран {m}")
