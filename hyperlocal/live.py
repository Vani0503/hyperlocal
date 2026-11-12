"""Live event search: Claude's server-side web search tool finds real, public,
upcoming small food events in NYC, then we normalise them into the same shape
as the sample catalog so the same rules and fit scoring apply."""
import json, time
from .llm import parse_json, _cost

WEB_SEARCH_COST = 0.01   # USD per search ($10 / 1,000)

LIVE_SYS = """You find REAL, upcoming, PUBLIC small-group food events in New York City that a brand could sponsor:
supper clubs, dinner parties with public tickets, cooking classes, tastings, community dinners, run-club brunches.
Use web search. Prefer public listing pages (Eventbrite, Luma, Partiful public events, Resy/OpenTable events,
supper club websites). Only include events you actually found, with a working URL. Never invent events.
Do not include private individuals' phone numbers, emails or home addresses.
Return JSON only: {"events": [{"title": str, "organizer": str, "borough": "Manhattan|Brooklyn|Queens|Bronx|Staten Island",
"neighborhood": str, "date": "YYYY-MM-DD", "guests_estimate": int or null, "description": "<= 30 words",
"tags": [str], "alcohol_served": true/false/null, "age_policy": "21+" or "all ages" or null, "url": str}]}"""


def search_live_events(brief, llm, today, max_events=8):
    if llm.provider == "stub":
        return []
    user = (f"Today is {today}. Find up to {max_events} events for this brand.\n"
            f"Brand: {brief['brand_name']} ({brief['product_category']}). Audience: {brief.get('audience')}\n"
            f"Boroughs: {', '.join(brief['boroughs'])}. Dates: {brief['date_start']} to {brief['date_end']}.")
    t = time.time()
    r = llm.client.messages.create(model=llm.model, max_tokens=4000, system=LIVE_SYS,
                                   messages=[{"role": "user", "content": user}],
                                   tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}])
    text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    n_search = getattr(getattr(r.usage, "server_tool_use", None), "web_search_requests", 0) or 0
    llm.log.add(step="live_search", model=llm.model, latency_s=time.time() - t, in_tok=r.usage.input_tokens,
                out_tok=r.usage.output_tokens,
                cost=_cost(llm.model, r.usage.input_tokens, r.usage.output_tokens) + n_search * WEB_SEARCH_COST)
    try:
        found = parse_json(text).get("events", [])
    except Exception:
        found = []
    out = []
    for i, e in enumerate(found[:max_events], 1):
        if not e.get("title") or not e.get("date") or not e.get("url"):
            continue
        out.append({
            "id": f"L{i:02d}", "title": e["title"], "host": e.get("organizer") or "the organizer",
            "borough": e.get("borough") or "Manhattan", "neighborhood": e.get("neighborhood") or "",
            "date": e["date"], "guests": int(e.get("guests_estimate") or 20), "format": "live listing",
            "description": e.get("description", ""), "tags": e.get("tags") or [],
            "alcohol_served": bool(e.get("alcohol_served")), "age_policy": e.get("age_policy") or "all ages",
            "sober": False, "last_verified": today, "opted_out": False,
            "host_min_fee": 0,          # unknown for live listings: agent makes its formula offer
            "url": e["url"], "source": "live",
        })
    return out
