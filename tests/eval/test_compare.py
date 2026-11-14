"""compare.py: pairing by question and the exact McNemar p-value."""

from tests.eval.compare import compare, mcnemar


def test_mcnemar_exact_values() -> None:
    assert mcnemar(0, 0) == 1.0
    assert mcnemar(7, 4) == 0.548828125  # the 113-against-110 result: nowhere near significant
    assert mcnemar(6, 0) == 0.03125  # six clean wins is the least that passes 0.05
    assert mcnemar(5, 0) == 0.0625
    assert mcnemar(3, 3) == 1.0


def test_compare_pairs_by_question_and_slice() -> None:
    base = [
        {"q": "a", "s": "x", "hit": True},
        {"q": "b", "s": "x", "hit": False},
        {"q": "c", "s": "y", "hit": True},
    ]
    cand = [
        {"q": "b", "s": "x", "hit": True},
        {"q": "a", "s": "x", "hit": True},
        {"q": "c", "s": "y", "hit": False},
        {"q": "new", "s": "y", "hit": True},
    ]
    res = compare(base, cand)
    assert res["x"]["fixed"] == ["b"] and res["x"]["broken"] == []
    assert res["y"]["broken"] == ["c"]
    assert res["all"]["n"] == 3 and res["all"]["base"] == 2 and res["all"]["cand"] == 2
