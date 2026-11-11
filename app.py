"""Hyperlocal — Streamlit UI.  Run locally:  streamlit run app.py"""
import json, os
from pathlib import Path
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="Hyperlocal — sponsor small dinners", page_icon="🍽️", layout="wide")

# API key: Streamlit secrets (deployed) > env var (local) > typed in sidebar
def secret(k):
    try:
        return st.secrets.get(k)
    except Exception:
        return None


for _k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
    if secret(_k):
        os.environ[_k] = secret(_k)

from hyperlocal import agent, config as C
from hyperlocal.knowledge import load_events, DATA
from hyperlocal.llm import LLM, CallLog

MAX_RUNS_PER_SESSION = 15   # protects your API bill on a public link
golden = json.loads((DATA / "golden.json").read_text())
cases = {c["id"]: c for c in golden["cases"]}
events = load_events()

# ---------------- sidebar ----------------
with st.sidebar:
    st.header("Settings")
    have_key = bool(os.getenv("ANTHROPIC_API_KEY"))
    if not have_key:
        k = st.text_input("Anthropic API key (optional)", type="password",
                          help="Without a key the app runs in demo mode with a simple offline stand-in for the AI.")
        if k:
            os.environ["ANTHROPIC_API_KEY"] = k; have_key = True
    options = ([f"Fast — {C.FAST_MODEL}", f"Strong — {C.STRONG_MODEL}"] if have_key else []) + ["Demo mode (no AI, offline)"]
    choice = st.radio("Model", options)
    model = "stub" if choice.startswith("Demo") else choice.split("— ")[1]
    today = st.date_input("Today's date (for date rules)", pd.Timestamp(golden["today"])).isoformat()
    st.caption(f"Runs this session: {st.session_state.get('runs', 0)}/{MAX_RUNS_PER_SESSION}")
    if model == "stub":
        st.warning("Demo mode: AI steps use keyword heuristics. Results are illustrative only.")

st.title("🍽️ Hyperlocal")
st.markdown("**Brands sponsor small community dinners without the manual work.** Paste a brand brief → the agent "
            "finds fitting NYC supper clubs, prices and negotiates within your limits, drafts host offers, plans "
            "shipping, and decides whether to pay the host from their evidence. "
            "`AI` = judgment steps · `RULE` = deterministic steps (all money, eligibility, privacy and payment).")

tab_run, tab_catalog, tab_evals, tab_how = st.tabs(["▶ Run a campaign", "📚 Event catalog", "📊 Eval results", "⚙️ How it works"])

# ---------------- run tab ----------------
with tab_run:
    labels = {"custom": "✍️ Write my own brief"} | {cid: f"{cid} · {', '.join(c['tags'])} · {c['brief'][:60]}…" for cid, c in cases.items()}
    pick = st.selectbox("Start from an example brief or write your own", list(labels), format_func=labels.get, index=1)
    base = cases.get(pick)
    brief = st.text_area("Brand brief (free text, as a brand would write it)", base["brief"] if base else
                         "We're Brew Theory coffee. 2 brunches for coffee lovers in Brooklyn or Manhattan, Jan-Feb 2027. "
                         "$600 total, $250 max each.", height=110)

    with st.expander("Step 5 input: host's completion evidence (optional)", expanded=bool(base and base["evidence"])):
        ev0 = (base or {}).get("evidence") or {"status": "completed", "submitted_days_after_event": 2, "attendance_ratio": 1.0,
               "host_report": "Great night, product was on every table.", "photo_descriptions": ["Table set with {brand} samples, logo visible"]}
        use_ev = st.checkbox("Include evidence", value=bool(base and base["evidence"]) or pick == "custom")
        c1, c2, c3 = st.columns(3)
        status = c1.selectbox("Event status", ["completed", "cancelled"], index=0 if ev0["status"] == "completed" else 1)
        days = c2.number_input("Days after event submitted", 0, 60, int(ev0["submitted_days_after_event"]))
        att = c3.slider("Attendance vs agreed", 0.0, 1.5, float(ev0["attendance_ratio"]), 0.05)
        report = st.text_area("Host report", ev0["host_report"])
        photos = st.text_area("Photo descriptions (one per line; {brand} = brand name)", "\n".join(ev0["photo_descriptions"]))
        evidence = {"status": status, "submitted_days_after_event": days, "attendance_ratio": att, "host_report": report,
                    "photo_descriptions": [p for p in photos.splitlines() if p.strip()]} if use_ev else None

    if st.button("Run agent", type="primary", width="stretch"):
        if st.session_state.get("runs", 0) >= MAX_RUNS_PER_SESSION and model != "stub":
            st.error("Run limit reached for this session. Switch to demo mode or reload later.")
        else:
            st.session_state["runs"] = st.session_state.get("runs", 0) + (model != "stub")
            with st.spinner("Running the 5 steps…"):
                try:
                    st.session_state["result"] = agent.run(brief, evidence, today=today, llm=LLM(model, log=CallLog()), events=events)
                    st.session_state["expected"] = base["expect"] if base and brief == base["brief"] else None
                except Exception as e:
                    st.session_state["result"] = None; st.error(f"Run failed: {e}")

    r = st.session_state.get("result")
    if r:
        u = r["usage"]; tr = {t["step"]: t for t in r["trace"]}
        m = st.columns(5)
        m[0].metric("Status", r["status"].replace("_", " "))
        m[1].metric("Agreements", len(r.get("agreements", [])))
        m[2].metric("Spend reserved", f"${r.get('spend', 0):,}", f"of ${r['brief'].get('budget_total') or 0:,}", delta_color="off")
        m[3].metric("AI cost", f"${u['cost_usd']:.4f}")
        m[4].metric("AI latency", f"{u['latency_s']:.1f}s", f"{u['llm_calls']} calls", delta_color="off")

        st.subheader("1 · Brief understood  `AI` → validated `RULE`")
        b = r["brief"]
        st.dataframe(pd.DataFrame([{k: (", ".join(map(str, v)) if isinstance(v, list) else str(v)) for k, v in b.items()}]).T.rename(columns={0: "value"}),
                     width="stretch")
        if r["status"] == "needs_confirmation":
            st.warning(f"⏸ Paused before any outreach. Issues: {', '.join(r['issues'])}. {r['next_action']}")
        else:
            st.subheader("2 · Events found  `RULE` filters + retrieval → `AI` fit scores")
            elig = tr.get("2a eligibility + dedupe", {})
            fit = tr.get("2c score community fit", {}).get("scores", {})
            ev_by = {e["id"]: e for e in events}
            rows = []
            for e in events:
                rid = e["id"]
                why = elig.get("rejected", {}).get(rid)
                st_ = ("dropped: duplicate listing" if rid in elig.get("duplicates_dropped", []) else
                       f"ineligible: {', '.join(why)}" if why else
                       f"AI fit {fit[rid][0]}/5 — {fit[rid][1]}" if rid in fit else "eligible, not in top retrieval")
                rows.append({"id": rid, "event": e["title"], "borough": e["borough"], "date": e["date"], "guests": e["guests"], "result": st_})
            df = pd.DataFrame(rows)
            df["_o"] = df["result"].map(lambda s: 0 if s.startswith("AI") else 1 if s.startswith("eligible") else 2)
            st.dataframe(df.sort_values("_o").drop(columns="_o"), hide_index=True, width="stretch", height=280)

            st.subheader("3 · Agreements  `RULE` pricing & negotiation + `AI` offer drafts")
            if r.get("agreements"):
                st.dataframe(pd.DataFrame([{k: a[k] for k in ("event_id", "title", "date", "guests", "host_fee", "materials",
                                                              "reserved_total", "negotiation", "fit_score")} for a in r["agreements"]]),
                             hide_index=True, width="stretch")
                for a in r["agreements"]:
                    with st.expander(f"✉️ Offer to {a['host']} — {a['title']}  ({a['offer_source']}, {a['offer_attempts']} draft(s))"):
                        st.write(a["offer_message"])
            else:
                st.info(r.get("next_action", "No agreements made."))
            for e in r.get("escalations", []):
                st.warning(f"↗ Escalated to brand: {ev_by[e['id']]['title']} — {e['reason']}. The agent never pays above the cap.")

            if r.get("plans"):
                st.subheader("4 · Execution plan  `RULE`")
                st.dataframe(pd.DataFrame([{**p, "host_checklist": " · ".join(p["host_checklist"])} for p in r["plans"]]),
                             hide_index=True, width="stretch")
            if r.get("payment"):
                p = r["payment"]
                st.subheader("5 · Verify & pay  `RULE` checks + `AI` evidence review")
                icon = {"release": "✅", "human_review": "👀", "dispute": "⚠️", "cancel": "✖️"}[p["decision"]]
                st.markdown(f"### {icon} {p['decision'].replace('_', ' ').title()}" + (f" — ${p['amount']} due within {p['due_within_days']} days" if p["amount"] else ""))
                st.write(f"Reason: {p['reason']}")
                if p["pii_redacted"]:
                    st.info(f"🔒 {p['pii_redacted']} guest contact detail(s) redacted before the AI saw the report.")

        if st.session_state.get("expected"):
            with st.expander("🎯 Golden expected output for this case"):
                st.json(st.session_state["expected"])
        with st.expander("🔍 Full trace (every step, AI vs RULE)"):
            for t in r["trace"]:
                st.markdown(f"**{t['step']}** `{t['type']}`")
                st.json({k: v for k, v in t.items() if k not in ("step", "type")}, expanded=False)

# ---------------- catalog tab ----------------
with tab_catalog:
    st.markdown("**Knowledge source.** The agent *retrieves* from this catalog instead of putting it all in the prompt: "
                "it grows without limit and changes daily, while each brief needs only ~5 rows. Rules filter it, BM25 ranks "
                f"what's left, and only the top {C.RETRIEVAL_TOP_K} go to the AI. Listings are modelled on real NYC supper-club formats.")
    st.dataframe(pd.DataFrame(events).assign(tags=lambda d: d.tags.map(", ".join)), hide_index=True, width="stretch")

# ---------------- evals tab ----------------
with tab_evals:
    with st.expander("▶ Run the full evaluation now (20 golden cases, judge on 10, two model tiers)", expanded=False):
        if not os.getenv("ANTHROPIC_API_KEY"):
            st.info("Add an Anthropic API key (sidebar or app secrets) to run real evals.")
        else:
            use_openai = bool(os.getenv("OPENAI_API_KEY"))
            jp, jm = ("openai", C.JUDGE_MODEL) if use_openai else ("anthropic", "claude-opus-5-5")
            st.caption(f"Agent: {C.MAIN_MODEL} · tiers: {C.FAST_MODEL} vs {C.STRONG_MODEL} · judge: {jp}:{jm}"
                       + ("" if use_openai else " (add OPENAI_API_KEY to secrets for a different-family judge)")
                       + ". Takes ~5 minutes and roughly $1 of API usage.")
            pw = st.text_input("Eval password", type="password", help="Set EVAL_PASSWORD in app secrets so visitors can't trigger paid runs.")
            ok_pw = (pw == secret("EVAL_PASSWORD")) if secret("EVAL_PASSWORD") else True
            if st.button("Run evaluation", disabled=not ok_pw):
                import sys, types
                sys.path.insert(0, str(ROOT / "evals"))
                import run_evals
                box = st.empty(); lines = []
                def log(m):
                    lines.append(m); box.code("\n".join(lines[-15:]))
                a = types.SimpleNamespace(stub=False, model=C.MAIN_MODEL, fast=C.FAST_MODEL, strong=C.STRONG_MODEL,
                                          judge_provider=jp, judge_model=jm, skip_judge=False, skip_tiers=False)
                with st.spinner("Running evaluation…"):
                    run_evals.evaluate(a, log=log)
                st.success("Done. Report below; download it and the team scoring sheet.")
    for f, label in [(ROOT / "REPORT.md", "⬇ Download REPORT.md"), (ROOT / "results" / "team_scores.csv", "⬇ Download team scoring sheet")]:
        if f.exists():
            st.download_button(label, f.read_bytes(), file_name=f.name)
    rep = next((p for p in [ROOT / "REPORT.md", ROOT / "REPORT_STUB_EXAMPLE.md"] if p.exists()), None)
    if rep:
        if rep.name.startswith("REPORT_STUB"):
            st.warning("Showing the stub example. Run `python evals/run_evals.py` with your API keys and commit REPORT.md to show real results.")
        st.markdown(rep.read_text())
    else:
        st.info("No report yet. Run `python evals/run_evals.py`.")

# ---------------- how tab ----------------
with tab_how:
    st.markdown("""
| Step | AI (judgment only) | Rules (deterministic) |
|---|---|---|
| 1 Capture | Turns a messy brief into fields | Pauses if budget/cap/dates are missing or inconsistent |
| 2 Find | Scores community fit 0–5 | Dates, borough, freshness, opt-outs, min guests, 21+/alcohol rules, dedupe, BM25 ranking |
| 3 Negotiate | Writes the host offer | Fee formula, per-host cap, 1 counter round then escalate, budget reserve, offer guard + template fallback |
| 4 Execute | — | Ship-by date, one order per event, proof approval, host checklist |
| 5 Verify & pay | Judges if evidence shows *this* brand | Cancellation, 14-day window, attendance <50%, PII redaction, confidence threshold |

**Why it creates value:** coordinating one small sponsorship by hand costs ~3.5 ops hours (~$140), so at a 25% take rate
it only pays off for host fees above ~$560 — which is why brands default to big pop-ups. The agent cuts coordination to
cents of AI plus a few minutes of human review on exceptions, making $150–450 dinner sponsorships profitable, while hosts
get paid fairly for ~1.5 hours of extra work and never share guest data.
""")
