# 🍽️ Hyperlocal

**An app that helps brands put their product into small dinner parties in New York.**

---

## The problem

- **Brands** (for example, an oat milk company) want real people to try their product.
- **Dinner party hosts** cook for 10–30 guests. They work hard and usually earn nothing.
- A brand could pay a host to serve its product at a dinner. But setting up **one** small deal by hand takes 3–4 hours:
  find the host, agree a price, send samples, check it happened, pay the host.
- That's too much work for a $300 deal, so it doesn't happen.

## The idea

**Like Uber connects riders and drivers, Hyperlocal connects brands and dinner hosts.**

The app does those 3–4 hours of work in about 1 minute.

## A simple example

1. **Leafline** (an oat milk brand) types:
   *"We want 3 dinners in Brooklyn in December. Budget $1,200. Max $300 per dinner."*
2. The app finds **Maya's dinner party**: 18 guests who like healthy, plant-based food.
3. The app offers Maya **$300** to serve Leafline oat milk, and writes her a friendly message.
4. The app plans when to ship the oat milk to Maya.
5. After the dinner, Maya sends photos. The app checks them:
   - ✅ Oat milk is in the photos → **pay Maya**
   - 🔄 Another brand is in the photos → **don't pay**
   - 🌫️ Photos are blurry → **a person checks**
   - ❌ Dinner was cancelled → **no payment**

## Who wins?

| Who | What they get |
|---|---|
| 🥛 Brand | Real people try the product, at a fixed price |
| 👩‍🍳 Host | Gets paid (~$150–450) for about 1.5 hours of extra work. Never shares guest details |
| 🏢 Us | We keep a 25% fee. By hand, each deal costs ~$140 of staff time and loses money. With the app it costs a few cents, so it makes money |

## How the app "thinks"

- **AI** does only the **thinking** jobs: understanding the request, choosing which dinner fits, writing the message, checking the photos.
- **Fixed rules** do the **money and safety** jobs: budget, dates, prices, payment.
  So the AI can **never** spend too much or pay by mistake.

## What's inside the app

| Tab | What it is |
|---|---|
| 🚀 **Try it** | Type what a brand wants, click the button, see the result |
| 🍽️ **Dinners** | The list of 30 dinner parties the app can choose from (sample data, made up for this demo) |
| 📝 **Test score** | An exam for the app: 20 practice requests with correct answers. We check how many it gets right |
| ℹ️ **About** | This explanation |

---

## For the teacher / technical details

| Requirement | Where it is |
|---|---|
| Works end to end | `app.py` (web app) and `run.py` (command line) run all 5 steps on any request |
| AI only where judgment is needed | AI: understand request, judge fit, write message, check photos. Rules: everything else, in `hyperlocal/rules.py` |
| One knowledge source | The dinner list `data/events.json`. The app **searches** it (BM25) instead of giving the AI the whole list, because a real list would be huge and change every day. The brand's request and rules are small, so the AI always sees them |
| 20 golden cases | `data/golden.json`: 20 practice requests with correct answers, including tricky ones (missing budget, whiskey brand, wrong brand in photos, host cancelled) |
| Team scores, judge, agreement rate | `results/team_scores.csv` for the team. A second AI from another company grades 10 cases, and we measure how often it agrees with the team |
| Top 3 failure patterns | Created automatically in the test report |
| Two model tiers | The same 10 cases on Claude Haiku 5.5 (fast, cheap) and Claude Sonnet 5.5 (smarter): speed, cost per 100 runs, quality |
| Economic value | Above, and calculated in `evals/economics.py` |

**Run the test:** in the app, open **📝 Test score → Run the test**. Or on a computer: `python evals/run_evals.py`.

**Files:** `app.py` is the screen · `hyperlocal/agent.py` is the robot brain (the 5 steps) · `hyperlocal/rules.py` has the fixed rules ·
`data/` has the dinners and practice requests · `evals/` has the test.
