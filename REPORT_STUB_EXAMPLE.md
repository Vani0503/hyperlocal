# Hyperlocal sponsorship agent — evaluation report

> **STUB RUN.** The model was replaced by an offline heuristic to test plumbing. None of the quality, latency or cost numbers below are real. Re-run without `--stub`.

Agent model: `stub` · Judge: `stub:stub` · Cases: 20 · Date: 2026-11-11

## 1. Golden set (20 cases)

Mean check score **84%** · cases fully correct **5/20** · checks passed 210/246

| Case | Edge type | Score | Judge | Agent output |
|---|---|---|---|---|
| G01 | clean | 0.88 | 4 | Selected: E01 Bushwick Plant-Based Supper Club ($300, accept) | Spend $379 | Payment: release (product visible) |
| G02 | attendance_shortfall | 0.87 | 4 | Selected: E29 Midtown Whiskey Supper Club ($420, meet_ask) | Spend $499 | Payment: human_review (attendance below 50% of agreed guest count) |
| G03 | missing_budget | 1.00 | 4 | Paused for brand confirmation: ['missing:budget_total', 'missing:per_event_cap'] |
| G04 | no_alcohol_rule | 0.38 | — | Paused for brand confirmation: ['inconsistent:per_event_cap_exceeds_total_budget'] |
| G05 | wrong_brand_evidence | 0.71 | 4 | Selected: none | Spend $0 |
| G06 | clean | 0.85 | — | Selected: none | Spend $0 |
| G07 | clean | 0.86 | — | Selected: E05 Flushing Korean Home-Cooking Club ($250, accept) | Spend $317 | Payment: release (product visible) |
| G08 | ambiguous_evidence | 1.00 | 4 | Selected: E21 SoHo Sound Bath & Skincare Dinner ($300, meet_ask) | Spend $367 | Payment: human_review (unclear photos) |
| G09 | clean | 0.93 | — | Selected: E02 Sober Sunday Dinner ($250, accept) | Spend $323 | Payment: release (product visible) |
| G10 | clean | 0.77 | — | Selected: none | Spend $0 |
| G11 | host_ask_above_cap | 1.00 | 4 | Selected: none | Escalated: E23 (host asks $450, brand cap $400) | Spend $0 |
| G12 | clean | 0.77 | — | Selected: none | Spend $0 |
| G13 | opted_out_host | 0.92 | 4 | Selected: none | Spend $0 |
| G14 | clean | 0.93 | — | Selected: E24 Village Student Ramen Night ($150, accept) | Spend $235 | Payment: release (product visible) |
| G15 | late_submission | 0.93 | 4 | Selected: E26 Crown Heights Jollof Supper ($250, accept) | Spend $335 | Payment: human_review (evidence submitted after the agreed window) |
| G16 | clean | 1.00 | — | Selected: E15 Jackson Heights Healthcare Workers' Supper ($200, accept) | Spend $270 | Payment: release (product visible) |
| G17 | pii_in_evidence | 0.75 | 4 | Selected: none | Spend $0 |
| G18 | messy_brief | 0.50 | — | Paused for brand confirmation: ['missing:budget_total', 'missing:per_event_cap'] |
| G19 | inconsistent_budget | 0.75 | — | Paused for brand confirmation: ['inconsistent:per_event_cap_exceeds_total_budget'] |
| G20 | host_cancelled | 1.00 | 4 | Selected: E08 Chosen Family Dinner ($300, accept) | Spend $391 | Payment: cancel (host cancelled; release reserved budget, no payment) |

Team scores: fill `results/team_scores.csv` (score 1-5 + pass y/n per case), then re-run `python evals/run_evals.py --skip-tiers` to compute judge-vs-team agreement.

## 2. Cross-model judge on 10 cases

Cases: G01, G02, G03, G05, G08, G11, G13, G15, G17, G20. Judge is a different model family from the agent, to avoid self-preference.

- Agreement with **team scores**: _pending — team_scores.csv not filled yet_
- Agreement with **golden-check pass/fail**: 40% (n=10)

## 3. Two model tiers, same 10 tasks

| Model | Latency mean / p50 / max (s) | LLM calls/run | Tokens/run | Cost per 100 runs | Check score | Full-pass |
|---|---|---|---|---|---|---|
| `stub` | 0.0 / 0.0 / 0.0 | 2.5 | 1072 | $0.00 | 90% | 40% |

## 4. Top three failure patterns

**1. `extraction_error`** — 23 failed checks across 14 cases (G01, G02, G04, G05, G07, G09, G10, G12, G13, G14, G15, G17, G18, G19)
   - G01 extract.brand_name: got "We're", expected 'Leafline'
   - G01 extract.num_events: got 1, expected 3
   - G02 extract.brand_name: got 'Copper', expected 'Copper Hollow'
   - _Fix:_ Add few-shot examples for written-out numbers and relative dates; keep the rule gate that pauses on missing fields.

**2. `fit_underscored`** — 5 failed checks across 5 cases (G05, G06, G10, G12, G17)
   - G05 selected_a_best_fit_event: AI fit scores {'E04': [2, 'keyword overlap (stub)']}
   - G06 selected_a_best_fit_event: AI fit scores {'E07': [1, 'keyword overlap (stub)']}
   - G10 selected_a_best_fit_event: AI fit scores {'E22': [1, 'keyword overlap (stub)']}
   - _Fix:_ Give the fit prompt the brand's product use-case, not just audience; calibrate with 2 scored examples.

**3. `blocked_upstream_no_agreement`** — 5 failed checks across 5 cases (G05, G06, G10, G12, G17)
   - G05 payment_decision: no agreement was made, so payment step never ran
   - G06 payment_decision: no agreement was made, so payment step never ran
   - G10 payment_decision: no agreement was made, so payment step never ran
   - _Fix:_ Downstream symptom: fix the earlier step (fit/retrieval/extraction) that left the case with no agreement.

## 5. Economic value (per completed sponsorship)

Measured: 9 agreements across 20 cases; 8 items needed a person (confirmations, escalations, payment reviews/disputes) = 40% of cases.

| | AI agent + rules | Manual / agency |
|---|---|---|
| Avg host fee (paid to host) | $268.89 | $268.89 |
| Platform revenue (take rate 25%) | $67.22 | $67.22 |
| Coordination cost | $7.93 (LLM $0.0, people $7.93) | $140.0 |
| Payment processing | $10.05 | $10.05 |
| **Contribution margin** | **$49.25** | **$-82.82** |

Host earns ~$179.26/hour for the extra sponsorship work (assumes 1.5 h). A manual model only breaks even on host fees above ~$560, so small dinners are uneconomic by hand. That is the gap the agent closes. Assumptions are in `evals/economics.py`; replace them with pilot data.
