"""The five-step sponsorship workflow. Each step is tagged AI or RULE in the
trace so it's visible exactly where model judgment is used."""
import json
from datetime import date
from . import config as C, rules as R, prompts as P
from .knowledge import load_events, retrieve
from .llm import LLM


def run(brief_text, evidence=None, today="2026-11-15", model=None, llm=None, events=None):
    llm = llm or LLM(model or C.MAIN_MODEL)
    today_d = date.fromisoformat(today)
    events = events if events is not None else load_events()
    trace, out = [], {"status": "ok"}

    # 1. Capture needs and boundaries --------------------------------------
    raw = llm.complete_json(P.EXTRACT_SYS.format(today=today), brief_text, "extract")
    trace.append({"step": "1a extract brief", "type": "AI", "output": raw})
    brief, issues = R.validate_brief(dict(raw))
    trace.append({"step": "1b validate brief", "type": "RULE", "issues": issues})
    out["brief"] = brief
    if issues:
        out.update(status="needs_confirmation", issues=issues,
                   next_action="Ask the brand to confirm the flagged fields before any outreach.")
        return finish(out, trace, llm)

    # 2. Find events and propose -------------------------------------------
    eligible, rejected = [], {}
    for e in events:
        why = R.eligibility(e, brief, today_d)
        (rejected.__setitem__(e["id"], why) if why else eligible.append(e))
    eligible, dupes = R.dedupe(eligible)
    trace.append({"step": "2a eligibility + dedupe", "type": "RULE", "eligible": [e["id"] for e in eligible],
                  "rejected": rejected, "duplicates_dropped": dupes})
    query = " ".join([brief.get("audience", ""), " ".join(brief.get("audience_keywords") or []),
                      brief.get("product_category", "").replace("_", " ")])
    cands = retrieve(eligible, query, C.RETRIEVAL_TOP_K)
    trace.append({"step": "2b retrieve (BM25 over catalog)", "type": "RULE",
                  "query": query, "candidates": [(c["id"], c["retrieval_score"]) for c in cands]})
    if not cands:
        out.update(agreements=[], escalations=[], spend=0,
                   next_action="No eligible events. Suggest widening dates/geography to the brand.")
        return finish(out, trace, llm)

    ctx = json.dumps([{k: c[k] for k in ("id", "title", "format", "guests", "description", "tags")} for c in cands])
    fit = llm.complete_json(P.FIT_SYS, f"BRAND: {brief['brand_name']} ({brief['product_category']})\n"
                                       f"GOAL: {brief.get('audience')}\nEVENTS:\n{ctx}", "fit")
    by_id = {s["id"]: s for s in fit.get("scores", [])}
    for c in cands:
        s = by_id.get(c["id"], {})
        c["fit_score"] = int(s.get("fit_score", 0)); c["fit_reason"] = s.get("reason", "missing score")
    trace.append({"step": "2c score community fit", "type": "AI",
                  "scores": {c["id"]: [c["fit_score"], c["fit_reason"]] for c in cands}})

    # 3. Negotiate and finalize --------------------------------------------
    agreements, escalations, skipped, spend = R.select_within_budget(cands, brief)
    trace.append({"step": "3a price, negotiate, reserve budget", "type": "RULE", "agreements":
                  [(a["event_id"], a["host_fee"], a["negotiation"]) for a in agreements],
                  "escalations": escalations, "skipped": skipped, "spend": spend})
    for a in agreements:
        msg, tries, v = "", 0, []
        while tries < 2:
            fix = f"\nYour previous draft broke these rules, fix them: {v}" if v else ""
            msg = llm.complete(P.OFFER_SYS, f"Brand: {brief['brand_name']}\nHost: {a['host']}\nEvent: {a['title']} on {a['date']}"
                                            f"\nFee: ${a['host_fee']}{fix}", "offer", 400).strip()
            v = R.check_offer(msg, brief["brand_name"], a["host_fee"]); tries += 1
            if not v: break
        a["offer_message"] = msg if not v else R.template_offer(brief["brand_name"], a)
        a["offer_source"] = "ai" if not v else "template_fallback"
        a["offer_attempts"] = tries
    trace.append({"step": "3b draft offers + guard", "type": "AI+RULE",
                  "results": {a["event_id"]: [a["offer_source"], a["offer_attempts"]] for a in agreements}})

    # 4. Coordinate execution ----------------------------------------------
    plans = [R.execution_plan(a) for a in agreements]
    trace.append({"step": "4 execution plan", "type": "RULE", "plans": plans})
    out.update(agreements=agreements, escalations=escalations, spend=spend, plans=plans)

    # 5. Verify, pay, evaluate (first agreement's evidence) ----------------
    if evidence and agreements:
        a = agreements[0]
        decision, reason = R.payment_precheck(evidence)
        report, n_pii = R.scrub_pii(evidence["host_report"])
        verdict = None
        if decision is None:
            photos = [p.replace("{brand}", brief["brand_name"]) for p in evidence["photo_descriptions"]]
            verdict = llm.complete_json(P.EVIDENCE_SYS,
                f"Brand: {brief['brand_name']}\nDeliverables: {plans[0]['host_checklist']}\n"
                f"Host report: {report.replace('{brand}', brief['brand_name'])}\nPhotos: {photos}", "evidence")
            decision = R.payment_decision(verdict.get("verdict"), float(verdict.get("confidence", 0)))
            reason = verdict.get("reason")
        trace.append({"step": "5 verify evidence + payment", "type": "RULE+AI" if verdict else "RULE",
                      "pii_redacted": n_pii, "ai_verdict": verdict, "decision": decision})
        out["payment"] = {"event_id": a["event_id"], "decision": decision, "reason": reason,
                          "amount": a["host_fee"] if decision == "release" else 0,
                          "pii_redacted": n_pii, "due_within_days": C.PAYMENT_DUE_DAYS if decision == "release" else None}
    return finish(out, trace, llm)


def finish(out, trace, llm):
    out["trace"] = trace
    out["usage"] = llm.log.totals()
    return out
