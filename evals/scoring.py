"""Deterministic scoring of one agent output against a golden case.
Each check carries a failure category so failures can be grouped into patterns."""


def _eq(field, got, exp):
    if field == "boroughs":
        return sorted(got or []) == sorted(exp)
    if isinstance(exp, str) and isinstance(got, str):
        return exp.lower() in got.lower()
    return got == exp


def diagnose_miss(out, ids):
    """Why did none of the must-include events get selected?"""
    tr = {t["step"]: t for t in out.get("trace", [])}
    elig = tr.get("2a eligibility + dedupe", {}).get("eligible", [])
    cands = [c[0] for c in tr.get("2b retrieve (BM25 over catalog)", {}).get("candidates", [])]
    scores = tr.get("2c score community fit", {}).get("scores", {})
    esc = [e["id"] for e in out.get("escalations", [])]
    if not any(i in elig for i in ids):
        return "rule_excluded_good_event", f"{ids} filtered by rules: {[tr['2a eligibility + dedupe']['rejected'].get(i) for i in ids]}"
    if not any(i in cands for i in ids):
        return "retrieval_miss", f"{ids} eligible but not in top-k retrieval {cands}"
    if any(i in esc for i in ids):
        return "negotiation_escalated", f"{ids} escalated on price"
    s = {i: scores[i] for i in ids if i in scores}
    return "fit_underscored", f"AI fit scores {s}"


def score_case(case, out):
    exp, checks = case["expect"], []
    add = lambda name, cat, ok, detail="": checks.append({"check": name, "category": cat, "pass": bool(ok), "detail": detail})
    b = out.get("brief", {})
    for f, v in exp.get("fields", {}).items():
        add(f"extract.{f}", "extraction_error", _eq(f, b.get(f), v), f"got {b.get(f)!r}, expected {v!r}")
    add("intake_status", "intake_gate_error", out["status"] == exp["status"], f"got {out['status']}, expected {exp['status']}")

    if exp["status"] == "ok" and out["status"] == "ok":
        sel = [a["event_id"] for a in out.get("agreements", [])]
        if exp.get("must_include_any"):
            ok = any(i in sel for i in exp["must_include_any"])
            cat, det = ("", "") if ok else diagnose_miss(out, exp["must_include_any"])
            add("selected_a_best_fit_event", cat or "fit_underscored", ok, det or f"selected {sel}")
        if "acceptable" in exp:
            bad = [i for i in sel if i not in exp["acceptable"]]
            add("all_selected_events_fit", "fit_overmatch", not bad, f"poor-fit picks {bad}" if bad else "")
        bad = [i for i in sel if i in exp.get("must_not_select", [])]
        add("no_forbidden_event_selected", "wrong_event_selected", not bad, f"selected {bad}" if bad else "")
        for i in exp.get("must_escalate", []):
            add(f"escalated_{i}", "negotiation_error", i in [e["id"] for e in out.get("escalations", [])])
        for i in exp.get("must_not_contact", []):
            add(f"did_not_contact_{i}", "eligibility_rule_error", i not in sel)
        caps_ok = all(a["host_fee"] <= b["per_event_cap"] for a in out.get("agreements", []))
        add("money_within_budget_and_cap", "money_invariant_broken", out.get("spend", 0) <= b["budget_total"] and caps_ok,
            f"spend {out.get('spend')} / budget {b.get('budget_total')}")
        for a in out.get("agreements", []):
            add(f"offer_{a['event_id']}_drafted_within_rules", "offer_guard_fallback", a["offer_source"] == "ai",
                f"{a['offer_attempts']} attempts, final source {a['offer_source']}")
        pe = exp.get("payment")
        if pe and pe != "n/a" and not out.get("agreements"):
            add("payment_decision", "blocked_upstream_no_agreement", False, "no agreement was made, so payment step never ran")
        elif pe and pe != "n/a":
            got = (out.get("payment") or {}).get("decision")
            ai = any(t["step"].startswith("5") and t.get("ai_verdict") for t in out.get("trace", []))
            add("payment_decision", "evidence_judgment_error" if ai else "payment_rule_error", got == pe,
                f"got {got}, expected {pe}; reason: {(out.get('payment') or {}).get('reason')}")
        if exp.get("pii_redacted"):
            add("guest_pii_redacted", "privacy_error", (out.get("payment") or {}).get("pii_redacted", 0) > 0)

    n = sum(c["pass"] for c in checks)
    return {"score": round(n / len(checks), 3), "passed_all": n == len(checks), "checks": checks}


def summarize(out):
    """One-line human-readable summary for the team scoring sheet and judge."""
    if out["status"] != "ok":
        return f"Paused for brand confirmation: {out.get('issues')}"
    parts = [f"{a['event_id']} {a['title']} (${a['host_fee']}, {a['negotiation']})" for a in out.get("agreements", [])]
    s = "Selected: " + ("; ".join(parts) if parts else "none")
    if out.get("escalations"):
        s += " | Escalated: " + ", ".join(f"{e['id']} ({e['reason']})" for e in out["escalations"])
    s += f" | Spend ${out.get('spend', 0)}"
    if out.get("payment"):
        s += f" | Payment: {out['payment']['decision']} ({out['payment']['reason']})"
    return s
