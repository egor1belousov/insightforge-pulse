"""ИИ-ассистент с учётом роли.

HR и руководитель: данные всех пар + методика + регламент.
Стажёр и наставник: только свои данные + регламент; ответы другой стороны не раскрываются
(проверка правилами до обращения к модели).
"""

import re
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import Assignment, Course, Program, User
from app.services.dashboard import dashboard
from app.services.forms.me import my_data
from app.services.llm.client import chat_json, prompt

DOCS = Path(__file__).resolve().parent.parent.parent / "docs"
OTHER_SIDE_RE = re.compile(
    r"(наставник|стаж[её]р)\w*.{0,30}(оцен|ответ|дума|пишет|написал|комментар|считает|говорит|жалует)"
    r"|(оцен|ответ|комментар|дума|счита|пишет|говорит|жалует)\w*.{0,25}(наставник|стаж[её]р)",
    re.I,
)
REFUSAL = (
    "Я не показываю ответы другой стороны — так анкеты остаются честными. "
    "Могу подсказать, как начать разговор: предложите короткую встречу и приходите с двумя-тремя конкретными вопросами. "
    "Если нужна помощь — нажмите «Хочу поговорить с HR»."
)


REG_INTENT = re.compile(
    r"отпуск|зарплат|оплат|стипенд|аттестац|график|отсутств|выходн|больничн|увольн по|сроки стаж"
)
NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in NUM_RE.findall(text)}


def _known_intent(q: str, staff: bool) -> bool:
    t = q.lower()
    if staff:
        return bool(
            re.search(
                r"п-?0?\d{1,2}\b|перв|приоритет|срочн|кому.*помо|программ|систем|уход|увол|(пар|наставник).*(форм|созда|подбор|смен|замен|назнач)",
                t,
            )
        )
    return bool(re.search(r"поговор|\bhr\b|эйчар|анкет|курс|тест|обучен", t))


class AssistantAnswer(BaseModel):
    answer: str
    refs: list[str] = Field(default_factory=list)


def regulations() -> list[tuple[str, str]]:
    """Пункты регламента: (номер, текст)."""
    path = DOCS / "REGULATIONS.md"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(\d+\.\d+)\.\s+(.*)", line.strip())
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def _reg_hits(q: str) -> list[tuple[str, str]]:
    words = [
        w
        for w in re.findall(r"[а-яё]{4,}", q.lower())
        if w not in ("когда", "какой", "какая", "можно", "нужно", "стажёр", "стажер")
    ]
    hits = []
    for num, text in regulations():
        t = text.lower()
        score = sum(1 for w in words if w[:5] in t)
        if score:
            hits.append((score, num, text))
    return [(n, t) for _, n, t in sorted(hits, reverse=True)[:3]]


def _staff_context(db: Session, program: Program, user: User) -> tuple[str, dict]:
    d = dashboard(db, program, user)
    lines = [f"Месяц: {d['tag']}. {d['headline']}. {d['sub']}"]
    for p in sorted(d["pairs"], key=lambda x: x["health"] or 100):
        alert = next((a for a in d["alerts"] if a["pair"] == p["code"]), None)
        lines.append(
            f"{p['code']} ({p['intern']} + {p['mentor']}, {p['dept']}): индекс {p['health']}, состояние «{p['st']['label']}». {alert['why'] if alert else 'Сигналов нет.'}"
        )
    if d["program"]["box"]:
        lines.append(d["program"]["box"]["title"] + ". " + d["program"]["box"]["text"])
    return "\n".join(lines), d


def _side_context(db: Session, program: Program, user: User) -> tuple[str, dict]:
    from app.core.deps import own_participant

    part = own_participant(db, user)
    if part is None:
        return "Участник не привязан к паре.", {}
    me = my_data(db, program, part)
    lines = [
        f"Пользователь: {'наставник' if part.side == 'mentor' else 'стажёр'} {part.external_id}, {me['month_number']}-й месяц, анкета за {me['period_name']}: {'получена' if me['submitted'] else 'ещё не заполнена'}."
    ]
    if me["bars"]:
        lines.append("Свои оценки по темам: " + ", ".join(f"{b['name']} {b['now']:.2f}" for b in me["bars"]))
    for t in me["talk"]:
        lines.append(f"Тема для разговора: {t['title']} — {t['text']}")
    for a in db.query(Assignment).filter(Assignment.participant_id == part.id):
        if a.course_id:
            c = db.get(Course, a.course_id)
            lines.append(f"Назначен курс «{c.title}» ({c.duration}), пройден на {a.progress}%.")
        elif a.test_id:
            lines.append(
                f"Назначен тест, {'результат ' + str(round((a.score or 0) * 100)) + '%' if a.score is not None else 'ещё не пройден'}."
            )
    return "\n".join(lines), me


def _fallback_staff(q: str, d: dict) -> AssistantAnswer:
    t = q.lower()
    m = re.search(r"п-?0?(\d{1,2})", t)
    if m:
        code = f"П-{int(m.group(1)):02d}"
        p = next((x for x in d["pairs"] if x["code"] == code), None)
        if p:
            a = next((x for x in d["alerts"] if x["pair"] == code), None)
            past = next((x for x in d.get("history", []) if x["pair"] == code), None)
            why = a["why"] if a else "Сейчас сигналов нет: оценки сторон согласованы."
            if not a and past:
                why += f" Внимание требовалось: {past['months']}" + (
                    f" (критично — {past['red']})." if past["red"] else "."
                )
            return AssistantAnswer(
                answer=f"{code}: индекс {p['health']}, «{p['st']['label']}». {why} Что делать — во вкладке «Действия» карточки пары: там рекомендации и повестка встречи.",
                refs=[f"сигналы {code}"],
            )
    if re.search(r"перв|приоритет|срочн|кому.*помо", t):
        order = [p for p in sorted(d["pairs"], key=lambda x: x["health"] or 100) if p["visible"]]
        txt = ", ".join(f"{p['code']} (индекс {p['health']}, {p['st']['label'].lower()})" for p in order[:3])
        if not txt and d.get("history"):
            hist = ", ".join(
                f"{h['pair']} ({h['intern']}: {h['red'] or h['months']})" for h in d["history"][:3]
            )
            pending = d["forms"]["pending"]
            return AssistantAnswer(
                answer=f"Сейчас сигналов нет. Сильнее всего внимание требовалось {hist} — проверьте, что улучшение закрепилось."
                + (f" Анкеты за этот месяц ещё не сдали: {', '.join(pending)}." if pending else ""),
                refs=["история сигналов", "анкеты за месяц"],
            )
        return AssistantAnswer(
            answer=f"По индексу здоровья первыми — {txt or 'сейчас сигналов нет'}. Начните с пары с самым низким индексом.",
            refs=["индекс здоровья пар"],
        )
    if re.search(r"программ|систем|общ", t) and d["program"]["box"]:
        return AssistantAnswer(
            answer=d["program"]["box"]["title"] + ". " + d["program"]["box"]["text"],
            refs=["сигнал программы"],
        )
    if re.search(r"уход|увол", t):
        risk = [p["code"] for p in d["pairs"] if p["state"] in ("under", "both")]
        return AssistantAnswer(
            answer=(
                "Ранние признаки риска ухода: "
                + ", ".join(risk)
                + ". Это не прогноз увольнения, а повод поговорить в ближайшие две недели."
            )
            if risk
            else "Ранних признаков риска ухода сейчас нет.",
            refs=["состояния пар"],
        )
    if re.search(r"(пар|наставник).*(форм|созда|подбор|смен|замен|назнач)", t):
        return AssistantAnswer(
            answer="Пары формирует HR в разделе «Программа»: для стажёра без пары система ранжирует свободных наставников по подразделению, загрузке и истории сигналов. Там же можно сменить наставника — история пары сохранится.",
            refs=["раздел «Программа»"],
        )
    return AssistantAnswer(
        answer=f"{d['headline']}. Могу разобрать любую пару («что делать с П-02»), подсказать, кому помочь первым, или ответить по регламенту.",
        refs=["дашборд"],
    )


def _fallback_side(q: str, me: dict) -> AssistantAnswer:
    t = q.lower()
    if re.search(r"поговор|hr|эйчар", t):
        return AssistantAnswer(
            answer="На странице «Моя стажировка» есть кнопка «Хочу поговорить с HR». Запрос увидит только HR, другая сторона пары о нём не узнает.",
            refs=["регламент п. 7.2"],
        )
    if re.search(r"анкет", t) and me:
        return AssistantAnswer(
            answer=f"Анкета за {me['period_name']} {'уже получена, спасибо' if me['submitted'] else 'ждёт вас на странице «Моя стажировка»: 2 минуты'}.",
            refs=["ваши данные"],
        )
    if re.search(r"курс|тест|учи|обучен", t):
        return AssistantAnswer(
            answer="Назначенные курсы и тесты — в разделе «Обучение». Пройдите курс, затем тест и разберите ошибки с наставником на реальной задаче.",
            refs=["регламент п. 3.2"],
        )
    return AssistantAnswer(
        answer="Я отвечаю по регламенту стажировки и вашим собственным данным: анкеты, курсы, сроки. Спросите, например, про отпуск, тесты или аттестацию.",
        refs=["база знаний"],
    )


def ask(db: Session, program: Program, user: User, question: str) -> dict:
    """Ответ ассистента с источниками и пометкой, кто ответил (ИИ или правила)."""
    q = question.strip()[:1000]
    if not q:
        return {"answer": "Задайте вопрос.", "refs": [], "fallback": True}
    staff = user.role in ("hr", "lead")
    if not staff and OTHER_SIDE_RE.search(q):
        return {"answer": REFUSAL, "refs": ["правила конфиденциальности"], "fallback": True}
    ctx, data = _staff_context(db, program, user) if staff else _side_context(db, program, user)
    regs = _reg_hits(q)
    # 1. Регламент — дословно из документа, без пересказа моделью.
    if regs and REG_INTENT.search(q.lower()):
        sect = regs[0][0].split(".")[0]
        same = [(n, t) for n, t in regulations() if n.split(".")[0] == sect]
        return {
            "answer": " ".join(t for _, t in same)
            + " Точные правила — в регламенте стажировки вашей компании.",
            "refs": [f"регламент п. {', '.join(n for n, _ in same)}"],
            "source": "regulations",
            "fallback": True,
        }
    # 2. Распознанные вопросы о данных — собираются из базы, без генерации.
    known = _known_intent(q, staff)
    if known:
        fb = _fallback_staff(q, data) if staff else _fallback_side(q, data)
        return fb.model_dump() | {"source": "data", "fallback": True}
    # 3. Остальное — модель по контексту; ответ с числами, которых нет в данных, отбрасывается.
    reg_txt = "\n".join(f"Регламент п. {n}: {t}" for n, t in regs)
    rules = (
        "Можно обсуждать все пары, сигналы и методику."
        if staff
        else "Не раскрывай ответы и оценки другой стороны пары. Отвечай только по данным пользователя и регламенту."
    )
    context = ctx + ("\n" + reg_txt if reg_txt else "")
    res = chat_json(
        prompt("system"),
        prompt(
            "assistant",
            role="HR или руководитель" if staff else "стажёр или наставник",
            rules=rules,
            context=context,
            question=q,
        ),
        AssistantAnswer,
        timeout=60,
    )
    if res is not None and res.answer.strip() and _numbers(res.answer) <= _numbers(context + " " + q):
        return {"answer": res.answer.strip(), "refs": res.refs[:4], "source": "llm", "fallback": False}
    fb = _fallback_staff(q, data) if staff else _fallback_side(q, data)
    return fb.model_dump() | {"source": "data", "fallback": True}
