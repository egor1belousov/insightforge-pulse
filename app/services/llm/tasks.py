"""Задачи LLM (docs/SPEC.md, раздел 7). У каждой — Pydantic-схема и запасной вариант на правилах.

Каждая функция возвращает словарь с полем `fallback`: True, если ответ получен правилами.
"""

import re
from datetime import date

from pydantic import BaseModel, Field

from app.core.settings import get_settings
from app.services.ingest.text import guess_topic, side_hint, similarity
from app.services.llm import fallback
from app.services.llm.client import chat_json, prompt

TOPICS = {
    "tasks": "Понимание задач",
    "auto": "Самостоятельность",
    "support": "Поддержка",
    "load": "Нагрузка",
    "feedback": "Обратная связь",
    "growth": "Перспективы",
}
SIDE_RU = {"intern": "стажёр", "mentor": "наставник"}


def _system() -> str:
    return prompt("system")


def _model() -> str:
    return get_settings().ollama_model


# ---------- 1. classify_table ----------


class TableSide(BaseModel):
    side: str = Field(pattern="^(intern|mentor)$")
    confidence: float = Field(ge=0, le=1)


def classify_table(file: str, sheet: str, headers: list[str]) -> dict:
    """Сторона таблицы, когда признаков мало."""
    res = chat_json(
        _system(),
        prompt("classify_table", file=file, sheet=sheet, headers="; ".join(headers[:30])),
        TableSide,
        timeout=30,
    )
    if res is not None:
        return {"side": res.side, "confidence": min(res.confidence, 0.85), "fallback": False}
    hi = sum(side_hint(h)[0] for h in headers) + side_hint(file)[0] * 2
    hm = sum(side_hint(h)[1] for h in headers) + side_hint(file)[1] * 2
    if hi == hm:
        return {"side": "intern", "confidence": 0.3, "fallback": True}
    return {"side": "intern" if hi > hm else "mentor", "confidence": 0.55, "fallback": True}


# ---------- 2. map_question_topic ----------


class TopicAnswer(BaseModel):
    topic: str
    confidence: float = Field(ge=0, le=1)
    mirror: int = Field(ge=0, default=0)


def map_question_topic(text: str, side: str, others: list[str]) -> dict:
    """Тема вопроса и номер зеркального вопроса другой стороны (1-based, 0 — нет)."""
    topics = "\n".join(f"{k} — {v}" for k, v in TOPICS.items())
    other_txt = "\n".join(f"{i} — {q}" for i, q in enumerate(others, 1)) or "нет"
    res = chat_json(
        _system(),
        prompt(
            "map_question_topic", side=SIDE_RU.get(side, side), text=text, topics=topics, others=other_txt
        ),
        TopicAnswer,
        timeout=30,
    )
    if res is not None and res.topic in TOPICS:
        mirror = res.mirror if 0 < res.mirror <= len(others) else 0
        return {
            "topic": res.topic,
            "confidence": min(res.confidence, 0.9),
            "mirror": mirror,
            "fallback": False,
        }
    topic, conf = guess_topic(text)
    mirror = 0
    if others:
        scored = [(guess_topic(o)[0] == topic, similarity(text, o), i) for i, o in enumerate(others, 1)]
        best = max(scored)
        mirror = best[2] if best[0] else 0
    return {"topic": topic, "confidence": conf, "mirror": mirror, "fallback": True}


# ---------- 3. analyze_comment ----------


class CommentAnswer(BaseModel):
    topics: list[str] = Field(default_factory=list)
    tone: float = Field(ge=-1, le=1)
    anxiety: float = Field(ge=0, le=1)
    quote: str = ""


def _contradiction(anxiety: float, score: float | None) -> float:
    if score is None:
        return 0.0
    return round(anxiety * max(0.0, min(1.0, (score - 0.4) / 0.35)), 2)


def analyze_comment(text: str, score: float | None, side: str = "intern") -> dict:
    """Темы, тон, тревожность, противоречие с баллами, дословная цитата.

    Тревожность — максимум из оценки модели и словаря: небольшая модель склонна её занижать.
    Цитата проверяется вхождением в текст.
    """
    rules = fallback.analyze_comment(text, score)
    sc = "нет данных" if score is None else f"{score:.2f}"
    res = chat_json(
        _system(),
        prompt("analyze_comment", side=SIDE_RU.get(side, side), score=sc, text=text),
        CommentAnswer,
        timeout=40,
    )
    if res is None:
        return rules | {
            "contradiction": _contradiction(rules["anxiety"], score),
            "model": "rules",
            "fallback": True,
        }
    quote = res.quote.strip().strip('«»"')
    pos = text.lower().find(quote.lower()) if quote else -1
    quote = text[pos : pos + len(quote)] if pos >= 0 else rules["quote"]  # дословно, в исходном регистре
    topics = [t for t in res.topics if t in TOPICS] or rules["topics"]
    anxiety = round(max(res.anxiety, rules["anxiety"]), 2)
    return {
        "topics": topics,
        "tone": round(res.tone, 2),
        "anxiety": anxiety,
        "contradiction": _contradiction(anxiety, score),
        "quote": quote,
        "model": _model(),
        "fallback": False,
    }


# ---------- 4. explain_signal ----------


class TextAnswer(BaseModel):
    text: str


NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _numbers(s: str) -> set[str]:
    return {n.replace(",", ".").lstrip("0") or "0" for n in NUM_RE.findall(s)}


def explain_signal(pair: str, signals: list[dict]) -> dict:
    """Причина сигналов простыми словами по фактам из БД. Новые числа запрещены."""
    facts = "\n".join(f"- {s['type']}: {s['description']}" for s in signals)
    rules_text = " ".join(dict.fromkeys(s["cause"] for s in signals if s.get("cause")))
    if not signals:
        return {"text": "Сигналов нет: оценки сторон согласованы.", "fallback": True}
    res = chat_json(_system(), prompt("explain_signal", pair=pair, facts=facts), TextAnswer, timeout=40)
    if res is not None and res.text.strip():
        if _numbers(res.text) <= _numbers(facts) | {"1", "2", "3"}:
            return {"text": res.text.strip(), "fallback": False}
    return {"text": rules_text, "fallback": True}


# ---------- 5. meeting_agenda ----------


class AgendaAnswer(BaseModel):
    items: list[str] = Field(min_length=1, max_length=5)


AGENDA_RULES = {
    "level": "Сверить ожидания: что для каждого значит «хорошо» в работе стажёра — разобрать два конкретных примера.",
    "growth": "Договориться о правиле работы на месяц и назначить контрольную точку через две недели с заранее названными критериями.",
    "lag": "Наставник и стажёр называют, что изменилось за последние месяцы: один уже видит спад, второй — нет.",
    "words": "Отдельно поговорить о том, что беспокоит, — в том числе о перспективах после стажировки.",
    "decline": "HR и руководитель: какую нагрузку можно снять с наставника и как выделить фиксированное время на стажёра.",
    "missing": "Напомнить про ежемесячную анкету: без неё мы не видим изменений.",
}


def meeting_agenda(pair: str, signals: list[dict]) -> dict:
    """Повестка встречи втроём по сигналам пары — без сырых ответов сторон."""
    facts = (
        "\n".join(f"- {s['type']}: {s.get('cause', '')}" for s in signals)
        or "- сигналов нет, плановая встреча"
    )
    res = chat_json(_system(), prompt("meeting_agenda", pair=pair, facts=facts), AgendaAnswer, timeout=40)
    if res is not None:
        items = [i.strip() for i in res.items if i.strip()][:3]
        if items:
            return {"items": items, "fallback": False}
    items = [AGENDA_RULES[s["type"]] for s in signals if s["type"] in AGENDA_RULES]
    items = list(dict.fromkeys(items))[:2] or ["Что получается лучше всего за последний месяц и что мешает."]
    items.append("Записать договорённости «кто — что — когда» и назначить дату следующей сверки.")
    return {"items": items[:3], "fallback": True}


# ---------- 6. meeting_outcomes ----------


class Agreement(BaseModel):
    who: str
    what: str
    when: str = "не указан"


class OutcomesAnswer(BaseModel):
    agreements: list[Agreement] = Field(default_factory=list, max_length=8)


WHO_RE = [
    (re.compile(r"\bстаж[её]р\w*", re.I), "Стажёр"),
    (re.compile(r"\bнаставник\w*", re.I), "Наставник"),
    (re.compile(r"\bhr\b|\bэйчар", re.I), "HR"),
    (re.compile(r"\bруководител\w*", re.I), "Руководитель"),
]
WHEN_RE = re.compile(
    r"((?:до|к|с|через)\s+(?:\d{1,2}\s+\w+|\w+\s+недел\w*|две недели|неделю|месяц)|по\s+\w+(?:ам|ям)|каждую\s+\w+|раз в \w+|\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря))",
    re.I,
)


def _outcomes_rules(text: str, intern: str, mentor: str) -> list[dict]:
    out = []
    for sent in re.split(r"(?<=[.!?;])\s+|\n", text):
        s = sent.strip()
        if not s:
            continue
        who = None
        for rx, name in WHO_RE:
            if rx.search(s):
                who = name
                break
        if who is None or not re.search(
            r"будет|соглас|обещ|сдаёт|сдает|даст|проведёт|подготов|договор|назнач|созвон|решени", s, re.I
        ):
            continue
        label = {"Стажёр": f"Стажёр {intern}", "Наставник": f"Наставник {mentor}"}.get(who, who)
        when = WHEN_RE.search(s)
        what = re.sub(r"^\s*(стаж[её]р|наставник|hr|руководитель)\w*\s*", "", s, flags=re.I).rstrip(".")
        out.append({"who": label, "what": what[:160], "when": when.group(1) if when else "не указан"})
    return out


def meeting_outcomes(text: str, intern: str, mentor: str) -> dict:
    """Договорённости «кто / что / когда» из свободного текста итогов встречи."""
    if not text.strip():
        return {"agreements": [], "fallback": True}
    res = chat_json(
        _system(),
        prompt(
            "meeting_outcomes",
            text=text,
            today=date.today().strftime("%d.%m.%Y"),
            intern=intern,
            mentor=mentor,
        ),
        OutcomesAnswer,
        timeout=60,
    )
    if res is not None and res.agreements:
        return {"agreements": [a.model_dump() for a in res.agreements], "fallback": False}
    return {"agreements": _outcomes_rules(text, intern, mentor), "fallback": True}
