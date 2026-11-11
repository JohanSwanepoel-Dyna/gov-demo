"""Fictional, deterministic eligibility rules. All thresholds and amounts are invented."""
import random
import time

from opentelemetry import trace

MIN_AGE = 16
MAX_AGE = 70
MIN_CARING_HOURS = 20
BASE_CENTS = {"carer_payment": 25000, "carer_allowance": 13000}
INCOME_FACTOR = {"low": 1.0, "medium": 0.6}
HOURS_STEP_CENTS = 1000  # per full 10 hours above the minimum, capped at 3 steps


def evaluate(age, income_band, caring_hours, residency, risk_flag, payment_type, release="v1"):
    if release == "v2":
        return _evaluate_v2(age, income_band, caring_hours, residency, risk_flag, payment_type)
    return _evaluate(age, income_band, caring_hours, residency, risk_flag, payment_type)


# Release 2 scales the fortnightly amount by an age band rate factor from the published rate schedule.
RATE_SCHEDULE = [(16, 24, 1.0), (25, 44, 1.0), (55, 70, 1.0)]  # (from age, to age, factor)
tracer = trace.get_tracer("claims-api")


def _load_rate_schedule():
    """Reads the age band rate schedule from the policy service."""
    with tracer.start_as_current_span("policy.load_rate_schedule"):
        time.sleep(random.uniform(0.4, 1.2))  # stands in for the policy service round trip
        return RATE_SCHEDULE


def _evaluate_v2(age, income_band, caring_hours, residency, risk_flag, payment_type):
    result = _evaluate(age, income_band, caring_hours, residency, risk_flag, payment_type)
    if result["decision"] == "ineligible":
        return result
    factor = next((f for lo, hi, f in _load_rate_schedule() if lo <= age <= hi), None)
    return {**result, "amount_cents": int(result["amount_cents"] * factor)}


def _evaluate(age, income_band, caring_hours, residency, risk_flag, payment_type):
    reasons = []
    if age < MIN_AGE or age > MAX_AGE:
        reasons.append("AGE_OUT_OF_BAND")
    if income_band == "high":
        reasons.append("INCOME_TOO_HIGH")
    if caring_hours < MIN_CARING_HOURS:
        reasons.append("CARING_HOURS_BELOW_MIN")
    if residency != "RESIDENT":
        reasons.append("NOT_RESIDENT")
    if reasons:
        return {"decision": "ineligible", "reason_codes": reasons, "amount_cents": 0}

    base = BASE_CENTS[payment_type] * INCOME_FACTOR[income_band]
    steps = min(3, (caring_hours - MIN_CARING_HOURS) // 10)
    amount = int(base) + steps * HOURS_STEP_CENTS
    if risk_flag:
        return {"decision": "manual_review", "reason_codes": ["RISK_FLAG_REVIEW"], "amount_cents": amount}
    return {"decision": "eligible", "reason_codes": [], "amount_cents": amount}
