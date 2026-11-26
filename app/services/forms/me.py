"""Данные «Моя стажировка» / «Моя пара»: только своё, без ответов другой стороны."""

from sqlalchemy.orm import Session

from app.db.models import Participant, Program, Response, Signal, Topic
from app.services.analytics.service import month_name
from app.services.forms.submit import active_questionnaire, current_period, pair_of

TALK = {
    "intern": {
        "support": (
            "Время с наставником",
            "Предложите один фиксированный час в неделю и приходите с готовым списком вопросов.",
        ),
        "load": (
            "Объём задач",
            "Скажите наставнику, какие задачи занимают больше всего времени, — вместе решите, что можно упростить.",
        ),
        "tasks": (
            "Понятность задач",
            "Попросите наставника назвать критерии «хорошо сделано» для ближайшей задачи.",
        ),
        "auto": (
            "Самостоятельность",
            "Договоритесь, какую задачу вы попробуете сделать полностью сами и когда покажете результат.",
        ),
        "feedback": (
            "Обратная связь",
            "Попросите короткий разбор одной работы: что получилось и что улучшить.",
        ),
        "growth": (
            "Развитие",
            "Назовите наставнику навык, который хотите прокачать, и попросите задачу под него.",
        ),
        "engage": (
            "Интерес к задачам",
            "Расскажите наставнику, какие задачи вам интереснее всего, — это поможет подобрать следующие.",
        ),
        "overall": (
            "Стажировка в целом",
            "Если что-то не устраивает, нажмите «Хочу поговорить с HR» — разговор останется между вами.",
        ),
    },
    "mentor": {
        "support": (
            "Время на наставничество",
            "Договоритесь со стажёром о фиксированном часе в неделю. Если объекты не позволяют — скажите HR, это нормальный запрос.",
        ),
        "load": (
            "Нагрузка стажёра",
            "Проверьте, понимает ли стажёр приоритеты: что можно отложить, а что срочно.",
        ),
        "tasks": (
            "Ожидания",
            "Назовите вслух, что значит «хорошо» в работе стажёра, на одном конкретном примере.",
        ),
        "auto": ("Передача самостоятельности", "Три шага: показать, сделать вместе, проверить результат."),
        "feedback": (
            "Обратная связь",
            "Раз в неделю — короткий разбор с конкретными примерами: что получилось и что улучшить.",
        ),
        "growth": ("Развитие стажёра", "Расскажите стажёру, какие навыки важны для предложения о работе."),
        "engage": ("Вовлечённость", "Дайте стажёру задачу с правом самому выбрать способ решения."),
        "overall": ("Качество работы", "Разберите вместе одну работу: что сделано хорошо и что доработать."),
    },
}


def my_data(db: Session, program: Program, part: Participant) -> dict:
    """Своя анкета, свои оценки по темам и темы для разговора."""
    qn = active_questionnaire(db, program.id, part.side)
    period = current_period(db, program)
    pair = pair_of(db, part)
    topics = {
        t.id: (t.code, t.name)
        for t in db.query(Topic).filter(Topic.organization_id == program.organization_id)
    }
    resps = db.query(Response).filter(Response.participant_id == part.id).order_by(Response.period).all()
    by_period: dict[int, dict[str, list[float]]] = {}
    for r in resps:
        for a in r.answers:
            if a.value_norm is None or a.question is None or a.question.topic_id not in topics:
                continue
            by_period.setdefault(r.period, {}).setdefault(topics[a.question.topic_id][0], []).append(
                a.value_norm
            )
    periods = sorted(by_period)
    bars = []
    if periods:
        now_p = periods[-1]
        was_p = periods[max(0, len(periods) - 4)]
        for code, name in sorted(
            {v for v in topics.values()},
            key=lambda x: list(TALK["intern"]).index(x[0]) if x[0] in TALK["intern"] else 99,
        ):
            now = by_period[now_p].get(code)
            was = by_period[was_p].get(code)
            if now:
                bars.append(
                    {
                        "topic": code,
                        "name": name,
                        "now": round(sum(now) / len(now), 2),
                        "was": round(sum(was) / len(was), 2) if was else None,
                    }
                )
    # Темы для разговора: по сигналам пары, без раскрытия ответов другой стороны.
    talk_topics: list[str] = []
    if pair:
        last = db.query(Signal).filter(Signal.pair_id == pair.id).order_by(Signal.period.desc()).first()
        if last:
            for s in db.query(Signal).filter(Signal.pair_id == pair.id, Signal.period == last.period):
                if s.topic and s.topic in TALK[part.side]:
                    talk_topics.append(s.topic)
                if s.type == "decline":
                    talk_topics += ["support", "load"]
                if s.type in ("level", "growth"):
                    talk_topics.append("tasks")
    talk_topics = list(
        dict.fromkeys(talk_topics + [b["topic"] for b in sorted(bars, key=lambda b: b["now"])][:2])
    )[:2]
    submitted = any(r.period == period for r in resps)
    return {
        "participant": {
            "id": part.id,
            "external_id": part.external_id,
            "side": part.side,
            "department": part.department,
        },
        "pair": pair.code if pair else None,
        "other": (pair.mentor.external_id if part.side == "intern" else pair.intern.external_id)
        if pair
        else None,
        "period": period,
        "period_name": month_name(program, period),
        "next_name": month_name(program, period + 1),
        "month_number": period,
        "months": [
            {"n": m, "name": month_name(program, m), "done": m in {r.period for r in resps}}
            for m in range(1, max(program.months or 6, period) + 1)
        ],
        "submitted": submitted,
        "questionnaire": None
        if qn is None
        else {
            "id": qn.id,
            "questions": [
                {
                    "id": q.id,
                    "text": q.text,
                    "qtype": q.qtype,
                    "min": q.scale_min,
                    "max": q.scale_max,
                    "labels": q.scale_labels or [],
                    "options": q.options or [],
                }
                for q in qn.questions
            ],
        },
        "bars": bars,
        "talk": [{"title": TALK[part.side][t][0], "text": TALK[part.side][t][1]} for t in talk_topics],
    }
