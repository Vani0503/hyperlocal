"""Run the agent end to end on one brief.

  python run.py --brief "Leafline oat milk, 3 Brooklyn dinners in December, $1,200 total, $300 cap"
  python run.py --brief-file my_brief.txt --evidence-file evidence.json
  python run.py --case G01            # a golden case
  add --model stub to run offline, --trace to print every step
"""
import argparse, json, sys
from hyperlocal import agent
from hyperlocal.knowledge import DATA

p = argparse.ArgumentParser()
p.add_argument("--brief"); p.add_argument("--brief-file"); p.add_argument("--evidence-file")
p.add_argument("--case"); p.add_argument("--model"); p.add_argument("--today", default="2026-11-15")
p.add_argument("--trace", action="store_true")
a = p.parse_args()

evidence = json.load(open(a.evidence_file)) if a.evidence_file else None
if a.case:
    c = next(c for c in json.load(open(DATA / "golden.json"))["cases"] if c["id"] == a.case)
    brief, evidence = c["brief"], c["evidence"]
else:
    brief = a.brief or (open(a.brief_file).read() if a.brief_file else sys.exit("give --brief, --brief-file or --case"))

r = agent.run(brief, evidence, today=a.today, model=a.model)
if not a.trace:
    r.pop("trace")
    for x in r.get("agreements", []): x.pop("fit_reason", None)
print(json.dumps(r, indent=2, default=str))
