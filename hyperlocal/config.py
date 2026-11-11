"""All tunable numbers live here so rules stay auditable."""
import os

# ---- Models -------------------------------------------------------------
# Two tiers compared in evals. Main pipeline uses MAIN_MODEL.
FAST_MODEL = os.getenv("FAST_MODEL", "claude-haiku-5-5")
STRONG_MODEL = os.getenv("STRONG_MODEL", "claude-sonnet-5-5")
MAIN_MODEL = os.getenv("MAIN_MODEL", STRONG_MODEL)
# Cross-model judge: a different model family than the agent, so it does not
# share the agent's blind spots. Override with JUDGE_MODEL / JUDGE_PROVIDER.
JUDGE_PROVIDER = os.getenv("JUDGE_PROVIDER", "openai")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "gpt-6-sol")

# USD per 1M tokens (input, output). Standard API list prices, Nov 2026 —
# verify at https://platform.claude.com/docs/en/about-claude/pricing
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),   # prompts <=100K tokens
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "gpt-6-sol": (2.00, 10.00),
    "stub": (0.0, 0.0),
}

# ---- Business rules (deterministic) ------------------------------------
FRESHNESS_DAYS = 45            # listing must be verified within N days
RETRIEVAL_TOP_K = 6            # candidates sent to the AI fit step
FIT_THRESHOLD = 3              # 0-5; below this we never make an offer
PRICE_BASE = 100               # host fee = base + per_guest * guests
PRICE_PER_GUEST = 12
MATERIALS_PER_GUEST = 3        # samples / printing, billed to brand
SHIPPING_FLAT = 25
MAX_NEGOTIATION_ROUNDS = 1     # one counter, then escalate to a person
EVIDENCE_WINDOW_DAYS = 14      # later than this -> human review
MIN_ATTENDANCE_RATIO = 0.5     # below this -> human review
EVIDENCE_CONFIDENCE_MIN = 0.75 # AI verdict below this -> human review
PAYMENT_DUE_DAYS = 7           # host paid within N days of approval
MAX_OFFER_WORDS = 160
