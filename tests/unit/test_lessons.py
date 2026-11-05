"""brain lessons: past corrections that match a prompt, by words alone, silent on a weak match."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from brain_core.agent import Agent
from brain_core.cli.main import app
from brain_core.lessons import MAX_LESSONS, lessons, render

runner = CliRunner()


def entry(day: str, title: str, error: str, rule: str, theme: str = "execution") -> str:
    return (
        f"### [{day}] {title}\n- **Error:** {error}\n- **Correction:** \n"
        f"- **Implied rule:** {rule}\n- **Theme:** {theme}\n- **Promoted:** No\n"
    )


CORRECTIONS = "## Corrections\n\n" + "\n".join(
    [
        entry(
            "2026-03-02",
            "Reported two accounts as separate without checking",
            "Said the two Google accounts were separate after seeing a password prompt.",
            "Before calling two accounts separate, open each account page and read its email.",
            "verification",
        ),
        entry(
            "2026-04-11",
            "Commit message repeated the previous subject",
            "The commit message first line duplicated the subject of the commit before it.",
            "Read the last commit subject before writing a new commit message.",
        ),
        entry(
            "2026-04-20",
            "Added a co-author trailer to the commit",
            "Added a co-author trailer and a long body to the commit message.",
            "One short subject line per commit message, no trailers.",
        ),
        entry(
            "2026-05-02",
            "Wrote a commit message that listed every file",
            "The commit message subject listed each file instead of the change.",
            "A commit message subject names the change, not the files.",
        ),
        entry(
            "2026-05-20",
            "Called the PDF export done without opening it",
            "Claimed the PDF export was done after glancing at the page count.",
            "Open the exported PDF and compare it to the source before saying it is finished.",
            "verification",
        ),
        entry(
            "2026-06-01",
            "Recommended an external tool before checking the stack",
            "Recommended installing an external memory tool without checking what was installed.",
            "Check what the current stack can do before recommending an external tool.",
            "self-awareness",
        ),
    ]
)


def test_an_on_topic_prompt_gets_its_correction_with_the_rule() -> None:
    hits = lessons(CORRECTIONS, "can you check whether those Google accounts are separate?")
    assert [h["title"] for h in hits] == ["Reported two accounts as separate without checking"]
    assert hits[0]["rule"].startswith("Before calling two accounts separate")
    # "accounts" and its naive singular are one word, not two
    assert hits[0]["shared"] == ["accounts", "google", "separate"]
    assert "[2026-03-02] Reported two accounts" in render(hits) and "open each account" in render(
        hits
    )


def test_weak_matches_stay_silent() -> None:
    assert lessons(CORRECTIONS, "what does it do before that, and why would you use it?") == []
    assert lessons(CORRECTIONS, "push") == []  # no shared subject word at all
    assert lessons(CORRECTIONS, "the PDF") == []  # one shared word is not a match, however rare
    assert lessons(CORRECTIONS, "accounts") == []  # a plural and its singular are one word
    # two stray words in a long request about something else: enough overlap, too little weight
    long = (
        "draft the onboarding email for the new cohort, mention the schedule, the venue, parking, "
        "lunch, the welcome talk, the laptop setup session, the mentor pairing, the reading list, "
        "the feedback form, and who to contact; keep the tone warm and the message under a page, "
        "then file it under the subject line we agreed on last week"
    )
    assert lessons(CORRECTIONS, long) == []
    assert lessons(CORRECTIONS, "") == [] and lessons("", "write the commit message") == []


def test_at_most_two_best_first() -> None:
    hits = lessons(CORRECTIONS, "write the commit message subject for this change")
    assert len(hits) == MAX_LESSONS and all("ommit" in h["title"] for h in hits)
    assert hits[0]["score"] >= hits[1]["score"]


def test_hook_injects_once_per_session_and_logs(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "bot", "--path", str(tmp_path), "--lite"])
    source = tmp_path / "vault" / "corrections.md"

    def hook(prompt: str, sid: str = "c1") -> str:
        r = runner.invoke(
            app,
            ["lessons", "--hook", "--path", str(tmp_path)],
            input=json.dumps({"session_id": sid, "prompt": prompt}),
        )
        assert r.exit_code == 0, r.stdout
        return r.stdout

    ask = "is the PDF export finished?"
    source.unlink(missing_ok=True)
    assert hook(ask) == ""  # no corrections file: silent
    source.write_text(CORRECTIONS, encoding="utf-8")
    out = json.loads(hook(ask))["hookSpecificOutput"]
    assert out["hookEventName"] == "UserPromptSubmit"
    assert "Called the PDF export done without opening it" in out["additionalContext"]
    assert "Open the exported PDF" in out["additionalContext"]
    assert hook(ask) == ""  # the same session is not told twice
    assert hook("what is the weather like today?") == ""
    assert "Called the PDF export" in hook(ask, sid="c2")  # another session is
    with Agent.from_config(tmp_path / "brain.yaml") as agent:
        logged = agent.recent_events(event_type="lessons_injected")
        assert len(logged) == 2
        assert logged[0].payload["titles"] == ["Called the PDF export done without opening it"]

    plain = runner.invoke(app, ["lessons", ask, "--path", str(tmp_path)])
    assert "Called the PDF export" in plain.stdout
    assert "shared: export, finished, pdf" in plain.stdout
    none = runner.invoke(app, ["lessons", "push", "--path", str(tmp_path)])
    assert none.stdout.strip() == "no correction matches"
