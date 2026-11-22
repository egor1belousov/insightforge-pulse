"""Запись подтверждённой загрузки в базу."""

from sqlalchemy.orm import Session

from app.db.models import Answer, Pair, Participant, Program, Question, Questionnaire, Response, Topic
from app.services.ingest.pipeline import Record


def save_questionnaires(db: Session, program: Program, schema: dict) -> dict[str, dict[str, Question]]:
    """Создаёт новые версии анкет сторон с темами и зеркальными вопросами.

    Returns:
        Для каждой стороны: ключ вопроса из схемы → вопрос в БД.
    """
    topics = {t.code: t for t in db.query(Topic).filter(Topic.organization_id == program.organization_id)}
    out: dict[str, dict[str, Question]] = {}
    for side, qn in schema["questionnaires"].items():
        if not qn["questions"]:
            continue
        prev = db.query(Questionnaire).filter(
            Questionnaire.program_id == program.id, Questionnaire.side == side
        )
        version = max([q.version for q in prev] or [0]) + 1
        for q in prev:
            q.active = False
        qq = Questionnaire(
            program_id=program.id,
            side=side,
            version=version,
            source=qn.get("source", "import"),
            title=qn.get("title") or "",
        )
        db.add(qq)
        db.flush()
        out[side] = {}
        for i, q in enumerate(qn["questions"]):
            topic = topics.get(q.get("topic") or "")
            row = Question(
                questionnaire_id=qq.id,
                text=q["text"],
                qtype=q["qtype"],
                scale_min=q.get("min"),
                scale_max=q.get("max"),
                scale_labels=q.get("labels") or None,
                options=q.get("options") or None,
                topic_id=topic.id if topic else None,
                inverse=bool(q.get("inverse")),
                order=i,
                column_key=q["key"],
            )
            db.add(row)
            out[side][q["key"]] = row
    db.flush()
    for side, qn in schema["questionnaires"].items():
        other = "mentor" if side == "intern" else "intern"
        for q in qn["questions"]:
            if q.get("mirror") and side in out and other in out and q["mirror"] in out[other]:
                out[side][q["key"]].mirror_question_id = out[other][q["mirror"]].id
    return out


def persist(
    db: Session, program: Program, schema: dict, records: list[Record], source: str = "import"
) -> dict:
    """Записывает участников, пары, анкеты и ответы. Повторная загрузка заменяет анкеты тех же месяцев.

    Returns:
        Счётчики записанного.
    """
    qmap = save_questionnaires(db, program, schema)
    parts: dict[tuple[str, str], Participant] = {
        (p.side, p.external_id): p for p in db.query(Participant).filter(Participant.program_id == program.id)
    }
    dept: dict[str, str] = {}
    for r in records:
        if r.department:
            dept[r.ext_id] = r.department
    for p in schema["pairs"]:
        d = dept.get(p["intern"]) or dept.get(p["mentor"])
        if d:
            dept.setdefault(p["intern"], d)
            dept.setdefault(p["mentor"], d)

    def part(side: str, ext: str) -> Participant:
        key = (side, ext)
        if key not in parts:
            parts[key] = Participant(
                program_id=program.id, external_id=ext, side=side, department=dept.get(ext)
            )
            db.add(parts[key])
            db.flush()
        elif dept.get(ext) and not parts[key].department:
            parts[key].department = dept[ext]
        return parts[key]

    new_pairs = 0
    existing = {p.intern_participant_id: p for p in db.query(Pair).filter(Pair.program_id == program.id)}
    n = len(existing)
    for p in schema["pairs"]:
        i, m = part("intern", p["intern"]), part("mentor", p["mentor"])
        if i.id in existing:
            continue
        n += 1
        pair = Pair(
            program_id=program.id, code=f"П-{n:02d}", intern_participant_id=i.id, mentor_participant_id=m.id
        )
        db.add(pair)
        existing[i.id] = pair
        new_pairs += 1

    qn_ids = {side: next(iter(qs.values())).questionnaire_id for side, qs in qmap.items() if qs}
    written = 0
    for r in records:
        pt = part(r.side, r.ext_id)
        db.query(Response).filter(Response.participant_id == pt.id, Response.period == r.period).delete()
        resp = Response(
            participant_id=pt.id,
            questionnaire_id=qn_ids.get(r.side),
            period=r.period,
            source=source,
            complete=r.complete,
        )
        db.add(resp)
        qs = qmap.get(r.side, {})
        for key, (raw, val) in r.scores.items():
            if key in qs:
                resp.answers.append(Answer(question_id=qs[key].id, value_raw=raw, value_norm=val))
        for key, text in r.texts.items():
            resp.answers.append(Answer(question_id=qs[key].id if key in qs else None, text=text))
        written += 1
    db.commit()
    return {"responses": written, "pairs_new": new_pairs, "participants": len(parts)}
