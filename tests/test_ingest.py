import json
from pathlib import Path

import pytest

from app.services.ingest.pipeline import analyze, build_records, profile_from_schema

ROOT = Path(__file__).parent / "fixtures" / "ingest"
VARIANTS = sorted(p.name for p in ROOT.iterdir() if p.is_dir())


def files_of(v: str) -> list[Path]:
    return [p for p in sorted((ROOT / v).iterdir()) if p.name != "expected.json"]


@pytest.mark.parametrize("variant", VARIANTS)
def test_variant_matches_expected(variant: str) -> None:
    exp = json.loads((ROOT / variant / "expected.json").read_text(encoding="utf-8"))
    schema = analyze(files_of(variant))

    sides = {t["file"]: t["side"] for t in schema["tables"]}
    assert sides == exp["files"]
    assert len(schema["asks"]) == exp["asks"], schema["asks"]
    assert sorted([p["intern"], p["mentor"]] for p in schema["pairs"]) == exp["pairs"]
    for side, n in exp["questions"].items():
        assert len(schema["questionnaires"][side]["questions"]) == n
    assert {i["type"] for i in schema["issues"]} >= set(exp["quality"])

    records = build_records(files_of(variant), schema)
    for side, n in exp["responses"].items():
        assert sum(1 for r in records if r.side == side) == n
    by = {(r.side, r.ext_id, r.period): r for r in records}
    qtopic = {q["key"]: q["topic"] for s in schema["questionnaires"].values() for q in s["questions"]}
    for s in exp["sample"]:
        r = by[(s["side"], s["id"], s["period"])]
        vals = [v for k, (_, v) in r.scores.items() if qtopic[k] == s["topic"]]
        assert vals and vals[0] == pytest.approx(s["norm"], abs=1e-3), (s, vals)


def test_mirrors_and_topics_v1() -> None:
    schema = analyze(files_of("v1"))
    intern = [q for q in schema["questionnaires"]["intern"]["questions"] if q["qtype"] != "text"]
    assert [q["topic"] for q in intern] == ["tasks", "auto", "support", "load", "feedback", "growth"]
    assert all(q["mirror"] for q in intern)


def test_comment_text_collected() -> None:
    schema = analyze(files_of("v4"))
    records = build_records(files_of("v4"), schema)
    texts = [t for r in records for t in r.texts.values()]
    assert any("боюсь" in t for t in texts)


def test_profile_reapplied_with_full_confidence() -> None:
    first = analyze(files_of("v3"))
    first["tables"][0]["columns"][-1]["role"] = "skip"
    second = analyze(files_of("v3"), profile=profile_from_schema(first))
    assert second["profile_applied"]
    assert all(t["side_conf"] == 1.0 for t in second["tables"])
    assert second["tables"][0]["columns"][-1]["role"] == "skip"


def test_v6_fixes_applied() -> None:
    schema = analyze(files_of("v6"))
    records = build_records(files_of("v6"), schema)
    assert not any(r.ext_id == "С-1О4" for r in records)
    assert sum(1 for r in records if r.ext_id == "С-102" and r.period == 4) == 1
    incomplete = [r for r in records if not r.complete]
    assert [(r.ext_id, r.period) for r in incomplete] == [("Н-204", 5)]


MGTS = Path(__file__).parent.parent / "data" / "mgts"


def test_mgts_case_recognized_without_questions() -> None:
    files = sorted(MGTS.iterdir())
    schema = analyze(files)
    assert schema["asks"] == []
    assert {t["file"]: t["side"] for t in schema["tables"]} == {
        "Ответы стажеров.xlsx": "intern",
        "Ответы наствников.xlsx": "mentor",
    }
    assert sorted((p["intern"], p["mentor"]) for p in schema["pairs"]) == [
        (f"СТ-00{i}", f"Н-00{i}") for i in range(1, 6)
    ]
    qs = schema["questionnaires"]
    kinds = {s: [q["qtype"] for q in qs[s]["questions"]] for s in qs}
    assert kinds == {"intern": ["scale"] * 7 + ["text"] * 2, "mentor": ["scale"] * 6 + ["text"] * 2}
    topics = {s: [q["topic"] for q in qs[s]["questions"] if q["qtype"] != "text"] for s in qs}
    assert topics["intern"] == ["tasks", "feedback", "load", "engage", "growth", "support", "overall"]
    assert topics["mentor"] == ["tasks", "overall", "auto", "load", "engage", "support"]
    assert sum(1 for q in qs["intern"]["questions"] if q["mirror"]) == 5

    records = build_records(files, schema)
    assert len(records) == 60 and all(r.complete for r in records)
    r = next(r for r in records if (r.side, r.ext_id, r.period) == ("intern", "СТ-004", 4))
    load = next(k for k, q in ((q["key"], q) for q in qs["intern"]["questions"]) if q["topic"] == "load")
    assert r.scores[load] == ("2", 0.25)
    assert len(r.texts) == 2 and r.department == "HR-блок"
