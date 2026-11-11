"""Deterministic steps. Anything involving money, eligibility, privacy,
deadlines or payment is decided here, never by the model."""
import re
from datetime import date, timedelta
from . import config as C

BOROUGHS = {"Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"}
CATEGORIES = {"alcohol", "food", "beverage_non_alcoholic", "wellness_beauty",
              "tech_app", "pet", "apparel_fitness", "other"}
d = date.fromisoformat


# ---- Step 1: validate the AI-extracted brief ----------------------------
def validate_brief(b):
    """Return (clean_brief, issues). Any issue => needs human confirmation."""
    issues = []
    for k in ("budget_total", "per_event_cap", "num_events", "min_guests"):
        try:
            b[k] = int(round(float(str(b[k]).replace("$", "").replace(",", "")))) if b.get(k) not in (None, "") else None
        except ValueError:
            b[k] = None
    for k in ("budget_total", "per_event_cap", "date_start", "date_end"):
        if b.get(k) in (None, "", 0):
            issues.append(f"missing:{k}")
    try:
        if b.get("date_start") and b.get("date_end") and d(b["date_start"]) > d(b["date_end"]):
            issues.append("invalid:date_range")
    except ValueError:
        issues.append("invalid:date_format")
    bt, cap = b.get("budget_total"), b.get("per_event_cap")
    if bt and cap and cap > bt:
        issues.append("inconsistent:per_event_cap_exceeds_total_budget")
    b["boroughs"] = [x for x in (b.get("boroughs") or []) if x in BOROUGHS] or sorted(BOROUGHS)
    if b.get("product_category") not in CATEGORIES:
        b["product_category"] = "other"
    b["num_events"] = int(b.get("num_events") or 1)
    b["min_guests"] = int(b.get("min_guests") or 0)
    return b, issues


# ---- Step 2: eligibility filters + dedupe -------------------------------
def eligibility(e, b, today):
    """Return list of reasons the event is ineligible (empty = eligible)."""
    r = []
    if e["opted_out"]: r.append("host_opted_out")
    if (today - d(e["last_verified"])).days > C.FRESHNESS_DAYS: r.append("stale_listing")
    if not (d(b["date_start"]) <= d(e["date"]) <= d(b["date_end"])): r.append("outside_dates")
    if d(e["date"]) <= today + timedelta(days=10): r.append("too_soon_to_ship")
    if e["borough"] not in b["boroughs"]: r.append("outside_geography")
    if e["guests"] < b["min_guests"]: r.append("below_min_guests")
    if b["product_category"] == "alcohol" and (not e["alcohol_served"] or e["sober"] or e["age_policy"] != "21+"):
        r.append("alcohol_brand_needs_21plus_alcohol_event")
    if b.get("exclude_alcohol_events") and e["alcohol_served"]: r.append("brand_excludes_alcohol_events")
    return r


def dedupe(events):
    """Same host + same date = same real-world event listed twice."""
    seen, out, dropped = set(), [], []
    for e in events:
        key = (e["host"].lower(), e["date"])
        (dropped if key in seen else out).append(e)
        seen.add(key)
    return out, [x["id"] for x in dropped]


# ---- Step 3: pricing, bounded negotiation, budget reservation ------------
def materials_cost(e):
    return C.MATERIALS_PER_GUEST * e["guests"] + C.SHIPPING_FLAT


def price_and_negotiate(e, cap):
    """Opening offer from the formula; host ask = listed minimum fee.
    accept: offer >= ask. meet_ask: one counter round, ask <= cap.
    escalate: ask > cap -> brand decides, agent never exceeds the cap."""
    offer = min(cap, C.PRICE_BASE + C.PRICE_PER_GUEST * e["guests"]) // 10 * 10
    ask = e["host_min_fee"]
    if ask <= offer:
        return {"outcome": "accept", "fee": offer, "rounds": 0, "host_ask": ask}
    if ask <= cap and C.MAX_NEGOTIATION_ROUNDS >= 1:
        return {"outcome": "meet_ask", "fee": ask, "rounds": 1, "host_ask": ask}
    return {"outcome": "escalate", "fee": None, "rounds": 1, "host_ask": ask,
            "reason": f"host asks ${ask}, brand cap ${cap}"}


def select_within_budget(scored, b):
    """Greedy by fit score; reserve fee + materials; never exceed budget/cap."""
    budget, agreements, escalations, skipped = b["budget_total"], [], [], []
    for e in sorted(scored, key=lambda x: (-x["fit_score"], -x["retrieval_score"])):
        if e["fit_score"] < C.FIT_THRESHOLD:
            skipped.append({"id": e["id"], "reason": "below_fit_threshold"}); continue
        if len(agreements) >= b["num_events"]:
            break
        n = price_and_negotiate(e, b["per_event_cap"])
        if n["outcome"] == "escalate":
            escalations.append({"id": e["id"], **n}); continue
        total = n["fee"] + materials_cost(e)
        if total > budget:
            skipped.append({"id": e["id"], "reason": "insufficient_remaining_budget"}); continue
        budget -= total
        agreements.append({"event_id": e["id"], "title": e["title"], "host": e["host"], "date": e["date"],
                           "guests": e["guests"], "host_fee": n["fee"], "materials": materials_cost(e),
                           "reserved_total": total, "negotiation": n["outcome"], "fit_score": e["fit_score"],
                           "fit_reason": e.get("fit_reason", "")})
    return agreements, escalations, skipped, b["budget_total"] - budget


# ---- Offer message guard -------------------------------------------------
FORBIDDEN = [r"guest (list|emails?|contacts?|phone)", r"guarantee", r"exclusive rights", r"\bsales target"]


def check_offer(msg, brand, fee):
    v = []
    if f"${fee}" not in msg.replace(",", ""): v.append(f"must state the exact fee ${fee}")
    if brand.lower() not in msg.lower(): v.append(f"must name the brand {brand}")
    if len(msg.split()) > C.MAX_OFFER_WORDS: v.append(f"must be under {C.MAX_OFFER_WORDS} words")
    if not re.search(r"decline|no thanks|not interested|opt out|say no", msg, re.I):
        v.append("must tell the host they can decline")
    for p in FORBIDDEN:
        if re.search(p, msg, re.I): v.append(f"forbidden content: {p}")
    return v


def template_offer(brand, a):
    return (f"Hi {a['host']}, {brand} would like to sponsor {a['title']} on {a['date']}. "
            f"We'd pay you ${a['host_fee']}, and we ship all materials at our cost. We just need a short checklist "
            f"and two photos afterward. We never need guest information. If it's not a fit, just decline, no problem.")


# ---- Step 4: execution plan ---------------------------------------------
def execution_plan(a, printed_before=False):
    ev = d(a["date"])
    ship_by = ev - timedelta(days=7)
    while ship_by.weekday() >= 5:
        ship_by -= timedelta(days=1)
    return {"event_id": a["event_id"], "order_id": f"ORD-{a['event_id']}",  # one order per event: no duplicates
            "proof_approval_required": not printed_before, "ship_by": ship_by.isoformat(),
            "host_checklist": ["Place samples / table cards before guests arrive",
                               "Take 2 photos showing the product (no guest faces needed)",
                               "Submit the completion form within 14 days"]}


# ---- Step 5: privacy scrub + payment decision ---------------------------
PII = [r"[\w.+-]+@[\w-]+\.[\w.]+", r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}"]


def scrub_pii(text):
    n = 0
    for p in PII:
        text, k = re.subn(p, "[REDACTED]", text)
        n += k
    return text, n


def payment_precheck(ev):
    """Rules that decide before the AI looks at evidence."""
    if ev["status"] == "cancelled":
        return "cancel", "host cancelled; release reserved budget, no payment"
    if ev["submitted_days_after_event"] > C.EVIDENCE_WINDOW_DAYS:
        return "human_review", "evidence submitted after the agreed window"
    if ev["attendance_ratio"] < C.MIN_ATTENDANCE_RATIO:
        return "human_review", "attendance below 50% of agreed guest count"
    return None, None


def payment_decision(verdict, confidence):
    if verdict == "not_met":
        return "dispute"
    if verdict == "met" and confidence >= C.EVIDENCE_CONFIDENCE_MIN:
        return "release"
    return "human_review"
