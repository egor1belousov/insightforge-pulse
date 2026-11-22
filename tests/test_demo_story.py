from app.db.models import HealthSnapshot, Pair, Signal
from app.db.session import SessionLocal
from app.seed import seed_accounts, seed_demo_data


def test_demo_data_reproduces_story() -> None:
    with SessionLocal() as db:
        prog = seed_accounts(db)
        seed_demo_data(db, prog)
        pairs = {p.code: p.id for p in db.query(Pair)}
        idx = {h.pair_id: h.index for h in db.query(HealthSnapshot).filter(HealthSnapshot.period == 6)}
        sig = {}
        for s in db.query(Signal).filter(Signal.period == 6, Signal.pair_id.isnot(None)):
            sig.setdefault(s.pair_id, set()).add(s.type)
        assert idx[pairs["П-01"]] >= 90 and not (sig.get(pairs["П-01"], set()) - {"missing"})
        assert {"level", "growth", "lag"} <= sig[pairs["П-02"]]
        assert {"level", "lag"} <= sig[pairs["П-03"]]
        assert {"decline", "missing"} <= sig[pairs["П-04"]]
        assert "words" in sig[pairs["П-05"]]
        program = db.query(Signal).filter(Signal.pair_id.is_(None), Signal.type == "program").all()
        assert {s.topic for s in program} >= {"support", "load"}
