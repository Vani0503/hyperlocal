# Hyperlocal — AI agent for small brand sponsorships

An agent that takes a brand's free-text brief, finds fitting NYC dinner parties and supper clubs, prices and
negotiates within the brand's limits, drafts host offers, plans shipping, then checks the host's evidence and
decides whether to release payment. Rules handle money, eligibility, privacy and payment. AI is used only where
judgment is needed.

## Web app (Streamlit)

```bash
pip install -r requirements.txt
streamlit run app.py            # opens http://localhost:8501
```
The app reads the API key from `.streamlit/secrets.toml` (copy `secrets.toml.example`), from the `ANTHROPIC_API_KEY` env var,
or from the sidebar. With no key it runs in demo mode using an offline stand-in for the AI. Public visitors are capped at 15
paid runs per session (`MAX_RUNS_PER_SESSION` in `app.py`).

## Run it from the command line

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # agent (Haiku 5.5 + Sonnet 5.5)
export OPENAI_API_KEY=...           # cross-model judge (different model family)

python run.py --case G01 --trace                       # one golden case, every step shown
python run.py --brief "Brew Theory coffee, 2 brunches in Brooklyn in Jan 2027, \$600 total, \$250 cap"
python evals/run_evals.py                              # everything below -> REPORT.md + results/
```

- No OpenAI key? Run `python evals/run_evals.py --judge-provider anthropic --judge-model claude-opus-5-5`. The judge is then the same vendor but a different tier, so say so in your write-up.
- Smoke test with no keys: `python evals/run_evals.py --stub`. It uses a heuristic stand-in for the model, so the numbers mean nothing.
- Check that the rules and golden labels agree: `python evals/oracle_check.py`. With perfect AI answers, all 20 cases score 100%.
- Before running, check the judge model ID (`JUDGE_MODEL` in `hyperlocal/config.py`, or as an env var) against your OpenAI account.

## How it maps to the criteria

### 1. Runs end to end on real inputs
`run.py` takes any free-text brief (plus optional evidence JSON) and runs all 5 steps: brief → structured fields →
eligible events → fit scores → priced agreements and escalations → offer messages → shipping plan →
payment decision. Every step is logged in the trace, tagged `AI` or `RULE`.
*Data note:* `data/events.json` holds 30 listings modelled on real NYC supper-club formats. They are not scraped.
Replace them with real listings (hand-pulled for the pilot) and nothing else needs to change.

### 2. AI only where judgment is needed
| Step | AI (judgment) | Rules (deterministic, in `rules.py`) |
|---|---|---|
| 1 Capture | Turns a messy brief into fields ("two thousand", "next Jan") | Schema check; pause if a budget, cap or date is missing or inconsistent |
| 2 Find | Scores community fit, 0–5 with a reason | Dates, borough, freshness, opt-outs, min guests, 21+/alcohol and no-alcohol rules, dedupe, BM25 ranking |
| 3 Negotiate | Writes the host offer | Fee formula, cap, one counter round, then escalate; budget reserve; offer guard (exact fee, can-decline line, no guest data); template fallback |
| 4 Execute | — | Ship-by date, one order per event, proof-approval rule, host checklist |
| 5 Verify and pay | Judges whether the evidence shows *this* brand's product | Cancellation, 14-day window, attendance below 50%, PII redaction, confidence threshold → release / review / dispute |

The model never decides an amount and never releases money on its own.

### 3. One knowledge source: the event catalog, retrieved rather than put in context
See the docstring in `hyperlocal/knowledge.py`. The catalog is the one input that grows without limit and changes
daily. Each brief needs about 5 rows out of thousands, so the agent filters by rule, ranks with BM25, and puts
only the top 6 into the prompt. The brief, rules and agreement are small and needed by every step, so they
go in context.

### 4. Evals
- **20 golden cases** (`data/golden.json`) with expected fields, must-pick and must-not-pick events, escalations
  and payment decisions. They cover clean cases plus 11 edge types: missing budget, inconsistent budget,
  messy brief, alcohol and no-alcohol rules, opted-out host, host ask above the cap, competitor product in
  evidence, blurry evidence, late evidence, low attendance, guest PII in the evidence, host cancellation.
- **Auto-scoring** (`evals/scoring.py`): about 12 checks per case, each tagged with a failure category.
- **Team scores:** `results/team_scores.csv` is generated with the agent's output summarised for each case. Your team scores
  each case 1–5 and pass y/n, then re-runs `python evals/run_evals.py --skip-tiers`.
- **Cross-model judge on 10 cases**, with agreement against team scores (pass/fail, exact, within ±1) and
  against the golden checks.
- **Top 3 failure patterns**, grouped from failed-check categories and each paired with a fix.

### 5. Two model tiers on the same 10 tasks
Haiku 5.5 ($0.10 / $0.50 per M tokens) and Sonnet 5.5 ($2 / $10). The report gives mean, p50 and max latency,
cost per 100 runs from measured token usage, and quality. The trade-off rule is: take the cheaper tier unless
quality drops by more than 5 points. That is safe here because the costly mistakes (money, eligibility,
payment) are made by rules, not the model.

### 6. Economic value
A small sponsorship pays a host about $150–450. Coordinating one by hand takes about 3.5 hours of ops time
(find, agree, ship, verify, pay), roughly $140. At a 25% take rate, a manual operator only breaks even on fees
of about $560 or more, which is why brands only do big pop-ups. The agent cuts coordination to cents of model
cost plus a few minutes of a person's time on exceptions, so the platform keeps a positive margin per
sponsorship. Value goes three ways:
- **Brands** get intimate, targeted placements at a predictable cost, with proof it happened.
- **Hosts** get paid for about 1.5 hours of extra work, on time, with no guest data shared.
- **The platform** earns its margin from a market that can't be served by hand.

`evals/economics.py` computes this from the eval run (measured model cost and measured rate of human
touches). The take rate, ops wage and hours are labelled assumptions to replace with pilot data. The north-star
metric is still repeat purchase by brands; this model only shows the unit economics can work.

## Files
```
run.py                  CLI: one brief end to end
hyperlocal/agent.py     5-step workflow (AI vs RULE tagged)
hyperlocal/rules.py     every deterministic decision
hyperlocal/knowledge.py event catalog + BM25 retrieval (and why)
hyperlocal/prompts.py   extraction, fit, offer, evidence, judge prompts
hyperlocal/config.py    models, prices, thresholds
data/events.json        knowledge source (30 NYC listings)
data/golden.json        20 golden cases + expected outputs
evals/run_evals.py      golden run, judge, tiers, failure patterns, economics -> REPORT.md
evals/oracle_check.py   proves rules and labels are consistent
```
