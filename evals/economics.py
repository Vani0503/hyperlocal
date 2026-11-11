"""Unit economics per completed sponsorship. Inputs marked MEASURED come from
the eval run; ASSUMPTION values are placeholders to replace with pilot data."""

ASSUMPTIONS = {
    "manual_hours_per_sponsorship": 3.5,   # find, agree, ship, verify, pay — agency/manual baseline
    "ops_hourly_cost": 40.0,               # loaded cost of an ops coordinator, USD
    "minutes_per_human_touch": 10,         # escalation, confirmation, review, dispute
    "first_batch_approval_minutes": 3,     # brand/ops approves each AI match + offer in batch 1
    "platform_take_rate": 0.25,            # charged to brand on top of host fee
    "payment_pct": 0.029, "payment_fixed": 0.30,
    "host_hours": 1.5,                     # receive box, set out samples, 2 photos, form, reply to offer
}


def model(avg_host_fee, llm_cost_per_case, human_touch_rate, agreements_per_case, a=ASSUMPTIONS):
    take = a["platform_take_rate"] * avg_host_fee
    llm = llm_cost_per_case / max(agreements_per_case, 1e-9)
    human_ai = (human_touch_rate * a["minutes_per_human_touch"] / max(agreements_per_case, 1e-9)
                + a["first_batch_approval_minutes"]) / 60 * a["ops_hourly_cost"]
    pay = a["payment_pct"] * (avg_host_fee + take) + a["payment_fixed"]
    manual = a["manual_hours_per_sponsorship"] * a["ops_hourly_cost"]
    return {
        "avg_host_fee": round(avg_host_fee, 2),
        "platform_revenue": round(take, 2),
        "llm_cost": round(llm, 4),
        "human_review_cost": round(human_ai, 2),
        "payment_processing": round(pay, 2),
        "contribution_margin": round(take - llm - human_ai - pay, 2),
        "manual_coordination_cost": round(manual, 2),
        "manual_margin": round(take - manual - pay, 2),
        "host_effective_hourly": round(avg_host_fee / a["host_hours"], 2),
        "breakeven_fee_manual": round(manual / a["platform_take_rate"], 0),
    }
