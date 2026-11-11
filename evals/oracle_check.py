"""Sanity check: feed the pipeline PERFECT AI answers (taken from the golden
expectations). Every case should then score 100%. If not, the bug is in the
rules or the golden labels, not the model. Run: python evals/oracle_check.py"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "evals"))
from hyperlocal import agent
from hyperlocal.llm import LLM, CallLog
from hyperlocal.knowledge import DATA
from scoring import score_case

EVID = {"release": ("met", .95), "dispute": ("not_met", .9), "human_review": ("unclear", .4)}


class Oracle(LLM):
    def __init__(self, case):
        self.model, self.provider, self.log, self.c = "stub", "oracle", CallLog(), case

    def complete(self, system, user, step, max_tokens=0):
        e = self.c["expect"]
        if step == "extract":
            f = {"num_events": 1, "boroughs": [], "min_guests": 0, "product_category": "food", "audience": self.c["brief"],
                 "date_start": "2026-12-01", "date_end": "2027-02-28", "per_event_cap": 300, "budget_total": 1000}
            f.update(e["fields"]); return json.dumps(f)
        if step == "fit":
            evs = json.loads(user.split("EVENTS:\n", 1)[1])
            sc = lambda i: 5 if i in e.get("must_include_any", []) + e.get("must_escalate", []) else 4 if i in e.get("acceptable", []) else 1
            return json.dumps({"scores": [{"id": x["id"], "fit_score": sc(x["id"]), "reason": "oracle"} for x in evs]})
        if step == "offer":
            import re
            fee = re.search(r"Fee: (\$\d+)", user).group(1); brand = e["fields"]["brand_name"]
            return f"{brand} offers {fee}. Materials ship free; you can decline."
        v, conf = EVID.get(e["payment"], ("met", .95))
        return json.dumps({"verdict": v, "confidence": conf, "reason": "oracle"})


g = json.load(open(DATA / "golden.json"))
bad = 0
for c in g["cases"]:
    out = agent.run(c["brief"], c["evidence"], today=g["today"], llm=Oracle(c))
    s = score_case(c, out)
    fails = [f"{x['check']}: {x['detail']}" for x in s["checks"] if not x["pass"]]
    bad += bool(fails)
    print(c["id"], "OK" if not fails else fails)
print("all consistent" if not bad else f"{bad} inconsistent cases")
