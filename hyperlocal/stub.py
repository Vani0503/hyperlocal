"""Offline heuristic stand-in for the model. ONLY for smoke-testing plumbing
without API keys. Its scores say nothing about real model quality."""
import json, re

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                      "august", "september", "october", "november", "december"], 1)}
LAST = {1: 31, 2: 28, 12: 31}


def respond(step, user):
    return json.dumps(globals()[f"_{step}"](user)) if step != "offer" else _offer(user)


def _extract(t):
    low = t.lower()
    amts = [float(a.replace(",", "")) for a in re.findall(r"\$([\d,]+)", t)]
    cap = None
    m = re.search(r"(cap|max|more than|up to)[^$]{0,20}\$([\d,]+)|\$([\d,]+)\s*(cap|max|/event|per)", low)
    if m: cap = float((m.group(2) or m.group(3)).replace(",", ""))
    total = next((a for a in amts if a != cap), None)
    months = sorted({MONTHS[w] for w in re.findall(r"[a-z]+", low) if w in MONTHS} |
                    {MONTHS[k] for k in MONTHS if k[:3] + " " in low or k[:3] + "-" in low})
    ds = de = None
    if months:
        def y(mn): return 2026 if mn >= 11 else 2027
        ms = months if not (12 in months and len(months) > 1) else [12] + [m for m in months if m != 12]
        ds, de = f"{y(ms[0])}-{ms[0]:02d}-01", f"{y(ms[-1])}-{ms[-1]:02d}-{LAST.get(ms[-1], 30)}"
    n = re.search(r"\b(\d)\s+(events?|dinners?|brunch|gatherings|supper|cultural)", low)
    g = re.search(r"(\d+)\+?\s*guests", low)
    cat = ("alcohol" if re.search(r"whiskey|mezcal|rye|wine brand", low) else
           "pet" if "dog" in low else "tech_app" if "app" in low else "beverage_non_alcoholic"
           if re.search(r"milk|water|kombucha|coffee|tea", low) else "food")
    bor = [b for b in ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"] if b.lower() in low]
    words = [w for w in re.findall(r"[a-z]{4,}", low) if w not in {"want", "with", "that", "this", "total", "budget"}]
    return {"brand_name": t.split()[0].strip(",.") if not t.lower().startswith(("hi", "hey")) else t.split()[1],
            "product_category": cat, "budget_total": total, "per_event_cap": cap,
            "num_events": int(n.group(1)) if n else (1 if "one " in low else None), "boroughs": bor,
            "date_start": ds, "date_end": de, "min_guests": int(g.group(1)) if g else None,
            "exclude_alcohol_events": "no events where alcohol" in low, "audience": t[:150],
            "audience_keywords": words[:8]}


def _fit(t):
    goal = set(re.findall(r"[a-z]{4,}", t.split("EVENTS:")[0].lower()))
    evs = json.loads(t.split("EVENTS:\n", 1)[1])
    out = []
    for e in evs:
        words = set(re.findall(r"[a-z]{4,}", (e["description"] + " " + " ".join(e["tags"])).lower()))
        out.append({"id": e["id"], "fit_score": min(5, len(goal & words)), "reason": "keyword overlap (stub)"})
    return {"scores": out}


def _offer(t):
    brand = re.search(r"Brand: (.*)", t).group(1); fee = re.search(r"Fee: (\$\d+)", t).group(1)
    host = re.search(r"Host: (.*)", t).group(1)
    return (f"Hi {host}, {brand} would love to sponsor your dinner for {fee}. Materials ship at our cost; "
            f"you'd do a short checklist and two product photos. We never need guest info. Feel free to decline.")


def _evidence(t):
    low = t.lower()
    if re.search(r"different brand|barco", low): return {"verdict": "not_met", "confidence": 0.9, "reason": "competitor product"}
    if re.search(r"blurry|cannot make out", low): return {"verdict": "unclear", "confidence": 0.4, "reason": "unclear photos"}
    return {"verdict": "met", "confidence": 0.9, "reason": "product visible"}


def _judge(t):
    return {"score": 4, "pass": True, "reason": "stub judge"}
