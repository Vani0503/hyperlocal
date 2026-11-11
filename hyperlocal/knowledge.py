"""Knowledge source: the event catalog (data/events.json).

Why RETRIEVAL, not context:
- The catalog is the only input that grows without bound (every host, every
  platform, every week) and changes daily (freshness, opt-outs, cancellations).
- Any one brand brief needs ~5 relevant events out of hundreds/thousands.
  Stuffing the whole catalog into the prompt makes cost scale with catalog
  size and dilutes the fit judgment with irrelevant rows.
- So: deterministic filters remove ineligible rows, BM25 ranks what is left,
  and only the top-k rows are placed in the AI's context.

Why the brief, rules and agreement go in CONTEXT instead: they are small,
fixed per run, and every step needs all of them.
"""
import json, math, re
from collections import Counter
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
_tok = lambda s: re.findall(r"[a-z0-9+]+", s.lower())


def load_events(path=DATA / "events.json"):
    return json.loads(Path(path).read_text())


def event_text(e):
    return " ".join([e["title"], e["format"], e["description"], " ".join(e["tags"]), e["neighborhood"]])


class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.docs = [_tok(d) for d in docs]
        self.k1, self.b = k1, b
        self.avg = sum(map(len, self.docs)) / max(len(self.docs), 1)
        df = Counter(t for d in self.docs for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query):
        q = _tok(query)
        out = []
        for d in self.docs:
            tf = Counter(d)
            s = 0.0
            for t in q:
                if t in tf:
                    s += self.idf[t] * tf[t] * (self.k1 + 1) / (tf[t] + self.k1 * (1 - self.b + self.b * len(d) / self.avg))
            out.append(s)
        return out


def retrieve(events, query, k):
    """Rank already-eligible events by BM25 relevance to the brand query."""
    if not events:
        return []
    s = BM25([event_text(e) for e in events]).scores(query)
    ranked = sorted(zip(events, s), key=lambda x: -x[1])
    return [dict(e, retrieval_score=round(sc, 3)) for e, sc in ranked[:k]]
