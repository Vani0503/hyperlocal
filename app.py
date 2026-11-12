"""Hyperlocal — simple Streamlit app.  Run locally:  streamlit run app.py"""
import io, json, os, urllib.parse
from datetime import date
from pathlib import Path
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="Hyperlocal", page_icon="🍽️", layout="centered")


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
from hyperlocal.live import search_live_events

MAX_RUNS = 15                       # protects your API bill on a public link
TODAY = json.loads((DATA / "golden.json").read_text())["today"]
EVENTS = load_events()
EV = {e["id"]: e for e in EVENTS}
REAL_TODAY = date.today().isoformat()


def shrink(file):
    """Resize an uploaded photo to fit the AI's image limits; return (bytes, media_type)."""
    from PIL import Image
    im = Image.open(file).convert("RGB")
    im.thumbnail((1568, 1568))
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"
EXAMPLE = ("We're Leafline, an oat milk brand. We want 3 small dinners in Brooklyn or Manhattan in December or January, "
           "with plant-based, coffee or wellness guests. Total budget $1,200, and max $300 per dinner.")

WHY_NOT = {
    "host_opted_out": "host doesn't want sponsors", "stale_listing": "listing is old, may not happen",
    "outside_dates": "wrong dates", "too_soon_to_ship": "too soon to ship samples", "outside_geography": "wrong area",
    "below_min_guests": "too few guests", "alcohol_brand_needs_21plus_alcohol_event": "alcohol brands need a 21+ dinner with drinks",
    "brand_excludes_alcohol_events": "alcohol is served (you said no alcohol)",
}
ASK = {
    "missing:budget_total": "What is your **total budget**?", "missing:per_event_cap": "What is the **most you'll pay one host**?",
    "missing:date_start": "**When** do you want the dinners?", "missing:date_end": "**When** do you want the dinners?",
    "inconsistent:per_event_cap_exceeds_total_budget": "Your max per dinner is **bigger than your total budget**. Which number is right?",
    "invalid:date_range": "The dates don't make sense. **When** do you want the dinners?",
}
PROOF = {
    "✅ Good photos — our product is on the table": {"status": "completed", "submitted_days_after_event": 2, "attendance_ratio": 1.0,
        "host_report": "Great night! Everyone tried the {brand} product.",
        "photo_descriptions": ["Dinner table with {brand} product at every seat, logo clearly visible", "Guests holding {brand} samples"]},
    "🔄 Photos show a different brand": {"status": "completed", "submitted_days_after_event": 2, "attendance_ratio": 1.0,
        "host_report": "All good, product was on the table.",
        "photo_descriptions": ["Table with bottles from a different brand called OtherCo", "No {brand} product visible anywhere"]},
    "🌫️ Photos are too dark or blurry": {"status": "completed", "submitted_days_after_event": 3, "attendance_ratio": 1.0,
        "host_report": "It was lovely, attaching pics.", "photo_descriptions": ["Very dark, blurry photo, cannot make out any products"]},
    "❌ Host cancelled the dinner": {"status": "cancelled", "submitted_days_after_event": 0, "attendance_ratio": 0.0,
        "host_report": "Sorry, I got sick and had to cancel.", "photo_descriptions": []},
}

# ---------------- header ----------------
st.title("🍽️ Hyperlocal")
st.markdown("#### Get your brand into small dinner parties in NYC.")
st.markdown("You're a brand. **Write what you want** → we **pick dinner parties** and offer the host money to show your product "
            "→ after the dinner, we **check the host's photos** and decide whether to pay.")

t_try, t_dinners, t_test, t_about = st.tabs(["🚀 Try it", "🍽️ Food and Beverage Partners", "📝 Test score", "ℹ️ About"])

# ---------------- TRY IT ----------------
with t_try:
    with st.expander("⚙️ Settings (you can ignore this)"):
        have_key = bool(os.getenv("ANTHROPIC_API_KEY"))
        if not have_key:
            k = st.text_input("Anthropic API key", type="password")
            if k:
                os.environ["ANTHROPIC_API_KEY"] = k; have_key = True
        opts = ([f"Smart AI ({C.STRONG_MODEL})", f"Fast AI ({C.FAST_MODEL})"] if have_key else []) + ["Demo (no AI)"]
        choice = st.radio("Which AI?", opts)
        model = "stub" if choice.startswith("Demo") else choice.split("(")[1].rstrip(")")
        st.caption(f"Pretend today is {TODAY}. Runs used: {st.session_state.get('runs', 0)}/{MAX_RUNS}")
    if model == "stub":
        st.info("Demo mode: no real AI is connected, so results are rough.")

    live = model != "stub"          # real web search whenever a real AI is connected
    st.caption("🌐 We search the internet for real food & beverage events in NYC. Tip: ask for dates in the next 1–3 months.")
    brief = st.text_area("**What does your brand want?**", EXAMPLE, height=110,
                         help="Say: your brand and product, which part of NYC, which month, total budget, max per dinner.")
    st.caption("Tip: include your product, NYC area, month, total budget and max per dinner. Edit the example or write your own.")

    if st.button("Find dinners for me", type="primary", width="stretch"):
        if model != "stub" and st.session_state.get("runs", 0) >= MAX_RUNS:
            st.error("You've used all your tries for now. Please reload later.")
        else:
            st.session_state["runs"] = st.session_state.get("runs", 0) + (model != "stub")
            with st.spinner("Searching the internet for real dinners and picking the best… (about 1 minute)" if live else
                            "Reading your request and picking dinners… (about 20 seconds)"):
                try:
                    st.session_state["r"] = agent.run(brief, None, today=REAL_TODAY if live else TODAY,
                                                      llm=LLM(model, log=CallLog()), events=EVENTS,
                                                      event_source=search_live_events if live else None)
                    st.session_state["model"] = model
                    st.session_state.pop("pay", None)
                except Exception as e:
                    st.session_state.pop("r", None); st.error(f"Something went wrong: {e}")

    r = st.session_state.get("r")
    if r:
        b = r["brief"]
        EVX = {e["id"]: e for e in r.get("events_used") or EVENTS}
        if "events_used" in r:
            st.caption(f"🌐 Found {len(r['events_used'])} real events on the internet for this request.")
        st.divider()
        st.subheader("1️⃣ What we understood")
        if b.get("budget_total") or b.get("brand_name"):
            areas = ", ".join(b["boroughs"]) if len(b.get("boroughs", [])) < 5 else "any area"
            st.markdown(f"**{b.get('brand_name', '?')}** wants **{b.get('num_events', 1)} dinner(s)** in **{areas}**, "
                        f"from **{b.get('date_start') or '?'}** to **{b.get('date_end') or '?'}**.  \n"
                        f"Total budget **${b.get('budget_total') or '?'}**, max **${b.get('per_event_cap') or '?'}** per dinner.")

        if r["status"] == "needs_confirmation":
            st.warning("**We need a bit more information before contacting anyone:**\n\n" +
                       "\n".join(f"- {ASK.get(i, i)}" for i in dict.fromkeys(r["issues"])) +
                       "\n\nAdd this to your text above and click the button again.")
        else:
            st.subheader("2️⃣ Dinners we picked for you")
            ags = r.get("agreements", [])
            if not ags:
                st.info("We couldn't find a good dinner for this request. Try a different month, area, or a bigger budget.")
            for a in ags:
                e = EVX[a["event_id"]]
                with st.container(border=True):
                    st.markdown(f"### {e['title']}")
                    if e.get("url"):
                        st.markdown(f"🔗 [See the real listing]({e['url']})  ·  *price is our suggested offer; guest count may be an estimate*")
                    st.markdown(f"📅 {e['date']} · 📍 {e['neighborhood']}, {e['borough']} · 👥 {e['guests']} guests · host: {e['host']}")
                    c1, c2 = st.columns(2)
                    c1.metric("We pay the host", f"${a['host_fee']}")
                    c2.metric("Samples + shipping", f"${a['materials']}")
                    st.markdown(f"**Why it fits:** {a.get('fit_reason') or '—'}")
                    st.markdown(f"**Ship samples by:** {next(p['ship_by'] for p in r['plans'] if p['event_id'] == a['event_id'])}")
                    with st.expander("✉️ Message to the host (ready to send)"):
                        st.write(a["offer_message"])
                        to = st.text_input("Send to (email address)", key=f"to_{a['event_id']}",
                                           placeholder="host@example.com — or your own email to test")
                        subj = f"{b['brand_name']} would like to sponsor {e['title']}"
                        link = f"mailto:{to}?subject={urllib.parse.quote(subj)}&body={urllib.parse.quote(a['offer_message'])}"
                        st.link_button("📧 Open in my email app", link, disabled=not to)
                        st.caption("We never send emails automatically. You review and press send yourself.")
            for x in r.get("escalations", []):
                st.warning(f"⚠️ **{EVX[x['id']]['title']}** is a good fit, but the host wants **${x['host_ask']}** and your max is "
                           f"**${b['per_event_cap']}**. We did not go over your limit, so you decide.")
            if ags:
                st.success(f"💰 Total cost: **${r['spend']:,}** of your ${b['budget_total']:,} budget.")

            # why not the others
            tr = {t["step"]: t for t in r["trace"]}
            rej = tr.get("2a eligibility + dedupe", {}).get("rejected", {})
            dup = tr.get("2a eligibility + dedupe", {}).get("duplicates_dropped", [])
            fit = tr.get("2c score community fit", {}).get("scores", {})
            picked = {a["event_id"] for a in ags} | {x["id"] for x in r.get("escalations", [])}
            rows = []
            for e in EVX.values():
                i = e["id"]
                if i in picked:
                    continue
                why = ("same dinner listed twice" if i in dup else
                       "; ".join(WHY_NOT.get(w, w) for w in rej[i]) if i in rej else
                       f"not a great fit ({fit[i][0]}/5): {fit[i][1]}" if i in fit and fit[i][0] < C.FIT_THRESHOLD else
                       "good fit, but budget or dinner count already used" if i in fit else "not a close match")
                rows.append({"Dinner": e["title"], "Why we skipped it": why})
            with st.expander(f"See the {len(rows)} dinners we skipped, and why"):
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

            # after the dinner
            if ags:
                a0 = ags[0]; e0 = EVX[a0["event_id"]]
                st.subheader("3️⃣ After the dinner: check the proof")
                st.markdown(f"Imagine **{e0['title']}** has happened. The host sends photos as proof.")
                ups = st.file_uploader("**Upload a real photo** (e.g. your product on a table)", type=["png", "jpg", "jpeg", "webp"],
                                       accept_multiple_files=True)
                if ups:
                    st.image(ups, width=180)
                    note = st.text_input("Host's note (optional)", "Here are the photos from the dinner!")
                else:
                    st.markdown("**No photo? Pick a pretend situation instead:**")
                    pick = st.radio("Pick one:", list(PROOF), label_visibility="collapsed")
                if st.button("Check the proof", width="stretch"):
                    plan = next(p for p in r["plans"] if p["event_id"] == a0["event_id"])
                    if ups:
                        ev_in = {"status": "completed", "submitted_days_after_event": 1, "attendance_ratio": 1.0,
                                 "host_report": note, "photo_descriptions": []}
                        imgs = [shrink(u) for u in ups[:4]]
                    else:
                        ev_in, imgs = PROOF[pick], None
                    with st.spinner("The AI is looking at the proof…"):
                        pay, _ = agent.verify_payment(b, a0, plan, ev_in, LLM(st.session_state["model"], log=CallLog()), images=imgs)
                    st.session_state["pay"] = (pay, e0["host"])
                if st.session_state.get("pay"):
                    pay, host = st.session_state["pay"]
                    msg = {"release": ("success", f"✅ **Pay {host} ${pay['amount']}** (within {pay['due_within_days']} days)."),
                           "human_review": ("warning", "👀 **A person should look at this** before paying."),
                           "dispute": ("error", "❌ **Don't pay yet.** The proof doesn't show your product."),
                           "cancel": ("info", "✖️ **Dinner cancelled. No payment**, and your money is freed up.")}[pay["decision"]]
                    getattr(st, msg[0])(f"{msg[1]}  \nReason: {pay['reason']}")

        with st.expander("🔍 For the curious: what the AI did vs. fixed rules"):
            st.caption("AI = thinking steps (understand request, judge fit, write message, check photos). "
                       "RULE = fixed code for money, dates, safety and payment, so the AI can never overspend.")
            for t in r["trace"]:
                st.markdown(f"**{t['step']}** — `{t['type']}`")
            u = r["usage"]
            st.caption(f"AI calls: {u['llm_calls']} · AI time: {u['latency_s']:.1f}s · AI cost: ${u['cost_usd']:.4f}")

# ---------------- DINNERS ----------------
with t_dinners:
    found = (st.session_state.get("r") or {}).get("events_used")
    if found:
        st.markdown(f"**{len(found)} real food & beverage partners** found on the internet for your last search:")
        st.dataframe(pd.DataFrame([{"Partner event": e["title"], "Organizer": e["host"], "Area": e["borough"], "Date": e["date"],
                                    "Guests (est.)": e["guests"], "What it's about": e["description"], "Link": e.get("url", "")}
                                   for e in found]), hide_index=True, width="stretch",
                     column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open")})
    else:
        st.info("No partners yet. Go to **🚀 Try it** and click **Find dinners for me**. "
                "The real food & beverage events we find on the internet will show up here.")

# ---------------- TEST SCORE ----------------
with t_test:
    st.markdown("**This is an exam for the app.** We wrote 20 practice requests and the right answer for each "
                "(e.g. *“this brand sells whiskey, so it must not pick a kids' dinner”*). The app tries all 20, and we count how many it gets right.")
    rep = ROOT / "REPORT.md"
    if rep.exists() and "STUB RUN" not in rep.read_text():
        st.success("Latest test results are below.")
        st.markdown(rep.read_text())
    else:
        st.info("The test hasn't been run yet.")
    if os.getenv("ANTHROPIC_API_KEY"):
        with st.expander("▶ Run the test (owner only, about 5 minutes)"):
            use_openai = bool(os.getenv("OPENAI_API_KEY"))
            jp, jm = ("openai", C.JUDGE_MODEL) if use_openai else ("anthropic", "claude-opus-5-5")
            pw = st.text_input("Password", type="password")
            ok = (pw == secret("EVAL_PASSWORD")) if secret("EVAL_PASSWORD") else True
            if st.button("Run the test", disabled=not ok):
                import sys, types
                sys.path.insert(0, str(ROOT / "evals"))
                import run_evals
                box, lines = st.empty(), []
                def log(m):
                    lines.append(m); box.code("\n".join(lines[-12:]))
                with st.spinner("Running 20 practice requests…"):
                    run_evals.evaluate(types.SimpleNamespace(stub=False, model=C.MAIN_MODEL, fast=C.FAST_MODEL, strong=C.STRONG_MODEL,
                                                             judge_provider=jp, judge_model=jm, skip_judge=False, skip_tiers=False), log=log)
                st.rerun()
    for f, label in [(rep, "⬇ Download full test report"), (ROOT / "results" / "team_scores.csv", "⬇ Download scoring sheet for your team")]:
        if f.exists() and "STUB RUN" not in f.read_text():
            st.download_button(label, f.read_bytes(), file_name=f.name)

# ---------------- ABOUT ----------------
with t_about:
    st.markdown("""
**The problem.** Brands want real people to try their products. Dinner hosts work hard and earn nothing.
Setting up one small sponsorship by hand (find the host, agree a price, ship samples, check proof, pay) takes 3–4 hours,
so it's not worth it for a $300 deal.

**The idea.** Like Uber connects riders and drivers, **Hyperlocal connects brands and dinner hosts.**
The app does those 3–4 hours of work in about a minute.

**Who wins?**
- 🥛 **Brand:** real people try the product, at a fixed, known cost.
- 👩‍🍳 **Host:** gets paid ~$150–450 for about 1.5 hours of extra work. Never shares guest details.
- 🏢 **Us:** we keep a 25% fee. Doing this by hand costs ~$140 of staff time per deal, so it loses money.
  With the app it costs a few cents of AI plus a few minutes of a person checking unusual cases, so it makes money.

**How the app thinks.** AI does only the *thinking* (understand the request, judge which dinner fits,
write the message, check photos). **Fixed rules** handle money, dates and payment, so the AI can never overspend or pay by mistake.
""")
