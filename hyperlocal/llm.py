"""Thin provider layer: Anthropic, OpenAI (for the cross-model judge), and an
offline stub so the pipeline can be smoke-tested without API keys.

Every call is logged (model, latency, tokens, cost) so evals can report
latency and cost per 100 runs from real usage, not estimates."""
import json, os, re, time
from dataclasses import dataclass, field
from .config import PRICES


@dataclass
class CallLog:
    calls: list = field(default_factory=list)

    def add(self, **kw):
        self.calls.append(kw)

    def totals(self):
        return {
            "llm_calls": len(self.calls),
            "latency_s": round(sum(c["latency_s"] for c in self.calls), 3),
            "input_tokens": sum(c["in_tok"] for c in self.calls),
            "output_tokens": sum(c["out_tok"] for c in self.calls),
            "cost_usd": round(sum(c["cost"] for c in self.calls), 6),
        }


def _cost(model, i, o):
    pin, pout = PRICES.get(model, (0, 0))
    return (i * pin + o * pout) / 1e6


class LLM:
    def __init__(self, model, provider=None, log=None):
        self.model = model
        self.provider = provider or ("stub" if model == "stub" else
                                     "openai" if model.startswith("gpt") else "anthropic")
        self.log = log if log is not None else CallLog()
        if self.provider == "anthropic":
            import anthropic
            self.client = anthropic.Anthropic()
        elif self.provider == "openai":
            from openai import OpenAI
            self.client = OpenAI()

    def complete(self, system, user, step, max_tokens=1200, images=None):
        """images: optional list of (bytes, media_type) — sent to Claude's vision."""
        t = time.time()
        if self.provider == "anthropic":
            content = user
            if images:
                import base64
                content = [{"type": "image", "source": {"type": "base64", "media_type": mt,
                            "data": base64.b64encode(b).decode()}} for b, mt in images] + [{"type": "text", "text": user}]
            kw = dict(model=self.model, max_tokens=max_tokens, system=system,
                      messages=[{"role": "user", "content": content}])
            try:
                r = self.client.messages.create(temperature=0, **kw)
            except Exception as e:  # some models reject temperature; retry with defaults
                if "temperature" not in str(e).lower():
                    raise
                r = self.client.messages.create(**kw)
            text = "".join(b.text for b in r.content if b.type == "text")
            i, o = r.usage.input_tokens, r.usage.output_tokens
        elif self.provider == "openai":
            r = self.client.chat.completions.create(model=self.model, max_completion_tokens=max_tokens,
                                                    messages=[{"role": "system", "content": system},
                                                              {"role": "user", "content": user}])
            text = r.choices[0].message.content
            i, o = r.usage.prompt_tokens, r.usage.completion_tokens
        else:
            from . import stub
            text = stub.respond(step, user + (" [image attached]" if images else ""))
            i, o = len(system + user) // 4, len(text) // 4
        lat = time.time() - t
        self.log.add(step=step, model=self.model, latency_s=lat, in_tok=i, out_tok=o,
                     cost=_cost(self.model, i, o))
        return text

    def complete_json(self, system, user, step, max_tokens=1200, images=None):
        sys_ = system + "\nRespond with a single JSON object only, no prose."
        text = self.complete(sys_, user, step, max_tokens, images)
        try:
            return parse_json(text)
        except (ValueError, IndexError):  # one retry on malformed JSON
            return parse_json(self.complete(sys_ + " Your last reply was not valid JSON.", user, step, max_tokens, images))


def parse_json(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=0)
    return json.loads(text[start:text.rfind("}" if text[start] == "{" else "]") + 1])
