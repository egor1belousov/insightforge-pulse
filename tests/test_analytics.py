from app.core.settings import DEFAULT_ANALYTICS
from app.services.analytics.core import (
    Comment,
    PairSeries,
    evaluate,
    personal_norm,
    program_signals,
    slope_of,
)

CFG = dict(DEFAULT_ANALYTICS)
P = [1, 2, 3, 4, 5, 6]


def series(
    intern: list[float], mentor: list[float], topics=("tasks", "auto"), comments=None, code="П-01"
) -> PairSeries:
    values = {
        "intern": {t: {p: v for p, v in zip(P, intern, strict=False) if v is not None} for t in topics},
        "mentor": {t: {p: v for p, v in zip(P, mentor, strict=False) if v is not None} for t in topics},
    }
    return PairSeries(1, code, P, values, comments or [])


def types(res) -> set[str]:
    return {s.type for s in res.signals}


def test_personal_norm_is_median_of_first_two() -> None:
    assert personal_norm({1: 0.4, 2: 0.6, 3: 0.9}, P) == 0.5
    assert personal_norm({3: 0.7}, P) == 0.7
    assert personal_norm({}, P) is None


def test_slope() -> None:
    assert abs(slope_of([(1, 0.1), (2, 0.2), (3, 0.3)]) - 0.1) < 1e-9
    assert slope_of([(1, 0.5)]) == 0.0


def test_healthy_pair_has_no_signals_and_high_index() -> None:
    ps = series([0.55, 0.62, 0.68, 0.74, 0.79, 0.83], [0.50, 0.60, 0.67, 0.73, 0.80, 0.84])
    res = evaluate(ps, 6, CFG)
    assert types(res) == set()
    assert res.state == "ok" and res.index >= 90


def test_level_uses_personal_norm() -> None:
    # Строгий наставник ставит на 0.3 ниже всё время — по сырым баллам разрыв, по личной шкале нет.
    strict = series([0.7] * 6, [0.4] * 6)
    assert "level" not in types(evaluate(strict, 6, CFG))
    # Наставник снижает оценки, стажёр — нет: по личной шкале разрыв два месяца подряд.
    diverge = series([0.6, 0.6, 0.6, 0.6, 0.6, 0.6], [0.6, 0.6, 0.5, 0.4, 0.3, 0.3])
    res = evaluate(diverge, 6, CFG)
    assert "level" in types(res)
    assert evaluate(diverge, 4, CFG).signals == [] or "level" not in types(evaluate(diverge, 4, CFG))


def test_growing_gap() -> None:
    ps = series([0.6, 0.62, 0.66, 0.72, 0.78, 0.84], [0.6, 0.6, 0.58, 0.55, 0.5, 0.45])
    res = evaluate(ps, 6, CFG)
    assert "growth" in types(res)
    sig = next(s for s in res.signals if s.type == "growth")
    assert sig.strength >= CFG["growth_slope"]


def test_lag_counts_months_without_reaction() -> None:
    ps = series([0.7, 0.7, 0.55, 0.5, 0.45, 0.4], [0.7, 0.7, 0.72, 0.74, 0.76, 0.78])
    res = evaluate(ps, 6, CFG)
    lag = next(s for s in res.signals if s.type == "lag")
    assert lag.facts["side"] == "intern" and lag.facts["blind"] == "mentor"
    assert lag.facts["months"] == 4 and res.lag_months == 4
    # Вторая сторона отреагировала — запаздывания больше нет.
    both = series([0.7, 0.7, 0.55, 0.5, 0.45, 0.4], [0.7, 0.7, 0.72, 0.55, 0.5, 0.45])
    assert "lag" not in types(evaluate(both, 6, CFG))


def test_words_vs_numbers() -> None:
    c = Comment(
        "intern",
        6,
        "Непонятно, будет ли предложение",
        anxiety=0.7,
        contradiction=0.7,
        tone=-0.3,
        quote="Непонятно",
        topics=["growth"],
    )
    ps = series([0.78] * 6, [0.76] * 6, comments=[c])
    res = evaluate(ps, 6, CFG)
    assert "words" in types(res) and res.state == "words"
    assert res.penalties["words"] == round(0.7 * CFG["w_words"], 1)
    calm = Comment("intern", 6, "Всё хорошо", anxiety=0.1, contradiction=0.0, tone=0.5)
    assert "words" not in types(evaluate(series([0.78] * 6, [0.76] * 6, comments=[calm]), 6, CFG))


def test_missing_questionnaire_is_separate_and_penalized() -> None:
    ps = series([0.6] * 6, [0.6, 0.6, 0.6, 0.6, 0.6, None])
    res = evaluate(ps, 6, CFG)
    assert res.missing == ["mentor"]
    assert "missing" in types(res)
    assert res.penalties["missing"] == CFG["w_missing"]


def test_index_formula_and_floor() -> None:
    ps = series([0.9, 0.9, 0.7, 0.5, 0.3, 0.1], [0.1, 0.1, 0.2, 0.4, 0.6, 0.9])
    res = evaluate(ps, 6, CFG)
    assert res.index == max(CFG["index_floor"], round(100 - sum(res.penalties.values())))
    assert res.index >= CFG["index_floor"]


def test_forecast_and_red_zone() -> None:
    ps = series([0.6, 0.62, 0.66, 0.72, 0.78, 0.84], [0.6, 0.6, 0.58, 0.55, 0.5, 0.45])
    res = evaluate(ps, 6, CFG)
    assert res.forecast is not None and res.forecast > res.abs_delta
    assert res.months_to_red is not None and res.months_to_red >= 0


def test_program_signal_needs_share_of_pairs() -> None:
    drop = [0.7, 0.7, 0.55, 0.55, 0.6, 0.6]
    flat = [0.7] * 6
    pairs = [series(drop, drop, code=f"П-0{i}") for i in range(1, 5)] + [series(flat, flat, code="П-05")]
    sig = program_signals(pairs, 3, CFG)
    assert sig and sig[0].facts["total"] == 5 and len(sig[0].facts["pairs"]) == 4
    assert program_signals(pairs[3:], 3, CFG) == []


def test_decline_when_both_drop() -> None:
    ps = series([0.58, 0.54, 0.48, 0.44, 0.40, 0.36], [0.56, 0.52, 0.47, 0.42, 0.38, 0.35])
    res = evaluate(ps, 6, CFG)
    assert "decline" in types(res) and res.state == "both"
