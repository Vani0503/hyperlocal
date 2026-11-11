"""Full evaluation: 20 golden cases, cross-model judge on 10 + agreement rate,
two model tiers on the same 10 tasks, top-3 failure patterns, unit economics.
Writes results/*.json, results/team_scores.csv and REPORT.md.

  python evals/run_evals.py                     # real run (needs ANTHROPIC_API_KEY, OPENAI_API_KEY)
  python evals/run_evals.py --stub              # offline plumbing check, numbers meaningless
  python evals/run_evals.py --judge-provider anthropic --judge-model claude-opus-5-5   # no OpenAI key
"""
import argparse, csv, json, statistics as st, sys, time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "evals"))
from hyperlocal import agent, config as C, prompts as P
from hyperlocal.llm import LLM, CallLog
from hyperlocal.knowledge import DATA, load_events
from scoring import score_case, summarize
import economics

JUDGE_CASES = ["G01", "G02", "G03", "G05", "G08", "G11", "G13", "G15", "G17", "G20"]  # diverse: clean + every edge type
RES = ROOT / "results"


LOG = print


def run_cases(cases, model, today, events):
    rows = []
    for c in cases:
        llm = LLM(model, log=CallLog())
        t = time.time()
        try:
            out = agent.run(c["brief"], c["evidence"], today=today, llm=llm, events=events)
            err = None
        except Exception as e:  # a crash is a failed case, not a crashed eval
            out, err = {"status": "error", "brief": {}, "trace": [], "usage": llm.log.totals()}, repr(e)
        wall = time.time() - t
        sc = score_case(c, out) if not err else {"score": 0.0, "passed_all": False,
                                                 "checks": [{"check": "ran", "category": "crash", "pass": False, "detail": err}]}
        rows.append({"id": c["id"], "tags": c["tags"], "model": model, "wall_s": round(wall, 3),
                     **out["usage"], **sc, "summary": summarize(out) if not err else err, "output": out})
        LOG(f"  {model:20s} {c['id']}  score={sc['score']:.2f}  {wall:5.1f}s  ${out['usage']['cost_usd']:.4f}")
    return rows


def judge(rows_by_id, cases_by_id, provider, model):
    jl = LLM(model, provider=provider, log=CallLog())
    out = {}
    for cid in JUDGE_CASES:
        r, c = rows_by_id[cid], cases_by_id[cid]
        o = r["output"]
        cand = next((t for t in o.get("trace", []) if t["step"].startswith("2c")), {}).get("scores", {})
        ev = {e["id"]: e for e in load_events()}
        payload = {
            "brand_brief": c["brief"],
            "agent_extracted_brief": {k: v for k, v in o.get("brief", {}).items() if k != "audience_keywords"},
            "agent_status": o["status"], "issues": o.get("issues"),
            "candidate_events_considered": {i: {"title": ev[i]["title"], "description": ev[i]["description"],
                                                "agent_fit": s} for i, s in cand.items()},
            "agreements": [{k: a[k] for k in ("event_id", "title", "host_fee", "negotiation", "offer_message")}
                           for a in o.get("agreements", [])],
            "escalations": o.get("escalations"), "spend": o.get("spend"),
            "host_evidence": c["evidence"], "payment": o.get("payment"),
        }
        try:
            j = jl.complete_json(P.JUDGE_SYS, json.dumps(payload, default=str), "judge", 2000)
        except Exception as e:
            j = {"score": None, "pass": None, "reason": f"judge error {e!r}"}
        out[cid] = j
        LOG(f"  judge {cid}: {j.get('score')} {j.get('reason', '')[:70]}")
    return out, jl.log.totals()


def read_team_scores(path):
    if not path.exists():
        return {}
    t = {}
    for row in csv.DictReader(open(path)):
        s = (row.get("team_score_1to5") or "").strip()
        if s:
            t[row["case_id"]] = {"score": int(s), "pass": (row.get("team_pass") or "").strip().lower() in ("y", "yes", "1", "true") or int(s) >= 4}
    return t


def write_team_sheet(rows, path):
    if path.exists():
        return
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "brief", "agent_output_summary", "team_score_1to5", "team_pass", "notes"])
        cases = {c["id"]: c for c in json.load(open(DATA / "golden.json"))["cases"]}
        for r in rows:
            w.writerow([r["id"], cases[r["id"]]["brief"].replace("\n", " "), r["summary"], "", "", ""])


def agreement(judge_scores, ref):
    pairs = [(judge_scores[i], ref[i]) for i in judge_scores if i in ref and judge_scores[i].get("score") is not None]
    if not pairs:
        return None
    n = len(pairs)
    res = {"n": n, "pass_fail_agreement": round(sum(bool(j["pass"]) == bool(r["pass"]) for j, r in pairs) / n, 3)}
    if all("score" in r for _, r in pairs):
        res["exact_score_agreement"] = round(sum(j["score"] == r["score"] for j, r in pairs) / n, 3)
        res["within_1_agreement"] = round(sum(abs(j["score"] - r["score"]) <= 1 for j, r in pairs) / n, 3)
    return res


def tier_stats(rows):
    w = [r["wall_s"] for r in rows]
    return {"model": rows[0]["model"], "n": len(rows),
            "latency_mean_s": round(st.mean(w), 2), "latency_p50_s": round(st.median(w), 2),
            "latency_max_s": round(max(w), 2), "llm_calls_per_run": round(st.mean(r["llm_calls"] for r in rows), 1),
            "tokens_per_run": round(st.mean(r["input_tokens"] + r["output_tokens"] for r in rows)),
            "cost_per_100_runs_usd": round(100 * st.mean(r["cost_usd"] for r in rows), 4),
            "quality_mean_check_score": round(st.mean(r["score"] for r in rows), 3),
            "quality_full_pass_rate": round(sum(r["passed_all"] for r in rows) / len(rows), 3)}


def failure_patterns(rows):
    agg = defaultdict(lambda: {"count": 0, "cases": set(), "examples": []})
    for r in rows:
        for c in r["checks"]:
            if not c["pass"]:
                a = agg[c["category"]]; a["count"] += 1; a["cases"].add(r["id"])
                if len(a["examples"]) < 3: a["examples"].append(f"{r['id']} {c['check']}: {c['detail']}")
    top = sorted(agg.items(), key=lambda kv: (-len(kv[1]["cases"]), -kv[1]["count"]))
    return [{"pattern": k, "failed_checks": v["count"], "cases": sorted(v["cases"]), "examples": v["examples"]} for k, v in top]


FIX_HINTS = {
    "extraction_error": "Add few-shot examples for written-out numbers and relative dates; keep the rule gate that pauses on missing fields.",
    "fit_underscored": "Give the fit prompt the brand's product use-case, not just audience; calibrate with 2 scored examples.",
    "fit_overmatch": "Raise FIT_THRESHOLD to 4 when num_events > eligible strong fits, or ask the model to rank and justify the 3rd pick.",
    "retrieval_miss": "Expand the BM25 query with product-category synonyms or raise RETRIEVAL_TOP_K; add tags to listings.",
    "evidence_judgment_error": "Require photo evidence to name the brand; route any competitor mention to dispute by rule before AI.",
    "offer_guard_fallback": "Put the guard's rules verbatim in the offer prompt; the template fallback keeps it safe meanwhile.",
    "intake_gate_error": "Tighten the extraction prompt's 'never invent numbers' rule; add validation for implied totals.",
    "blocked_upstream_no_agreement": "Downstream symptom: fix the earlier step (fit/retrieval/extraction) that left the case with no agreement.",
    "wrong_event_selected": "Encode the missed constraint as a rule in rules.eligibility rather than trusting the model.",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stub", action="store_true")
    ap.add_argument("--model", default=C.MAIN_MODEL)
    ap.add_argument("--fast", default=C.FAST_MODEL); ap.add_argument("--strong", default=C.STRONG_MODEL)
    ap.add_argument("--judge-provider", default=C.JUDGE_PROVIDER); ap.add_argument("--judge-model", default=C.JUDGE_MODEL)
    ap.add_argument("--skip-judge", action="store_true"); ap.add_argument("--skip-tiers", action="store_true")
    evaluate(ap.parse_args())


def evaluate(a, log=print):
    global LOG
    LOG = log
    if a.stub:
        a.model = a.fast = a.strong = a.judge_model = "stub"; a.judge_provider = "stub"
    RES.mkdir(exist_ok=True)
    g = json.load(open(DATA / "golden.json")); cases = g["cases"]; by_id = {c["id"]: c for c in cases}
    events = load_events()

    log(f"[1/4] 20 golden cases on {a.model}")
    main_rows = run_cases(cases, a.model, g["today"], events)
    json.dump(main_rows, open(RES / f"golden_{a.model}.json", "w"), indent=1, default=str)
    write_team_sheet(main_rows, RES / "team_scores.csv")
    rows_by_id = {r["id"]: r for r in main_rows}

    judge_scores, judge_usage, agree_team, agree_auto = {}, None, None, None
    if not a.skip_judge:
        log(f"[2/4] cross-model judge ({a.judge_provider}:{a.judge_model}) on 10 cases")
        judge_scores, judge_usage = judge(rows_by_id, by_id, a.judge_provider, a.judge_model)
        team = read_team_scores(RES / "team_scores.csv")
        agree_team = agreement(judge_scores, team)
        auto = {i: {"pass": rows_by_id[i]["passed_all"]} for i in JUDGE_CASES}
        agree_auto = agreement(judge_scores, auto)
        json.dump({"judge": judge_scores, "usage": judge_usage, "agreement_vs_team": agree_team,
                   "agreement_vs_golden_checks": agree_auto}, open(RES / "judge.json", "w"), indent=1)

    tiers = []
    if not a.skip_tiers:
        log(f"[3/4] tier comparison on the same 10 tasks: {a.fast} vs {a.strong}")
        ten = [by_id[i] for i in JUDGE_CASES]
        for m in dict.fromkeys([a.fast, a.strong]):
            rows = [rows_by_id[i] for i in JUDGE_CASES] if m == a.model else run_cases(ten, m, g["today"], events)
            tiers.append(tier_stats(rows))
            json.dump(rows, open(RES / f"tier_{m}.json", "w"), indent=1, default=str)

    log("[4/4] failure patterns + economics + report")
    fp = failure_patterns(main_rows)
    ag = [x for r in main_rows for x in r["output"].get("agreements", [])]
    touches = sum((r["output"]["status"] == "needs_confirmation") + len(r["output"].get("escalations", []))
                  + ((r["output"].get("payment") or {}).get("decision") in ("human_review", "dispute")) for r in main_rows)
    econ = economics.model(avg_host_fee=st.mean(x["host_fee"] for x in ag) if ag else 0,
                           llm_cost_per_case=st.mean(r["cost_usd"] for r in main_rows),
                           human_touch_rate=touches / len(main_rows), agreements_per_case=len(ag) / len(main_rows))
    write_report(a, main_rows, judge_scores, agree_team, agree_auto, tiers, fp, econ, touches, len(ag))
    log(f"done -> {ROOT / 'REPORT.md'}")
    return ROOT / "REPORT.md"


def write_report(a, rows, js, at, aa, tiers, fp, econ, touches, n_ag):
    L = []
    w = L.append
    w("# Hyperlocal sponsorship agent — evaluation report\n")
    if a.stub:
        w("> **STUB RUN.** The model was replaced by an offline heuristic to test plumbing. "
          "None of the quality, latency or cost numbers below are real. Re-run without `--stub`.\n")
    w(f"Agent model: `{a.model}` · Judge: `{a.judge_provider}:{a.judge_model}` · Cases: {len(rows)} · "
      f"Date: {time.strftime('%Y-%m-%d')}\n")
    mean = st.mean(r["score"] for r in rows); full = sum(r["passed_all"] for r in rows)
    w("## 1. Golden set (20 cases)\n")
    w(f"Mean check score **{mean:.0%}** · cases fully correct **{full}/20** · "
      f"checks passed {sum(c['pass'] for r in rows for c in r['checks'])}/{sum(len(r['checks']) for r in rows)}\n")
    w("| Case | Edge type | Score | Judge | Agent output |\n|---|---|---|---|---|")
    for r in rows:
        j = js.get(r["id"], {})
        w(f"| {r['id']} | {', '.join(r['tags'])} | {r['score']:.2f} | {j.get('score', '—')} | {r['summary'][:140]} |")
    w("\nTeam scores: fill `results/team_scores.csv` (score 1-5 + pass y/n per case), then re-run "
      "`python evals/run_evals.py --skip-tiers` to compute judge-vs-team agreement.\n")
    w("## 2. Cross-model judge on 10 cases\n")
    if js:
        w(f"Cases: {', '.join(JUDGE_CASES)}. Judge is a different model family from the agent, to avoid self-preference.\n")
        w(f"- Agreement with **team scores**: " + (f"pass/fail {at['pass_fail_agreement']:.0%}, exact {at.get('exact_score_agreement', 0):.0%}, "
                                                   f"within ±1 {at.get('within_1_agreement', 0):.0%} (n={at['n']})" if at else
                                                   "_pending — team_scores.csv not filled yet_"))
        w(f"- Agreement with **golden-check pass/fail**: " + (f"{aa['pass_fail_agreement']:.0%} (n={aa['n']})" if aa else "—"))
        w("")
    w("## 3. Two model tiers, same 10 tasks\n")
    if tiers:
        w("| Model | Latency mean / p50 / max (s) | LLM calls/run | Tokens/run | Cost per 100 runs | Check score | Full-pass |\n|---|---|---|---|---|---|---|")
        for t in tiers:
            w(f"| `{t['model']}` | {t['latency_mean_s']} / {t['latency_p50_s']} / {t['latency_max_s']} | {t['llm_calls_per_run']} | "
              f"{t['tokens_per_run']} | ${t['cost_per_100_runs_usd']:.2f} | {t['quality_mean_check_score']:.0%} | {t['quality_full_pass_rate']:.0%} |")
        if len(tiers) == 2:
            f_, s_ = tiers
            gap = s_["quality_mean_check_score"] - f_["quality_mean_check_score"]
            ratio = s_["cost_per_100_runs_usd"] / f_["cost_per_100_runs_usd"] if f_["cost_per_100_runs_usd"] else float("nan")
            choice = f_["model"] if gap <= 0.05 else s_["model"]
            w(f"\n**Trade-off:** the strong tier scores {gap:+.0%} on checks at {ratio:.1f}× the cost. "
              f"Decision rule: take the cheaper tier unless the quality gap exceeds 5 points → **{choice}**. "
              "Money, eligibility and payment are rules, so a cheaper model's mistakes land in fit and evidence "
              "judgment, where a person already reviews low-confidence cases.\n")
    w("\n## 4. Top three failure patterns\n")
    for i, p in enumerate(fp[:3], 1):
        w(f"**{i}. `{p['pattern']}`** — {p['failed_checks']} failed checks across {len(p['cases'])} cases ({', '.join(p['cases'])})")
        for e in p["examples"]:
            w(f"   - {e}")
        w(f"   - _Fix:_ {FIX_HINTS.get(p['pattern'], 'Inspect trace in results/ and add a rule or prompt example.')}\n")
    if not fp:
        w("No failed checks.\n")
    w("## 5. Economic value (per completed sponsorship)\n")
    w(f"Measured: {n_ag} agreements across 20 cases; {touches} items needed a person (confirmations, escalations, "
      f"payment reviews/disputes) = {touches / len(rows):.0%} of cases.\n")
    w("| | AI agent + rules | Manual / agency |\n|---|---|---|")
    w(f"| Avg host fee (paid to host) | ${econ['avg_host_fee']} | ${econ['avg_host_fee']} |")
    w(f"| Platform revenue (take rate {economics.ASSUMPTIONS['platform_take_rate']:.0%}) | ${econ['platform_revenue']} | ${econ['platform_revenue']} |")
    w(f"| Coordination cost | ${econ['llm_cost'] + econ['human_review_cost']:.2f} (LLM ${econ['llm_cost']}, people ${econ['human_review_cost']}) | ${econ['manual_coordination_cost']} |")
    w(f"| Payment processing | ${econ['payment_processing']} | ${econ['payment_processing']} |")
    w(f"| **Contribution margin** | **${econ['contribution_margin']}** | **${econ['manual_margin']}** |")
    w(f"\nHost earns ~${econ['host_effective_hourly']}/hour for the extra sponsorship work (assumes 1.5 h). A manual model only breaks even on host fees "
      f"above ~${econ['breakeven_fee_manual']:.0f}, so small dinners are uneconomic by hand. That is the gap the agent closes. "
      "Assumptions are in `evals/economics.py`; replace them with pilot data.\n")
    (ROOT / "REPORT.md").write_text("\n".join(L))


if __name__ == "__main__":
    main()
