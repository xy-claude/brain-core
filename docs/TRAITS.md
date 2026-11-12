# The twelve traits

A brain-core agent is born with twelve traits and grows them with experience. **Innate** means it ships with `brain init` and survives a cold start with the vault wiped. **Grown** means it accumulates in the vault. `brain_status()["traits"]` scores each trait from evidence on disk; `brain daily` writes a Traits section into the brief and one line into `health_log.md`, so the curve is visible over weeks.

The list comes from three literatures that agree more than they disagree: the classical cognitive architectures (ACT-R, Soar, CLARION, LIDA, the Standard Model) and CoALA for the memory stores; Miyake and Friedman and Diamond for which control functions are separable; Nelson and Narens and Fleming and Lau for how metacognition is measured. Of a typical fourteen-item "intelligence dashboard", only four name faculties any architecture builds; the rest are behaviours or outcome metrics. The full research is summarised at the end.

## The list

| # | Trait | Innate (ships at init) | Grown (in the vault) |
|---|---|---|---|
| 1 | Working memory | `brain_session('start')` and the memory rule that fixes what loads | the daily brief, the warmup, the facts the start block pulls |
| 2 | Episodic memory | `brain_session('end')` writes the dated archive; the weekly archive job | `sessions/YYYY-MM-DD.md` and monthly summaries |
| 3 | Semantic memory | the vault schema, `brain_remember`, `brain_recall`, the SQLite and vector indexes | facts, knowledge pages, decisions, vector entries |
| 4 | Procedural memory | the five rule files and the tool schemas | procedures, skills, rules promoted from corrections |
| 5 | Learning | dedup and contradiction rules, the correction format, `brain_distill` | corrections and themes, Fact-changed banners, promoted rules |
| 6 | Reasoning and planning | the reasoning checklist in the identity rule | mission decompositions; little else persists |
| 7 | Decision | the classification matrix in the doctrine rule | decisions with classification and confidence |
| 8 | Metacognition | the confidence field, the citation rule, the critique template | decisions paired with outcomes, critiques |
| 9 | Execution | the tool schemas, the write journal, the handoff format | per-layer write history, handoffs, cron output |
| 10 | Goal management | the mission queue schema, the priority order | the mission queue, executive state, proposals and verdicts |
| 11 | User model | the user-profile template, the output-style rule | the profile, preferences, tone and format corrections |
| 12 | Authority | the authority rule: the boundary and the escalation format | the pending queue, logged approvals, the trust level |

Memory is three stores, never one. On the LoCoMo benchmark a frontier model scores 10 on temporal questions against 93 for humans, and unanswerable questions collapse as context grows; a single recall hit-rate hides all of that.

## How a trait is scored

A trait never gets one number. It gets signals, each with a value, a sample size `n`, and a verdict:

- **defensible**: the answer key comes from a file the agent did not write in the same session. Dated archives, the event journal, the user's corrections, the mission queue's review dates. These are the signals worth watching.
- **cost**: a size or an age. Useful to know, says nothing about quality.
- **pending**: the evidence does not exist yet. Resolved decisions for calibration, the stratified recall eval, the harness event log for boundary violations.

Ratios are reported as counts until `n` reaches 20. One agent accumulates perhaps five to twenty resolved decisions a month, so a percentage on three items is noise.

| Trait | Defensible signal today | Direction |
|---|---|---|
| Working memory | sessions with writes that opened with `brain_session('start')` | higher |
| Episodic memory | the temporal slice of the recall eval (a question about a day surfaces that day's archive), from the last `run_recall.py --out data/eval.json` or `run_gold.py --out data/eval.json` | higher |
| Semantic memory | the single-hop, multi-hop, knowledge-update and abstention slices of the same eval; facts carrying a date; knowledge pages that cite a raw source | higher |
| Procedural memory | procedures validated in the last 30 days | higher |
| Learning | corrections on a theme after its rule was promoted; old values reappearing after a Fact-changed banner | lower |
| Reasoning and planning | the same write repeated three times in a row in one session | lower |
| Decision | decisions carrying a classification | higher |
| Metacognition | distinct confidence levels used; one level everywhere means the field is decorative | higher |
| Execution | `brain_remember` calls that failed or were refused | lower |
| Goal management | open missions not reviewed for 14 days | lower |
| User model | recent corrections about tone, format or delivery | lower |
| Authority | reversible low-risk items parked in the pending queue | lower |

What is deliberately not a signal: artefact counts (facts written, pages compiled, retains per session), an unstratified recall rate once it passes 90 percent, expected-calibration-error on three confidence words, and any score the agent writes about itself. Each of those is an activity the agent controls on both sides.

## What grows it

The growth levers are in the product and run without the agent remembering to run them.

- **The daily brief's Growth section.** Three read-only nudges written by `brain daily`: a correction theme that recurred since its rule was promoted (the rule is not landing), a mission not reviewed for fourteen days (advance it, block it with a reason, or drop it), and a pending decision that has waited fourteen days (ask again, or decide it is not needed). The brief keeps the first-seen date per pending decision in `data/pending_seen.json`, so age is real and not self-reported.
- **Session deltas.** `brain_session('start')` snapshots every defensible signal; `brain_session('end')` returns `traits_moved`, the signals that changed during the session, and notes the count in the day's close line. A session that moved nothing is visible as such.
- **Calibration.** Once decisions resolve, metacognition reports a Brier score of stated confidence against outcome. A later correction that names the decision is a miss, thirty days without one is a hold, younger decisions are censored and never counted as held. Zero is perfect, a quarter is chance.
- **The pipeline itself.** The correction pipeline that promotes a repeated theme into a rule is the training effect on procedural memory. The Fact-changed banner plus the leak check keeps semantic memory honest. The stratified eval is the growth test for the three memory stores: the same vault at day one and after thirty days of sessions, where every defensible signal must move in its direction, and CI holds that line.

## Where the list came from

The candidate list was fourteen dashboard categories: Memory, Reasoning, Decision, Execution, Learning, Context, Structural, Communication, Meta, Agency, Prioritization, Initiative, Delegation, Goal Progression. The research verdict:

- **Faculties** the architectures build: Memory (as three stores), Decision, Learning, Meta (renamed Metacognition), Context (renamed Working memory), Execution.
- **Behaviours** that emerge from faculties, folded in: Reasoning (kept, absorbs planning), Communication (into User model), Prioritization and Initiative and Goal Progression (into Goal management), Delegation (into Execution), Agency (replaced by Authority, which is measurable).
- **Not cognition**: Structural is the integrity of the architecture and stays as the health line in `brain status`.
- **Added**: Procedural memory, User model, Authority.

Sources that carry the taxonomy: Sumers et al., *Cognitive Architectures for Language Agents* (2023); Miyake and Friedman, *The Nature and Organization of Individual Differences in Executive Functions* (2012) with Diamond, *Executive Functions* (2013); Fleming and Lau, *How to Measure Metacognition* (2014) with Nelson and Narens (1990). Benchmarks that shaped the signals: LoCoMo, LongMemEval, tau-bench's pass^k, and Anthropic's 2026 guidance on evals for agents.
