from app.db.models import HealthSnapshot, Pair, Signal
from app.db.session import SessionLocal
from app.seed import seed_accounts, seed_demo_data


def _signals(db, period: int) -> dict[str, set[str]]:
    code = {p.id: p.code for p in db.query(Pair)}
    out: dict[str, set[str]] = {}
    for s in db.query(Signal).filter(Signal.period == period, Signal.pair_id.isnot(None)):
        out.setdefault(code[s.pair_id], set()).add(s.type)
    return out


def _zones(db, period: int) -> dict[str, str]:
    code = {p.id: p.code for p in db.query(Pair)}
    return {
        code[s.pair_id]: s.facts["zone"]
        for s in db.query(Signal).filter(Signal.period == period, Signal.pair_id.isnot(None))
    }


def test_mgts_history_reproduces_case_story() -> None:
    """История кейса МГТС: проблемы СТ-005 с начала, спад СТ-003, перегрузка СТ-004 в месяце 4."""
    with SessionLocal() as db:
        prog = seed_accounts(db)
        seed_demo_data(db, prog)
        pairs = {p.code: (p.intern.external_id, p.mentor.external_id) for p in db.query(Pair)}
        assert pairs["П-05"] == ("СТ-005", "Н-005") and pairs["П-06"] == ("СТ-006", "Н-006")

        m1, m3, m4 = _signals(db, 1), _signals(db, 3), _signals(db, 4)
        assert {"low", "gap"} <= m1["П-05"]
        assert {"decline", "low", "repeat"} <= m3["П-03"]
        assert {"low", "gap", "drop"} <= m4["П-04"]
        assert "П-02" not in _signals(db, 2) | m3 | m4
        assert _zones(db, 2)["П-05"] == "red" and _zones(db, 4)["П-04"] == "red"

        # к шестому месяцу все пары кейса выправились
        assert not _signals(db, 6)
        idx = {h.pair_id: h.index for h in db.query(HealthSnapshot).filter(HealthSnapshot.period == 6)}
        assert min(idx.values()) >= 80
        quote = next(
            s for s in db.query(Signal).filter(Signal.type == "repeat", Signal.period == 3)
        ).description
        assert "переделывать" in quote
