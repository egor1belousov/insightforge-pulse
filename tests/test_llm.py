import pytest

from app.services.llm import client, tasks


@pytest.fixture
def fake_llm(monkeypatch):
    answers: dict = {}

    def fake(system, user, schema, **kw):
        data = answers.get(schema.__name__)
        return None if data is None else schema.model_validate(data)

    monkeypatch.setattr(tasks, "chat_json", fake)
    return answers


def test_app_works_without_ollama() -> None:
    assert client.chat_json("s", "u", tasks.TextAnswer) is None  # LLM_ENABLED=false в тестах
    c = tasks.analyze_comment(
        "Всё нормально. Только непонятно, куда я расту и будет ли предложение после стажировки", 0.78
    )
    assert c["fallback"] and c["anxiety"] >= 0.6 and c["contradiction"] > 0.5
    assert (
        c["quote"] in "Всё нормально. Только непонятно, куда я расту и будет ли предложение после стажировки"
    )
    t = tasks.map_question_topic(
        "Комфортен ли для вас объём задач?", "intern", ["Как стажёр справляется с объёмом задач?"]
    )
    assert t == {"topic": "load", "confidence": 0.9, "mirror": 1, "fallback": True}
    assert tasks.classify_table("наставники.xlsx", "Лист1", ["ID", "Оценка"])["side"] == "mentor"
    sig = [{"type": "growth", "description": "Расхождение растёт: +0.08", "cause": "Нужна встреча втроём."}]
    assert tasks.explain_signal("П-02", sig) == {"text": "Нужна встреча втроём.", "fallback": True}
    a = tasks.meeting_agenda("П-02", sig)
    assert a["fallback"] and len(a["items"]) == 2
    o = tasks.meeting_outcomes(
        "Стажёр согласен сдавать работу после самопроверки с 16 ноября. Наставник будет давать обратную связь по пятницам. HR проведёт контрольную встречу 27 ноября.",
        "С-102",
        "Н-202",
    )
    assert [x["who"] for x in o["agreements"]] == ["Стажёр С-102", "Наставник Н-202", "HR"]
    assert o["agreements"][1]["when"] == "по пятницам"


def test_comment_quote_must_be_verbatim(fake_llm) -> None:
    text = "Нагрузка большая, обучения по оборудованию так и не было"
    fake_llm["CommentAnswer"] = {
        "topics": ["load", "xxx"],
        "tone": -0.6,
        "anxiety": 0.4,
        "quote": "Выдуманная цитата",
    }
    r = tasks.analyze_comment(text, 0.36)
    assert not r["fallback"] and r["topics"] == ["load"]
    assert r["quote"] in text
    fake_llm["CommentAnswer"]["quote"] = "обучения по оборудованию так и не было"
    assert tasks.analyze_comment(text, 0.36)["quote"] == "обучения по оборудованию так и не было"


def test_anxiety_is_max_of_model_and_rules(fake_llm) -> None:
    fake_llm["CommentAnswer"] = {"topics": [], "tone": 0.1, "anxiety": 0.2, "quote": ""}
    r = tasks.analyze_comment("Боюсь лишний раз спрашивать", 0.4)
    assert r["anxiety"] >= 0.5 and not r["fallback"]


def test_explain_rejects_invented_numbers(fake_llm) -> None:
    sig = [
        {
            "type": "lag",
            "description": "Наставник снижает оценки, стажёр не видит: 3 мес.",
            "cause": "Показать расхождение.",
        }
    ]
    fake_llm["TextAnswer"] = {"text": "Разрыв составляет 47%, это критично."}
    assert tasks.explain_signal("П-02", sig)["fallback"]
    fake_llm["TextAnswer"] = {
        "text": "Наставник уже 3 месяца видит спад, стажёр — нет. Начните с встречи втроём."
    }
    assert tasks.explain_signal("П-02", sig) == {
        "text": "Наставник уже 3 месяца видит спад, стажёр — нет. Начните с встречи втроём.",
        "fallback": False,
    }


def test_topic_rejects_unknown_codes(fake_llm) -> None:
    fake_llm["TopicAnswer"] = {"topic": "salary", "confidence": 0.9, "mirror": 9}
    assert tasks.map_question_topic("Хватает ли вам внимания наставника?", "intern", [])["fallback"]
    fake_llm["TopicAnswer"] = {"topic": "support", "confidence": 0.95, "mirror": 9}
    r = tasks.map_question_topic("Хватает ли вам внимания наставника?", "intern", ["a"])
    assert r == {"topic": "support", "confidence": 0.9, "mirror": 0, "fallback": False}


def test_outcomes_and_agenda_from_model(fake_llm) -> None:
    fake_llm["OutcomesAnswer"] = {"agreements": [{"who": "HR", "what": "встреча", "when": "27 ноября"}]}
    assert tasks.meeting_outcomes("текст", "С-1", "Н-1")["agreements"][0]["when"] == "27 ноября"
    fake_llm["AgendaAnswer"] = {"items": ["Пункт 1", "Пункт 2", "Пункт 3", "Пункт 4"]}
    assert tasks.meeting_agenda("П-01", [])["items"] == ["Пункт 1", "Пункт 2", "Пункт 3"]


def test_quote_keeps_original_case(fake_llm) -> None:
    text = "Всё нормально. Только непонятно, куда я расту"
    fake_llm["CommentAnswer"] = {
        "topics": ["growth"],
        "tone": -0.2,
        "anxiety": 0.7,
        "quote": "только непонятно, куда я расту",
    }
    assert tasks.analyze_comment(text, 0.78)["quote"] == "Только непонятно, куда я расту"
