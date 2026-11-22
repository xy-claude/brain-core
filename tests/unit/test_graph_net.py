"""M4: the graph net inside recall. Off, recall is exactly as before; on, the claims around
the entities a question names join the ranking, with their path and a claims block."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from brain_core.journal import Journal
from brain_core.knowledge.net import GraphNet
from brain_core.knowledge.walk import Limits
from brain_core.recall import brain_recall
from brain_core.storage import Database, migrate
from brain_core.stores.index import RecordIndex
from brain_core.stores.vault import VaultStore

TODAY = date(2026, 12, 12)
LINES = [
    "[[Ride App]] —[USES: payments]→ [[Stripe]] (2026-10-01)",
    "[[Stripe]] —[RUNS_ON]→ [[AWS]] (2026-10-01)",
    "[[Ride App]] —[OWNS]→ [[Driver Portal]] (2026-10-05)",
]


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 12, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)  # every sync a little later, as a real clock
        return self.now


def setup(tmp: Path, *lines: str) -> VaultStore:
    j = Journal(tmp / "data" / "journal.db", clock=Clock())
    db = Database.connect(tmp / "data" / "brain.db")
    migrate(db)
    v = VaultStore(tmp / "vault", index=RecordIndex(db, j))
    v.root.mkdir(parents=True)
    (v.root / "relations.md").write_text("# Relations\n\n" + "".join(f"- {x}\n" for x in lines))
    (v.root / "facts.md").write_text(
        "# Facts\n\n## General\n"
        "- The ride app charges riders at the end of each trip (2026-10-02)\n"
    )
    v.read("fact", "sync")
    return v


def net(v: VaultStore, **lim: Any) -> GraphNet:
    assert v.claims is not None and v.index is not None
    return GraphNet(v.claims, v.index, Limits(**lim) if lim else None)


def test_off_recall_is_unchanged(tmp_path: Path) -> None:
    v = setup(tmp_path, *LINES)
    q = "what does the ride app use for payments?"
    plain = brain_recall([v], q, fmt="detailed", today=TODAY)
    assert "claims" not in plain and "graph" not in plain
    assert not any("graph" in r.get("found_by", []) for r in plain["results"])


def test_the_claims_around_a_named_entity_join_the_ranking(tmp_path: Path) -> None:
    v = setup(tmp_path, *LINES)
    out = brain_recall(
        [v], "what does the ride app use for payments?", fmt="detailed", today=TODAY,
        graph=net(v),
    )  # fmt: skip
    assert out["graph"]["seeds"] == ["ride app"]
    walked = {(c["claim"], c["hop"], c["validity"]) for c in out["claims"]}
    assert ("Ride App —USES(payments)→ Stripe", 1, "true") in walked
    assert ("Stripe —RUNS_ON→ AWS", 2, "true") in walked  # two hops out
    by_graph = [r for r in out["results"] if "graph" in r.get("found_by", [])]
    assert by_graph and all(r.get("path") for r in by_graph)
    assert any(r["path"] == "Ride App —USES(payments)→ Stripe" for r in by_graph)


def test_as_of_walks_only_what_was_true_that_day(tmp_path: Path) -> None:
    v = setup(tmp_path, *LINES)
    q = "what does the ride app use for payments?"
    before = brain_recall([v], q, today=TODAY, graph=net(v), as_of=date(2026, 9, 1))
    assert before["claims"] == [] and before["as_of"] == "2026-09-01"
    asked = brain_recall(
        [v], "what did the ride app use originally?", today=TODAY, graph=net(v),
        as_of=date(2026, 9, 1),
    )  # fmt: skip
    assert asked["graph"]["history"] and {c["validity"] for c in asked["claims"]} == {"unknown"}


def test_a_cut_walk_says_so(tmp_path: Path) -> None:
    v = setup(tmp_path, *LINES)
    out = brain_recall([v], "tell me about the ride app", today=TODAY, graph=net(v, fan=1))
    assert "fan" in out["graph"]["truncated"]
    assert out["graph"]["note"].startswith("graph expansion truncated (fan")


def test_a_question_naming_nothing_leaves_the_net_out(tmp_path: Path) -> None:
    v = setup(tmp_path, *LINES)
    out = brain_recall([v], "when do riders pay?", fmt="detailed", today=TODAY, graph=net(v))
    plain = brain_recall([v], "when do riders pay?", fmt="detailed", today=TODAY)
    assert "claims" not in out and out["results"] == plain["results"]


def test_as_of_keeps_a_value_replaced_later(tmp_path: Path) -> None:
    v = setup(tmp_path, *LINES)
    (v.root / "facts.md").write_text(
        "# Facts\n\n## General\n- The fare cap is 30 euros (2026-09-01)\n"
        "- The fare cap is 40 euros (2026-11-15)\n"
    )
    v.read("fact", "sync")
    recs = {r.text: r.id for r in v.read("fact", None, 10)}
    v.supersede(recs["The fare cap is 40 euros"], recs["The fare cap is 30 euros"])
    q = "what is the fare cap?"
    now = {r["text"]: r for r in brain_recall([v], q, today=TODAY)["results"]}
    assert now["The fare cap is 30 euros"].get("superseded")
    then = {
        r["text"]: r for r in brain_recall([v], q, today=TODAY, as_of=date(2026, 10, 1))["results"]
    }
    assert not then["The fare cap is 30 euros"].get("superseded")  # still the value on 10-01


def test_as_of_puts_that_days_value_first(tmp_path: Path) -> None:
    v = setup(tmp_path, *LINES)
    (v.root / "facts.md").write_text(
        "# Facts\n\n## General\n- The fare cap is 30 euros (2026-09-01)\n"
        "- The fare cap is 40 euros (2026-11-15)\n"
        "- **⚠ Fact changed 2026-11-20:** The night fare is 5 euros "
        "(was: The night fare is 3 euros)\n"
        "- The night fare is 3 euros (2026-08-01)\n"
    )
    v.read("fact", "sync")
    recs = {r.text: r.id for r in v.read("fact", None, 10)}
    v.supersede(recs["The fare cap is 40 euros"], recs["The fare cap is 30 euros"])

    def order(q: str, as_of: date | None) -> list[str]:
        return [r["text"] for r in brain_recall([v], q, today=TODAY, as_of=as_of)["results"]]

    now = order("what is the fare cap?", None)
    assert now.index("The fare cap is 40 euros") < now.index("The fare cap is 30 euros")
    then = order("what is the fare cap?", date(2026, 10, 1))
    assert then.index("The fare cap is 30 euros") < then.index("The fare cap is 40 euros")
    night = order("what is the night fare?", date(2026, 10, 1))  # the banner came later
    old = "The night fare is 3 euros"
    assert night.index(old) < next(i for i, t in enumerate(night) if "night fare is 5" in t)
    marked = brain_recall([v], "what is the night fare?", today=TODAY, as_of=date(2026, 10, 1))
    assert not next(r for r in marked["results"] if r["text"] == old).get("superseded")
